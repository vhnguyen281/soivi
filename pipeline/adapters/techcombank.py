"""Techcombank: personal savings rates from the published PDF.

Notes in docs/adapters/techcombank.md.
"""

import io
import json
import re
from decimal import Decimal
from typing import Any

import pdfplumber

from core.enums import Channel, ExtractionMethod, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.vietnamese import clean, find_effective_date, parse_rate
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

LISTING_TITLE = "Lãi suất tiền gửi tiết kiệm/Tiền gửi có kỳ hạn"

# Section heading in the PDF -> (product_name, channel, core terms that must be present)
SECTIONS: dict[str, tuple[str, Channel, tuple[str, ...]]] = {
    "TIẾT KIỆM PHÁT LỘC TẠI QUẦY": (
        "Tiết kiệm Phát Lộc",
        Channel.COUNTER,
        ("1M", "6M", "12M", "36M"),
    ),
    "TIỀN GỬI PHÁT LỘC ONLINE": (
        "Tiền gửi Phát Lộc Online",
        Channel.ONLINE,
        ("1M", "6M", "12M", "36M"),
    ),
    "TIỀN GỬI RÚT GỐC LINH HOẠT TẠI QUẦY": (
        "Tiền gửi Rút gốc linh hoạt",
        Channel.COUNTER,
        ("1M", "6M", "12M", "36M"),
    ),
    "TIỀN GỬI RÚT GỐC LINH HOẠT ONLINE": (
        "Tiền gửi Rút gốc linh hoạt Online",
        Channel.ONLINE,
        ("1M", "6M", "12M", "36M"),
    ),
}
# 4 segments (Private, Priority, Inspire, Normal) x 3 amount tiers.
TIER_LINE = re.compile(r"^(?:≥3B 1 - 3B <1B ?){4}(?:\(\*+\))?$")
ROW = re.compile(r"^(KKH|1-3W|\d{1,2}M)((?:\s+\d+\.\d{2}){12})?$")
# Normal-customer columns are the last three: ≥3B, 1-3B, <1B.
NORMAL_TIERS = (3_000_000_000, 1_000_000_000, 0)


@register
class TechcombankSavings(BaseAdapter):
    name = "techcombank_savings"
    institution = "TECHCOMBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.PDF
    extraction_method = ExtractionMethod.PDF_TABLE
    # Source URL: the AEM document listing for personal customers; resolve_url()
    # picks the current savings PDF from it.

    def resolve_url(self) -> str:
        listing = self.ctx.fetchers.for_method(FetchMethod.HTTP).fetch(super().resolve_url())
        return find_document_url(listing.content)

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        if not content.startswith(b"%PDF-"):
            raise AdapterBroken("not a PDF")
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
        except Exception as exc:
            raise AdapterBroken(f"PDF unreadable: {type(exc).__name__}") from exc
        lines = [clean(line) for page in pages for line in page.splitlines()]
        if "BIỂU LÃI SUẤT TIỀN GỬI DÀNH CHO KHÁCH HÀNG CÁ NHÂN" not in lines:
            raise AdapterBroken(
                "title 'BIỂU LÃI SUẤT TIỀN GỬI DÀNH CHO KHÁCH HÀNG CÁ NHÂN' missing"
            )
        effective = find_effective_date(" ".join(lines[:10]))
        if effective is None:
            raise AdapterBroken("no 'Áp dụng từ ngày …' date near the top")
        lines = _vnd_part(lines)

        records: list[Record] = []
        for heading, (product, channel, core) in SECTIONS.items():
            rows = _section_rows(lines, heading)
            missing = [t for t in core if t not in rows]
            if missing:
                raise AdapterBroken(f"{heading}: terms {missing} missing")
            for term, values in rows.items():
                records.extend(_records(product, channel, term, values, effective))
        return records


def find_document_url(listing: bytes) -> str:
    """The current savings PDF from the document listing JSON."""
    try:
        items: list[Any] = json.loads(listing)["data"]["listViewDocumentFragmentList"]["items"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AdapterBroken(f"document listing has an unexpected shape: {exc}") from exc
    matches = [
        item
        for item in items
        if clean((item.get("categoryTitle") or {}).get("plaintext")) == LISTING_TITLE
    ]
    if len(matches) != 1:
        raise AdapterBroken(f"expected one listing entry {LISTING_TITLE!r}, found {len(matches)}")
    url = ((matches[0].get("documentPath") or {}).get("_publishUrl")) or ""
    if not url.startswith("https://techcombank.com/") or not url.endswith(".pdf"):
        raise AdapterBroken(f"listing entry has no techcombank.com PDF: {url!r}")
    return str(url)


VND_START = "I. LÃI SUẤT TIẾT KIỆM/TIỀN GỬI CÓ KỲ HẠN VND"
VND_END = "II. LÃI SUẤT TIẾT KIỆM/TIỀN GỬI CÓ KỲ HẠN NGOẠI TỆ"


def _vnd_part(lines: list[str]) -> list[str]:
    """Section I (VND) only; section II repeats product headings for USD/EUR."""
    try:
        start, end = lines.index(VND_START), lines.index(VND_END)
    except ValueError as exc:
        raise AdapterBroken(f"VND/foreign-currency section headings changed: {exc}") from exc
    if end <= start:
        raise AdapterBroken("foreign-currency section comes before the VND section")
    return lines[start + 1 : end]


def _section_rows(lines: list[str], heading: str) -> dict[str, list[Decimal]]:
    """Rows of one section: {'1M': [12 rates], ...}. Rows with no rates are dropped."""
    starts = [i for i, line in enumerate(lines) if line == heading]
    if len(starts) != 1:
        raise AdapterBroken(f"section {heading!r} found {len(starts)} times")
    i = starts[0] + 1
    while i < len(lines) and not TIER_LINE.match(lines[i]):
        if i - starts[0] > 4:
            raise AdapterBroken(f"{heading}: amount-tier header row not found")
        i += 1
    rows: dict[str, list[Decimal]] = {}
    for line in lines[i + 1 :]:
        m = ROW.match(line)
        if not m:
            break
        term, numbers = m.group(1), m.group(2)
        if numbers is None:
            continue  # e.g. "KKH" with no rate in the flexible tables
        if term in rows:
            raise AdapterBroken(f"{heading}: term {term} appears twice")
        values = [parse_rate(n) for n in numbers.split()]
        rows[term] = [v for v in values if v is not None]
    if not rows:
        raise AdapterBroken(f"{heading}: no rate rows")
    return rows


def _records(
    product: str, channel: Channel, term: str, values: list[Decimal], effective: Any
) -> list[Record]:
    if len(values) != 12:
        raise AdapterBroken(f"{product} {term}: expected 12 rates, got {len(values)}")
    if term == "KKH":
        months, days, band = 0, 0, None
    elif term == "1-3W":
        months, days, band = 0, 7, "Áp dụng cho kỳ hạn 1-3 tuần"
    else:
        months, days, band = int(term[:-1]), 0, None
    normal = values[9:12]
    return [
        SavingsRateRecord(
            product_name=product,
            channel=channel,
            term_months=months,
            term_days=days,
            min_amount_vnd=tier,
            interest_payment=InterestPayment.END,
            rate_pct=rate,
            conditions_text=band,
            effective_from=effective,
        )
        for tier, rate in zip(NORMAL_TIERS, normal, strict=True)
    ]
