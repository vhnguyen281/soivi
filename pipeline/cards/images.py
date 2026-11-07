"""Card pictures: find candidates on each card's own bank page, download them politely,
store them with their SHA-256, and leave the choice to a reviewer.

`python -m pipeline card-images` (run it in Docker: VPBank's pages need Chromium):
1. for every active card with a product page, read the latest stored snapshot of that page;
2. pick image URLs whose file name looks like this card (card-name words, "0deg", "masthead",
   "card"), skipping icons, logos, banners and SVGs;
3. if a page has none (pages that load pictures with JavaScript), render it in Chromium;
4. download the best three (robots.txt, 1 request per 5 s per host, honest User-Agent),
   store them in object storage and add a `card_image` row for each new picture.
Nothing is shown on the site until a reviewer approves one picture per card.
"""

import datetime as dt
import hashlib
import html
import io
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import VersionStatus
from core.models import (
    CardImage,
    CardInterest,
    CardPerk,
    CardProduct,
    CardReward,
    CardTerms,
    Institution,
    Snapshot,
)
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import FetchError
from pipeline.fetch.storage import SnapshotStore

KEEP = 3
MAX_BYTES = 3_000_000
IMAGE_EXT = re.compile(r"\.(png|jpe?g|webp)(?:$|[?#])", re.I)
GOOD = ("0deg", "masthead", "card", "the-tin-dung", "credit")
BAD = (
    "banner",
    "icon",
    "logo",
    "popup",
    "search",
    "background",
    "bg-",
    "-bg",
    "thumbnail",
    "avatar",
)
STOP = {
    "the",
    "tin",
    "dung",
    "card",
    "credit",
    "bidv",
    "techcombank",
    "vpbank",
    "goi",
    "dac",
    "quyen",
    "trieu",
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")


def name_tokens(card_name: str) -> list[str]:
    """Distinctive words of a card name: 'BIDV Visa Easy' -> ['visa', 'easy']."""
    words = re.findall(r"[a-z0-9]+", _fold(card_name))
    return [w for w in words if w not in STOP and len(w) > 1]


def image_urls(page_html: str, page_url: str) -> list[str]:
    """Every raster image URL on the page (img src, data-src, srcset, and URLs in inline JSON)."""
    text = html.unescape(page_html).replace("\\u002F", "/").replace("\\/", "/")
    found: list[str] = []
    for m in re.finditer(r"""(?:src|data-src|srcset|href)=["']([^"']+)["']""", text):
        for part in m.group(1).split(","):
            found.append(part.strip().split(" ")[0])
    found += re.findall(
        r"""["'(]((?:https?:)?/[^"'()\s]+?\.(?:png|jpe?g|webp)(?:\?[^"'()\s]*)?)""", text, re.I
    )
    out: list[str] = []
    for raw in found:
        if not raw or not IMAGE_EXT.search(raw):
            continue
        url = urljoin(page_url, raw)
        if urlparse(url).scheme in {"http", "https"} and url not in out:
            out.append(url)
    return out


def score(url: str, tokens: list[str]) -> int:
    name = _fold(urlparse(url).path.rsplit("/", 1)[-1])
    path = _fold(urlparse(url).path)
    points = 3 * sum(
        1
        for t in tokens
        if t in name.replace("+", "").replace("-", "").replace("_", "") or t in name
    )
    points += sum(2 for g in GOOD if g in path)
    points -= sum(4 for b in BAD if b in path)
    return points


def candidates(
    page_html: str, page_url: str, card_name: str, keep: int = KEEP
) -> list[tuple[str, int]]:
    """The best `keep` (url, score) pairs with a positive score, best first."""
    tokens = name_tokens(card_name)
    scored = [(u, score(u, tokens)) for u in image_urls(page_html, page_url)]
    scored = [s for s in scored if s[1] > 0]
    scored.sort(key=lambda s: -s[1])
    return scored[:keep]


def _dimensions(data: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return im.width, im.height
    except Exception:
        return None, None


def product_pages(session: Session) -> dict[int, tuple[str, str, str]]:
    """card id -> (bank, card name, product page URL) from the snapshots of approved values."""
    pages: dict[int, str] = {}
    for model in (CardPerk, CardReward, CardInterest, CardTerms):
        rows = session.execute(
            select(model.card_product_id, Snapshot.url, Snapshot.content_type)
            .join(Snapshot, Snapshot.id == model.snapshot_id)
            .where(model.status == VersionStatus.APPROVED)
        )
        for card_id, url, ctype in rows:
            is_page = "html" in (ctype or "") and not url.lower().split("?")[0].endswith(".pdf")
            # Prefer the card's own page over a shared list page (the longer path).
            if is_page and (card_id not in pages or len(url) > len(pages[card_id])):
                pages[card_id] = url
    names = session.execute(
        select(CardProduct.id, Institution.short_name, CardProduct.name)
        .join(Institution, Institution.id == CardProduct.institution_id)
        .where(CardProduct.active.is_(True))
    )
    return {cid: (bank, name, pages[cid]) for cid, bank, name in names if cid in pages}


@dataclass
class Found:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # already stored
    none: list[str] = field(default_factory=list)  # no candidate on the page
    failed: list[str] = field(default_factory=list)


def discover(
    session: Session, fetchers: Fetchers, store: SnapshotStore, only: set[int] | None = None
) -> Found:
    from core.enums import FetchMethod

    found = Found()
    for card_id, (bank, name, page) in sorted(product_pages(session).items()):
        if only and card_id not in only:
            continue
        label = f"{bank} {name}"
        snap = session.scalar(
            select(Snapshot)
            .where(Snapshot.url == page)
            .order_by(Snapshot.fetched_at.desc())
            .limit(1)
        )
        picks: list[tuple[str, int]] = []
        if snap is not None:
            picks = candidates(store.get(snap.storage_key).decode("utf-8", "ignore"), page, name)
        if not picks:
            try:
                rendered = fetchers.for_method(FetchMethod.BROWSER).fetch(page)
                picks = candidates(rendered.content.decode("utf-8", "ignore"), page, name)
            except FetchError as exc:
                found.failed.append(f"{label}: {exc}")
                continue
        if not picks:
            found.none.append(label)
            continue
        for url, points in picks:
            try:
                got = fetchers.for_method(FetchMethod.HTTP).fetch(url)
            except FetchError as exc:
                found.failed.append(f"{label}: {url}: {exc}")
                continue
            ctype = (got.content_type or "").split(";")[0].strip().lower()
            if (
                not ctype.startswith("image/")
                or ctype == "image/svg+xml"
                or len(got.content) > MAX_BYTES
            ):
                found.failed.append(
                    f"{label}: {url}: not a usable image ({ctype}, {len(got.content)} bytes)"
                )
                continue
            sha = hashlib.sha256(got.content).hexdigest()
            if session.scalar(
                select(CardImage.id).where(
                    CardImage.card_product_id == card_id, CardImage.sha256 == sha
                )
            ):
                found.skipped.append(f"{label}: {url}")
                continue
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(ctype, "img")
            key = f"card-images/{sha}.{ext}"
            store.put(key, got.content, ctype)
            width, height = _dimensions(got.content)
            session.add(
                CardImage(
                    card_product_id=card_id,
                    page_url=page,
                    image_url=url,
                    sha256=sha,
                    storage_key=key,
                    content_type=ctype,
                    size_bytes=len(got.content),
                    width=width,
                    height=height,
                    score=points,
                    fetched_at=got.fetched_at or dt.datetime.now(dt.UTC),
                )
            )
            session.flush()
            found.added.append(f"{label}: {url}")
    return found
