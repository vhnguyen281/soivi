"""Check that URLs are reachable, allowed by robots.txt, and look like what we expect.

Uses PoliteHttp, so it follows the same rules as the pipeline: robots.txt,
one request per host every 5 s, retries with backoff, honest User-Agent.

    uv run python -m pipeline.fetch.url_check --seeds        # check data/seeds/*.csv
    uv run python -m pipeline.fetch.url_check urls.csv       # columns: key,url,expect

`expect` is a regex searched (case-insensitively) in the page text; empty = any.
PDFs are read with pdfplumber (first 3 pages). Pages that need JavaScript usually
fail the `expect` check: that is reported, not hidden.
"""

import csv
import io
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pipeline.fetch.polite import FetchError, PoliteHttp

SEEDS_DIR = Path(__file__).resolve().parents[2] / "data" / "seeds"

# What each source kind's page should mention.
EXPECT_BY_KIND = {
    "savings_rate_page": r"l(ã|a)i\s*su(ấ|a)t",
    "card_tariff_pdf": r"(bi(ể|e)u\s*ph(í|i)|ph(í|i)\s*th(ư|u)(ờ|o)ng\s*ni(ê|e)n)",
    "card_product_page": r"th(ẻ|e)\s*t(í|i)n\s*d(ụ|u)ng",
}


@dataclass
class Check:
    key: str
    url: str
    status: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    robots_ok: bool | None = None
    matched: bool | None = None
    error: str | None = None
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)

    @property
    def ok(self) -> bool:
        return bool(self.robots_ok and self.status == 200 and self.matched is not False)


class _TextAndLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor).strip()))
            self._href = None

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)
            if self._href is not None:
                self._anchor.append(data.strip())


def html_text_and_links(html: str, base_url: str) -> tuple[str, list[tuple[str, str]]]:
    p = _TextAndLinks()
    p.feed(html)
    links = [(urljoin(base_url, href), text) for href, text in p.links]
    return " ".join(" ".join(p.parts).split()), links


def pdf_text(data: bytes, pages: int = 3) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return " ".join((page.extract_text() or "") for page in pdf.pages[:pages])


def check(client: PoliteHttp, key: str, url: str, expect: str = "") -> Check:
    result = Check(key=key, url=url)
    try:
        result.robots_ok = client.allowed(url)
        if not result.robots_ok:
            result.error = "disallowed by robots.txt (or robots.txt unreadable)"
            return result
        r = client.request(url)
    except FetchError as exc:
        result.error = str(exc)[:200]
        return result

    result.status = r.status_code
    result.final_url = str(r.url)
    result.content_type = r.headers.get("content-type", "").split(";")[0] or None
    if r.status_code != 200:
        return result
    try:
        if result.content_type == "application/pdf" or r.content[:5] == b"%PDF-":
            result.text = pdf_text(r.content)
        else:
            result.text, result.links = html_text_and_links(r.text, result.final_url)
    except Exception as exc:  # a broken file is a finding, not a crash
        result.error = f"could not read body: {type(exc).__name__}"
    if expect:
        result.matched = bool(re.search(expect, result.text, re.IGNORECASE))
    return result


def interleave(items: Iterable[tuple[str, str, str]]) -> Iterator[tuple[str, str, str]]:
    """Round-robin by host so the per-host delay rarely makes us wait."""
    by_host: dict[str, list[tuple[str, str, str]]] = {}
    for item in items:
        by_host.setdefault(urlsplit(item[1]).netloc, []).append(item)
    queues = list(by_host.values())
    while queues:
        for q in list(queues):
            yield q.pop(0)
            if not q:
                queues.remove(q)


def seed_targets(seeds_dir: Path = SEEDS_DIR) -> list[tuple[str, str, str]]:
    targets: list[tuple[str, str, str]] = []
    with (seeds_dir / "institutions.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["website"]:
                targets.append((f"{row['short_name']}/website", row["website"], ""))
    with (seeds_dir / "sources.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["url"]:
                key = f"{row['institution']}/{row['kind']}"
                targets.append((key, row["url"], EXPECT_BY_KIND.get(row["kind"], "")))
    return targets


def main(argv: list[str]) -> int:
    if argv == ["--seeds"]:
        targets = seed_targets()
    elif len(argv) == 1:
        with open(argv[0], encoding="utf-8") as f:
            targets = [(r["key"], r["url"], r.get("expect", "")) for r in csv.DictReader(f)]
    else:
        print(__doc__, file=sys.stderr)
        return 2

    client = PoliteHttp()
    out = csv.writer(sys.stdout)
    out.writerow(
        ["key", "ok", "status", "robots_ok", "matched", "content_type", "final_url", "error"]
    )
    failures = 0
    try:
        for key, url, expect in interleave(targets):
            c = check(client, key, url, expect)
            failures += not c.ok
            out.writerow(
                [key, c.ok, c.status, c.robots_ok, c.matched, c.content_type, c.final_url, c.error]
            )
            sys.stdout.flush()
    finally:
        client.close()
    print(f"{len(targets) - failures}/{len(targets)} ok", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
