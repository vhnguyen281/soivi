"""Feed config (feeds.yaml) and parsing of RSS feeds and section pages into entries."""

import datetime as dt
import html
import re
import unicodedata
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

import yaml
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from pipeline.extract.vietnamese import clean, fold

FEEDS_FILE = Path(__file__).with_name("feeds.yaml")
SUMMARY_MAX = 1000  # characters kept from a feed's description


class FeedError(Exception):
    """A feed's content can't be read as configured (not RSS, no items, ...)."""


@dataclass(frozen=True)
class Feed:
    name: str
    publisher: str
    kind: Literal["rss", "html"]
    url: str
    pubdate_is_local: bool = False
    link_pattern: str | None = None  # html feeds only


@dataclass(frozen=True)
class NewsOptions:
    dedupe_title_days: int = 7
    recheck_window_hours: int = 48
    recheck_cooldown_minutes: int = 30
    llm_max_per_run: int = 30


@dataclass(frozen=True)
class FeedConfig:
    feeds: tuple[Feed, ...]
    options: NewsOptions = field(default_factory=NewsOptions)

    def get(self, name: str) -> Feed:
        for feed in self.feeds:
            if feed.name == name:
                return feed
        raise LookupError(f"no feed named {name!r} in feeds.yaml")


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str
    summary: str | None
    published_at: dt.datetime | None


def load_config(path: Path = FEEDS_FILE) -> FeedConfig:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    feeds = []
    for item in raw.get("feeds") or []:
        feed = Feed(**item)
        if feed.kind not in ("rss", "html"):
            raise ValueError(f"feed {feed.name}: kind must be rss or html")
        if feed.kind == "html" and not feed.link_pattern:
            raise ValueError(f"feed {feed.name}: html feeds need link_pattern")
        if not feed.url.startswith("https://"):
            raise ValueError(f"feed {feed.name}: url must be https")
        feeds.append(feed)
    names = [f.name for f in feeds]
    if len(names) != len(set(names)):
        raise ValueError("feed names must be unique")
    return FeedConfig(tuple(feeds), NewsOptions(**(raw.get("options") or {})))


# --------------------------------------------------------------------------- normalising

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|zarsrc$)")


def canonical_url(url: str) -> str | None:
    """Strip the fragment and tracking parameters; None for anything but http(s)."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def title_key(title: str) -> str:
    """'Lãi suất: VCB tăng!' -> 'lai suat vcb tang' (to spot one story in two feeds)."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", fold(title)).split())


def _text(fragment: str | None) -> str:
    """Plain text from an HTML fragment (feed descriptions carry <a><img> markup)."""
    if not fragment:
        return ""
    without_tags = re.sub(r"<[^>]*>", " ", fragment)
    return clean(html.unescape(without_tags))


def _published(value: str | None, feed: Feed, tz: ZoneInfo) -> dt.datetime | None:
    if not value or not value.strip():
        return None
    try:
        when = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None or feed.pubdate_is_local:
        when = when.replace(tzinfo=tz)
    return when.astimezone(dt.UTC)


# --------------------------------------------------------------------------- parsing


def parse(content: bytes, feed: Feed, tz: ZoneInfo) -> list[FeedEntry]:
    entries = parse_rss(content, feed, tz) if feed.kind == "rss" else parse_html(content, feed)
    if not entries:
        raise FeedError(f"{feed.name}: no items found")
    return entries


def parse_rss(content: bytes, feed: Feed, tz: ZoneInfo) -> list[FeedEntry]:
    try:
        root: Element = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise FeedError(f"{feed.name}: not valid XML ({exc})") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise FeedError(f"{feed.name}: not an RSS 2.0 document (root <{root.tag}>)")
    entries = []
    for item in root.iter("item"):
        title = clean(html.unescape(item.findtext("title") or ""))
        link = item.findtext("link") or ""
        guid = item.find("guid")
        if not link.strip() and guid is not None and guid.get("isPermaLink") != "false":
            link = guid.text or ""
        url = canonical_url(link)
        if not title or url is None:
            continue
        summary = _text(item.findtext("description"))[:SUMMARY_MAX] or None
        published = _published(item.findtext("pubDate"), feed, tz)
        entries.append(FeedEntry(url, title, summary, published))
    return entries


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text)))
            self._href = None


def parse_html(content: bytes, feed: Feed) -> list[FeedEntry]:
    """Links on a section page whose absolute URL matches the feed's link_pattern.
    A story is often linked twice (image, then headline): the first text wins."""
    assert feed.link_pattern
    pattern = re.compile(feed.link_pattern)
    parser = _Links()
    parser.feed(unicodedata.normalize("NFC", content.decode("utf-8", errors="replace")))
    titles: dict[str, str] = {}
    for href, text in parser.links:
        url = canonical_url(urljoin(feed.url, href))
        if url is None or not pattern.fullmatch(url):
            continue
        title = clean(text)
        if title and not titles.get(url):
            titles[url] = title
        else:
            titles.setdefault(url, "")
    return [FeedEntry(url, title, None, None) for url, title in titles.items() if title]
