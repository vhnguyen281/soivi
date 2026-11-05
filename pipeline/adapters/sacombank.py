"""Sacombank: personal savings rates from the listed-rate PDF.

Notes in docs/adapters/sacombank.md.
"""

import datetime as dt
import io
import re
from typing import Any

import pdfplumber

from core.enums import Channel, ExtractionMethod, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.vietnamese import clean, fold, parse_rate, parse_term
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

END, QUARTERLY, MONTHLY, UPFRONT = (
    InterestPayment.END,
    InterestPayment.QUARTERLY,
    InterestPayment.MONTHLY,
    InterestPayment.UPFRONT,
)
EFFECTIVE = re.compile(r"Hiệu lực từ (?:\d{1,2}h\d{2} )?ngày (\d{1,2})\.(\d{1,2})\.(\d{4})")
BAND = re.compile(r"^tu (\d{1,2}) den duoi (\d{1,2}) thang$")

# (tier header labels, tier floors, payment columns, product, channel)
TABLES: list[dict[str, Any]] = [
    {
        "tiers": ["duoi 500 trieu dong", "tu 500 trieu dong den duoi 2 ty dong", "tu 2 ty dong"],
        "floors": [0, 500_000_000, 2_000_000_000],
        "payments": [END, QUARTERLY, MONTHLY, UPFRONT],
        "labels": ["lai cuoi ky", "lai hang quy", "lai hang thang", "lai tra truoc"],
        "product": "Tiết kiệm có kỳ hạn truyền thống",
        "channel": Channel.COUNTER,
    },
    {
        "tiers": [
            "duoi 50 trieu dong",
            "tu 50 trieu dong den duoi 500 trieu dong",
            "tu 500 trieu dong",
        ],
        "floors": [0, 50_000_000, 500_000_000],
        "payments": [END, QUARTERLY, MONTHLY],
        "labels": ["lai cuoi ky", "lai hang quy", "lai hang thang"],
        "product": "Tiền gửi có kỳ hạn trực tuyến",
        "channel": Channel.ONLINE,
    },
]
CORE_TERMS = {1, 3, 6, 12, 24, 36}


@register
class SacombankSavings(BaseAdapter):
    name = "sacombank_savings"
    institution = "SACOMBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.PDF
    extraction_method = ExtractionMethod.PDF_TABLE
    # Source URL (stable file name):
    # https://www.sacombank.com.vn/content/dam/sacombank/files/cong-cu/lai-suat/tien-gui/khcn/SACOMBANK_LAISUATNIEMYETTAIQUAY_KHCN_VIE.pdf

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        if not content.startswith(b"%PDF-"):
            raise AdapterBroken("not a PDF")
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                first_text = pdf.pages[0].extract_text() or ""
                grids = [
                    [[clean(c) if c else "" for c in row] for row in table]
                    for page in pdf.pages
                    for table in page.extract_tables(
                        {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
                    )
                ]
        except Exception as exc:
            raise AdapterBroken(f"PDF unreadable: {type(exc).__name__}") from exc

        if "LÃI SUẤT HUY ĐỘNG - KHÁCH HÀNG CÁ NHÂN" not in first_text:
            raise AdapterBroken("title 'LÃI SUẤT HUY ĐỘNG - KHÁCH HÀNG CÁ NHÂN' missing")
        if "ÁP DỤNG CHO TẤT CẢ ĐỊA BÀN" not in first_text:
            raise AdapterBroken("'ÁP DỤNG CHO TẤT CẢ ĐỊA BÀN' missing: rates may now be regional")
        m = EFFECTIVE.search(first_text)
        if not m:
            raise AdapterBroken("no 'Hiệu lực từ … ngày dd.mm.yyyy' line")
        effective = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

        records: list[Record] = []
        for spec in TABLES:
            matches = [g for g in grids if g and _tier_labels(g[0]) == spec["tiers"]]
            if len(matches) != 1:
                raise AdapterBroken(f"{spec['product']}: found {len(matches)} matching tables")
            records += _parse_grid(matches[0], spec, effective)
        return records


def _tier_labels(row: list[str]) -> list[str]:
    if not row or fold(row[0]) != "muc tien":
        return []
    return [fold(c) for c in row[1:] if c]


def _parse_grid(grid: list[list[str]], spec: dict[str, Any], effective: dt.date) -> list[Record]:
    width = 1 + len(spec["floors"]) * len(spec["payments"])
    header = grid[1] if len(grid) > 1 else []
    if fold(header[0] if header else "") != "ky han gui" or [fold(c) for c in header[1:]] != spec[
        "labels"
    ] * len(spec["floors"]):
        raise AdapterBroken(f"{spec['product']}: payment header changed: {header!r}")

    records: list[Record] = []
    terms: set[int] = set()
    columns = [(floor, pay) for floor in spec["floors"] for pay in spec["payments"]]
    for row in grid[2:]:
        if len(row) != width:
            raise AdapterBroken(f"{spec['product']}: row has {len(row)} cells: {row!r}")
        months, days, band = _term(row[0])
        if months in terms and not days:
            raise AdapterBroken(f"{spec['product']}: term {row[0]!r} appears twice")
        terms.add(months)
        for (floor, payment), cell in zip(columns, row[1:], strict=True):
            try:
                rate = parse_rate(cell)
            except ValueError as exc:
                raise AdapterBroken(str(exc)) from exc
            if rate is None:
                continue
            records.append(
                SavingsRateRecord(
                    product_name=spec["product"],
                    channel=spec["channel"],
                    term_months=months,
                    term_days=days,
                    min_amount_vnd=floor,
                    interest_payment=payment,
                    rate_pct=rate,
                    conditions_text=band,
                    effective_from=effective,
                )
            )
    missing = CORE_TERMS - terms
    if missing:
        raise AdapterBroken(f"{spec['product']}: terms missing {sorted(missing)}")
    return records


def _term(label: str) -> tuple[int, int, str | None]:
    s = fold(label)
    if s == "duoi 1 thang":
        # Notes: day terms are allowed from 7 days.
        return 0, 7, "Áp dụng cho kỳ hạn dưới 1 tháng"
    m = BAND.match(s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi != lo + 1:
            raise AdapterBroken(f"band wider than one month: {label!r}")
        return lo, 0, None
    try:
        months, days = parse_term(label)
    except ValueError as exc:
        raise AdapterBroken(str(exc)) from exc
    return months, days, None
