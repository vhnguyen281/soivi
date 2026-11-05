"""HDBank: personal savings rates from the published PDF. Notes in docs/adapters/hdbank.md."""

import datetime as dt
import html
import io
import re
from typing import Any

import pdfplumber

from core.enums import Channel, ExtractionMethod, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.vietnamese import clean, fold, parse_rate, parse_term
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

END, UPFRONT, MONTHLY, QUARTERLY = (
    InterestPayment.END,
    InterestPayment.UPFRONT,
    InterestPayment.MONTHLY,
    InterestPayment.QUARTERLY,
)
SKIP = None  # a column we read (to keep positions) but don't store

# Section heading (start) -> spec. Columns are positional; "-" marks "not offered".
SECTIONS: list[dict[str, Any]] = [
    {
        "start": "a. Tiết kiệm có kỳ hạn thông thường:",
        "end": "b. Tiết kiệm không kỳ hạn:",
        # VNĐ: cuối kỳ, trả lãi trước, hàng tháng, hàng quý, hàng 06 tháng, hàng năm;
        # then USD, EUR, AUD, GBP
        "columns": [END, UPFRONT, MONTHLY, QUARTERLY, SKIP, SKIP, SKIP, SKIP, SKIP, SKIP],
        "product": "Tiết kiệm có kỳ hạn thông thường",
        "channel": Channel.COUNTER,
        "is_cd": False,
    },
    {
        "start": "c. Tiết kiệm Online VNĐ:",
        "end": "d. Lãi suất Tiền gửi tiết kiệm Online Vikki",
        "columns": [END, UPFRONT, MONTHLY, QUARTERLY],
        "product": "Tiết kiệm Online",
        "channel": Channel.ONLINE,
        "is_cd": False,
    },
    {
        "start": "3. TIỀN GỬI CÓ KỲ HẠN",
        "end": "4. LÃI SUẤT CHỨNG CHỈ TIỀN GỬI:",
        # cuối kỳ, hàng tháng, hàng quý, hàng 06 tháng
        "columns": [END, MONTHLY, QUARTERLY, SKIP],
        "product": "Tiền gửi có kỳ hạn",
        "channel": Channel.COUNTER,
        "is_cd": False,
    },
    {
        "start": "4. LÃI SUẤT CHỨNG CHỈ TIỀN GỬI:",
        "end": "5. LÃI SUẤT TIỀN GỬI THANH TOÁN:",
        "columns": [END],
        "product": "Chứng chỉ tiền gửi",
        "channel": Channel.COUNTER,
        "is_cd": True,
    },
]
VALUE = r"(?:\d+,\d{2}|-)"
ROW = re.compile(rf"^(TK KKH|\d{{1,2}} (?:ngày|tuần|tháng))(?: loại ([12]))?((?: {VALUE})+)$")
TYPE2 = re.compile(rf"^loại 2((?: {VALUE})+)$")
FOOTNOTE = re.compile(
    r"\(\*{1,2}\) LS(\d{2}) loại 1: lãi suất \d{2} tháng lãi cuối kỳ loại 1 mức ([\d,]+)% .*?"
    r"tối thiểu từ (\d+) tỷ đồng trở lên"
)
LISTING_TEXT = "BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN"
LISTING_LABEL = re.compile(r"^BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN (\d{2})-(\d{2})-(\d{4})$")


@register
class HdbankSavings(BaseAdapter):
    name = "hdbank_savings"
    institution = "HDBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.PDF
    extraction_method = ExtractionMethod.PDF_TABLE
    # Source URL: https://hdbank.com.vn/vi/personal/cong-cu/interest-rate (rendered in a
    # browser; its data API is encrypted). resolve_url() picks the newest deposit PDF.

    def resolve_url(self) -> str:
        page = self.ctx.fetchers.for_method(FetchMethod.BROWSER).fetch(
            super().resolve_url(), wait_for=LISTING_TEXT
        )
        return latest_pdf_url(page.content.decode("utf-8", errors="replace"))

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        if not content.startswith(b"%PDF-"):
            raise AdapterBroken("not a PDF")
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as exc:
            raise AdapterBroken(f"PDF unreadable: {type(exc).__name__}") from exc
        lines = [clean(line) for line in text.splitlines() if clean(line)]
        if "BIỂU LÃI SUẤT HUY ĐỘNG VỐN DÀNH CHO KHÁCH HÀNG CÁ NHÂN" not in lines:
            raise AdapterBroken("title missing")
        if "Biểu lãi suất áp dụng trên toàn hệ thống (%/năm)" not in lines:
            raise AdapterBroken("'áp dụng trên toàn hệ thống' missing: rates may now be regional")
        tiers = _type1_tiers(clean(text.replace("\n", " ")))

        records: list[Record] = []
        for spec in SECTIONS:
            records += _section(lines, spec, tiers)
        return records


def latest_pdf_url(page_html: str) -> str:
    """The newest 'BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN dd-mm-yyyy' link on the page."""
    found: list[tuple[dt.date, str]] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page_html, re.S):
        label = clean(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))))
        lm = LISTING_LABEL.match(label)
        if lm:
            day, month, year = (int(x) for x in lm.groups())
            found.append((dt.date(year, month, day), html.unescape(m.group(1))))
    if not found:
        raise AdapterBroken("no 'BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN dd-mm-yyyy' link")
    found.sort()
    date, url = found[-1]
    if len(found) > 1 and found[-2][0] == date:
        raise AdapterBroken(f"two deposit-rate PDFs dated {date}")
    if not re.match(r"^https://cdn\.hdbank\.com\.vn/.+\.pdf$", url, re.I):
        raise AdapterBroken(f"link is not an HDBank CDN PDF: {url!r}")
    return url


def _type1_tiers(text: str) -> dict[int, tuple[int, str]]:
    """LS12/LS13 'loại 1' footnotes: term -> (min amount, conditions)."""
    tiers = {}
    for m in FOOTNOTE.finditer(text):
        term, min_ty = int(m.group(1)), int(m.group(3))
        tiers[term] = (
            min_ty * 1_000_000_000,
            f"Lãi suất loại 1: áp dụng cho khoản tiết kiệm từ {min_ty} tỷ đồng trở lên; "
            "chỉ lãi cuối kỳ",
        )
    if set(tiers) != {12, 13}:
        raise AdapterBroken(f"LS12/LS13 'loại 1' footnotes changed: found {sorted(tiers)}")
    return tiers


def _section(
    lines: list[str], spec: dict[str, Any], tiers: dict[int, tuple[int, str]]
) -> list[Record]:
    try:
        start, end = lines.index(spec["start"]), lines.index(spec["end"])
    except ValueError as exc:
        raise AdapterBroken(f"section heading missing: {exc}") from exc
    if end <= start:
        raise AdapterBroken(f"{spec['product']}: section order changed")

    records: list[Record] = []
    seen: set[tuple[int, int, int]] = set()
    current_term: str | None = None
    for line in lines[start + 1 : end]:
        if m := ROW.match(line):
            label, kind, values = m.group(1), m.group(2), m.group(3).split()
            current_term = label
        elif (m := TYPE2.match(line)) and current_term:
            label, kind, values = current_term, "2", m.group(1).split()
        else:
            continue  # header lines, footnote markers
        months, days = _term(label)
        floor, conditions = 0, None
        if kind == "1":
            if months not in tiers:
                raise AdapterBroken(f"'loại 1' rate for {label} has no footnote")
            floor, conditions = tiers[months]
        if len(values) != len(spec["columns"]):
            raise AdapterBroken(
                f"{spec['product']} {line!r}: {len(values)} values, expected {len(spec['columns'])}"
            )
        if (months, days, floor) in seen:
            raise AdapterBroken(f"{spec['product']}: {label} appears twice")
        seen.add((months, days, floor))
        for payment, value in zip(spec["columns"], values, strict=True):
            if payment is None:
                continue
            rate = parse_rate(value)
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
                    conditions_text=conditions,
                    is_cd=spec["is_cd"],
                )
            )
    terms = {m for m, d, _ in seen if not d}
    missing = {1, 3, 6, 12, 24, 36} - terms
    if missing:
        raise AdapterBroken(f"{spec['product']}: terms missing {sorted(missing)}")
    return records


def _term(label: str) -> tuple[int, int]:
    if fold(label) == "tk kkh":
        return 0, 0
    try:
        return parse_term(label)
    except ValueError as exc:
        raise AdapterBroken(str(exc)) from exc
