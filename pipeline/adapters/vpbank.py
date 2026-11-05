"""VPBank: personal savings rates from an image-only PDF (OCR). Notes in docs/adapters/vpbank.md.

Two stages, so the parsing rules can be tested without Tesseract:

    extract_grids(pdf bytes) -> plain dict of OCR reads   (slow: ~1-2 min, needs Tesseract)
    records_from_grids(dict) -> records                    (pure, strict checks)
"""

import datetime as dt
import io
import json
import re
from decimal import Decimal
from typing import Any

import pdfplumber

from core.enums import Channel, ExtractionMethod, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.ocr import OcrDisagreement, image_boxes, ocr_box, union
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

TERMS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 18, 24, 36]  # header "1T" … "36T"
MIN_CONFIRMED_HEADERS = 15
RATE = re.compile(r"^\d\.\d{2}$")
B = 1_000_000_000

# Tables on page 1, top to bottom. Amount labels are matched in the exact form OCR
# returns with a "0123456789<-" whitelist ("≥ 50 tỷ" reads as "250", every time).
TABLES: list[dict[str, Any]] = [
    {
        "product": "Tiết kiệm thường/Tiền gửi có kỳ hạn lĩnh lãi cuối kỳ",
        "channel": Channel.COUNTER,
        "payment": InterestPayment.END,
        "labels": ["<1", "1-<3", "3-<10", "10-<50", "250"],
        "floors": [0, 1 * B, 3 * B, 10 * B, 50 * B],
        "weeks_column": True,
    },
    {
        "product": "Tiết kiệm thường/Tiền gửi có kỳ hạn lĩnh lãi cuối kỳ",
        "channel": Channel.ONLINE,
        "payment": InterestPayment.END,
        "labels": ["<1", "1-<3", "3-<10", "10-<50", "250"],
        "floors": [0, 1 * B, 3 * B, 10 * B, 50 * B],
        "weeks_column": True,
    },
    {
        # One table for counter and online ("tại Quầy và Online").
        "product": "Tiết kiệm/Tiền gửi có kỳ hạn trả lãi trước",
        "channel": Channel.COUNTER,
        "payment": InterestPayment.UPFRONT,
        "labels": ["<5", "25"],
        "floors": [0, 5 * B],
        "weeks_column": False,
    },
]
DOC_URL = re.compile(r"^/-/media/vpbank-latest/tai-lieu-bieu-mau/lai-suat-huy-dong/khcn/.+\.pdf$")


@register
class VpbankSavings(BaseAdapter):
    name = "vpbank_savings"
    institution = "VPBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.PDF
    extraction_method = ExtractionMethod.OCR
    # Source URL: VPBank's document API for the personal deposit-rate category;
    # resolve_url() takes the newest document's PDF.

    def resolve_url(self) -> str:
        listing = self.ctx.fetchers.for_method(FetchMethod.HTTP).fetch(super().resolve_url())
        return "https://www.vpbank.com.vn" + newest_document_path(listing.content)

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        return records_from_grids(extract_grids(content))


def newest_document_path(listing: bytes) -> str:
    try:
        data = json.loads(listing)["data"]
        newest = data[0]
        items = newest["itemList"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AdapterBroken(f"document listing has an unexpected shape: {exc}") from exc
    if not str(newest.get("title", "")).startswith("Biểu lãi suất huy động dành cho KHCN"):
        raise AdapterBroken(f"newest document is not a KHCN rate sheet: {newest.get('title')!r}")
    pdfs = [i.get("url") for i in items if str(i.get("url", "")).lower().endswith(".pdf")]
    if len(pdfs) != 1 or not DOC_URL.match(pdfs[0]):
        raise AdapterBroken(f"expected one rate-sheet PDF in the newest document, got {pdfs!r}")
    return str(pdfs[0])


# --------------------------------------------------------------------------- stage 1: OCR


def extract_grids(content: bytes) -> dict[str, Any]:
    """OCR page 1 of the rate sheet into a JSON-friendly dict. Unreadable cells are None."""
    if not content.startswith(b"%PDF-"):
        raise AdapterBroken("not a PDF")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            page = pdf.pages[0]
            tables = page.find_tables(
                {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
            )
            if not tables:
                raise AdapterBroken("no ruled tables on page 1")
            # Rates are images today (the page's only text is a few spaces). Real text
            # inside a table means the PDF changed and should be parsed as text instead.
            if any(c["text"].strip() and _inside(c, t.bbox) for c in page.chars for t in tables):
                raise AdapterBroken("rate tables now have a text layer: rewrite as a text parser")
            return {
                "effective": _read(
                    page,
                    (0, 0, page.width, tables[0].bbox[1] - 30),
                    "0123456789/()",
                    psm=6,
                    extract=_date,
                ),
                "tables": [_grid(page, t) for t in tables],
            }
    except AdapterBroken:
        raise
    except Exception as exc:
        raise AdapterBroken(f"PDF unreadable: {type(exc).__name__}: {exc}") from exc


def _inside(char: dict[str, Any], box: tuple[float, float, float, float]) -> bool:
    return bool(box[0] <= char["x0"] <= box[2] and box[1] <= char["top"] <= box[3])


def _grid(page: Any, table: Any) -> dict[str, Any]:
    rows = table.rows
    return {
        "headers": [_read_cell(page, cell, "0123456789T-") for cell in rows[0].cells[2:]],
        "labels": [_read_cell(page, row.cells[0], "0123456789<-") for row in rows[1:]],
        "weeks": _read_cell(page, rows[1].cells[1]) if len(rows) > 1 else None,
        "values": [[_read_cell(page, cell) for cell in row.cells[2:]] for row in rows[1:]],
        "images_per_cell": [
            [len(image_boxes(page, c)) if c else 0 for c in row.cells[2:]] for row in rows[1:]
        ],
    }


def _read_cell(page: Any, cell: Any, whitelist: str = "0123456789.") -> str | None:
    if cell is None:
        return None
    boxes = image_boxes(page, cell)
    if not boxes:
        return None
    return _read(page, union(boxes), whitelist)


def _read(page: Any, box: Any, whitelist: str, psm: int = 7, extract: Any = None) -> str | None:
    try:
        if extract is None:
            return ocr_box(page, box, whitelist, psm)
        return ocr_box(page, box, whitelist, psm, extract=extract)
    except OcrDisagreement:
        return None


def _date(text: str) -> str | None:
    m = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- stage 2: rules


def records_from_grids(data: dict[str, Any]) -> list[Record]:
    effective = _effective(data.get("effective"))
    grids = data.get("tables") or []
    if len(grids) != len(TABLES):
        raise AdapterBroken(f"expected {len(TABLES)} tables on page 1, found {len(grids)}")

    records: list[Record] = []
    for grid, spec in zip(grids, TABLES, strict=True):
        records += _table(grid, spec, effective)
    return records


def _effective(value: Any) -> dt.date:
    if not isinstance(value, str):
        raise AdapterBroken("effective date ('Áp dụng từ ngày …') unreadable")
    day, month, year = (int(x) for x in value.split("/"))
    return dt.date(year, month, day)


def _table(grid: dict[str, Any], spec: dict[str, Any], effective: dt.date) -> list[Record]:
    name = f"{spec['product']} ({spec['channel'].value})"
    _check_headers(grid["headers"], name)
    if grid["labels"] != spec["labels"]:
        raise AdapterBroken(f"{name}: amount tiers changed: {grid['labels']!r}")

    values: list[list[str | None]] = grid["values"]
    if len(values) != len(spec["floors"]) or any(len(row) != len(TERMS) for row in values):
        raise AdapterBroken(f"{name}: grid shape changed")
    if any(n != 1 for row in grid["images_per_cell"] for n in row):
        raise AdapterBroken(f"{name}: a rate cell does not hold exactly one number")

    rates: list[list[Decimal]] = []
    for row in values:
        parsed = []
        for cell in row:
            if cell is None or not RATE.match(cell):
                raise AdapterBroken(f"{name}: unreadable or malformed rate {cell!r}")
            rate = Decimal(cell)
            if not Decimal("0") < rate < Decimal("15"):
                raise AdapterBroken(f"{name}: implausible rate {rate}")
            parsed.append(rate)
        rates.append(parsed)

    # Within a term column, a larger amount never earns less.
    for col, term in enumerate(TERMS):
        column = [row[col] for row in rates]
        if column != sorted(column):
            raise AdapterBroken(f"{name}: {term}T rates fall as the amount rises: {column}")

    records: list[Record] = []
    for floor, tier_rates in zip(spec["floors"], rates, strict=True):
        for term, tier_rate in zip(TERMS, tier_rates, strict=True):
            records.append(_record(spec, term, 0, floor, tier_rate, effective, None))
    if spec["weeks_column"]:
        weeks = grid["weeks"]
        if weeks is None or not RATE.match(weeks):
            raise AdapterBroken(f"{name}: '1-3 tuần' rate unreadable: {weeks!r}")
        # One merged cell for every amount tier.
        records.append(
            _record(spec, 0, 7, 0, Decimal(weeks), effective, "Áp dụng cho kỳ hạn 1-3 tuần")
        )
    return records


def _check_headers(headers: list[str | None], name: str) -> None:
    """Headers are a layout check: each must read as expected or be unreadable."""
    if len(headers) != len(TERMS):
        raise AdapterBroken(f"{name}: {len(headers)} term columns, expected {len(TERMS)}")
    confirmed = 0
    for read, term in zip(headers, TERMS, strict=True):
        if read == f"{term}T":
            confirmed += 1
        elif read and re.fullmatch(r"\d{1,2}T", read):
            raise AdapterBroken(f"{name}: column for {term}T reads {read!r}")
    if confirmed < MIN_CONFIRMED_HEADERS:
        raise AdapterBroken(f"{name}: only {confirmed} of {len(TERMS)} term headers confirmed")


def _record(
    spec: dict[str, Any],
    months: int,
    days: int,
    floor: int,
    rate: Decimal,
    effective: dt.date,
    conditions: str | None,
) -> SavingsRateRecord:
    return SavingsRateRecord(
        product_name=spec["product"],
        channel=spec["channel"],
        term_months=months,
        term_days=days,
        min_amount_vnd=floor,
        interest_payment=spec["payment"],
        rate_pct=rate,
        conditions_text=conditions,
        effective_from=effective,
    )
