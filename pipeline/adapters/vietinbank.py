"""VietinBank: personal savings rates. Notes in docs/adapters/vietinbank.md."""

from core.enums import Channel, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.html_tables import Table, extract_tables
from pipeline.extract.vietnamese import fold, parse_rate, parse_term_band
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

HEADING = "lai suat huy dong doi voi cac ky han"
EXPECTED_HEADER = ["ky han", "vnd (%/nam)", "usd (%/nam)", "eur (%/nam)"]
PRODUCT = "Tiền gửi thông thường"  # the page's calculator: "tiền gửi thông thường trả lãi sau"
CORE_TERMS = (0, 1, 3, 6, 12, 24)


@register
class VietinbankSavings(BaseAdapter):
    name = "vietinbank_savings"
    institution = "VIETINBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP
    # Source URL: https://www.vietinbank.vn/ca-nhan/cong-cu-tien-ich/lai-suat-khcn

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        table = _rate_table(content.decode("utf-8", errors="replace"))
        bands = _dedupe(table.rows[1:])

        records: list[Record] = []
        for label, vnd in bands.items():
            try:
                lo, hi = parse_term_band(label)
                rate = parse_rate(vnd)
            except ValueError as exc:
                raise AdapterBroken(str(exc)) from exc
            if lo is None or hi is None:
                continue  # "Dưới 1 tháng", "Trên 36 tháng": no single term (see docs)
            if rate is None:
                continue
            records.append(
                SavingsRateRecord(
                    product_name=PRODUCT,
                    channel=Channel.COUNTER,
                    term_months=lo,
                    min_amount_vnd=0,
                    interest_payment=InterestPayment.END,
                    rate_pct=rate,
                    # Keep the bank's band when it covers more than one whole month.
                    conditions_text=None if lo == hi else f"Áp dụng cho kỳ hạn: {label}",
                )
            )

        terms = {r.term_months for r in records}  # type: ignore[attr-defined]
        missing = [t for t in CORE_TERMS if t not in terms]
        if missing:
            raise AdapterBroken(f"no VND rate for {missing} months")
        if len(terms) != len(records):
            raise AdapterBroken("two bands map to the same term")
        return records


def _rate_table(html: str) -> Table:
    candidates = [t for t in extract_tables(html) if HEADING in fold(t.caption)]
    if len(candidates) != 1:
        raise AdapterBroken(f"expected one rate table after the heading, found {len(candidates)}")
    table = candidates[0]
    if [fold(c) for c in table.header] != EXPECTED_HEADER:
        raise AdapterBroken(f"unexpected header {table.header!r}")
    if any(len(row) != len(EXPECTED_HEADER) for row in table.rows):
        raise AdapterBroken("a row does not have 4 cells")
    return table


def _dedupe(rows: list[list[str]]) -> dict[str, str]:
    """The page renders each row twice. Keep one; copies must agree."""
    bands: dict[str, str] = {}
    for label, vnd, *_ in rows:
        if label in bands and bands[label] != vnd:
            raise AdapterBroken(f"{label!r} appears twice with different rates")
        bands[label] = vnd
    return bands
