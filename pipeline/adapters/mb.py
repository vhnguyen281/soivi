"""MB (Military Bank): personal savings rates from the rendered /fee page.

Notes in docs/adapters/mb.md.
"""

from core.enums import Channel, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.html_tables import Table, extract_tables
from pipeline.extract.vietnamese import find_effective_date, fold, parse_rate, parse_term
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

SAVINGS_CAPTION_END = "1. lai suat tiet kiem khach hang ca nhan bang dong viet nam tai mb:"
CENTRAL_SOUTH = "ap dung: cac chi nhanh thuoc mien trung va mien nam"
DIGITAL_CAPTION = "lai suat san pham tien gui so truyen thong (ap dung: khach hang mass)"

AMOUNT_HEADER = ["ky han"] + ["so tien duoi 1 ty vnd"] * 3 + ["so tien tu tren 1 ty vnd"] * 3
PAYMENT_HEADER = ["ky han"] + [
    "lai tra sau (%/nam)",
    "lai tra truoc (%/nam)",
    "lai tra hang thang (%/nam)",
] * 2
# Column order after the term: (payment, min amount, conditions)
COLUMNS = [
    (pay, amount, cond)
    for amount, cond in ((0, None), (1_000_000_000, "Số tiền trên 1 tỷ VND"))
    for pay in (InterestPayment.END, InterestPayment.UPFRONT, InterestPayment.MONTHLY)
]
CORE_TERMS = {(1, 0), (3, 0), (6, 0), (12, 0), (24, 0)}


@register
class MbSavings(BaseAdapter):
    name = "mb_savings"
    institution = "MB"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    # The rate API needs an anti-forgery token the page obtains first; we render
    # the public page instead of working around that (see docs).
    fetch_method = FetchMethod.BROWSER
    # The deposit section is loaded by a second API call; without it the page has
    # only loan rates. Don't capture until it is there.
    browser_wait_for = "Lãi suất huy động MB"
    # Source URL: https://www.mbbank.com.vn/fee

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        tables = extract_tables(content.decode("utf-8", errors="replace"))
        savings = [t for t in tables if fold(t.caption).endswith(SAVINGS_CAPTION_END)]
        north = [t for t in savings if CENTRAL_SOUTH not in fold(t.caption)]
        central_south = [t for t in savings if CENTRAL_SOUTH in fold(t.caption)]
        digital = [t for t in tables if DIGITAL_CAPTION in fold(t.caption)]
        if (len(north), len(central_south), len(digital)) != (1, 1, 1):
            raise AdapterBroken(
                "expected one table each for savings (North), savings (Central/South) and "
                f"digital deposits; found {len(north)}, {len(central_south)}, {len(digital)}"
            )
        effective = find_effective_date(north[0].caption)
        if effective is None:
            raise AdapterBroken("no 'hiệu lực từ ngày …' date before the savings table")

        records: list[Record] = []
        for table, region, product, channel, skip in (
            (north[0], "north", "Tiết kiệm khách hàng cá nhân", Channel.COUNTER, 0),
            (central_south[0], "central_south", "Tiết kiệm khách hàng cá nhân", Channel.COUNTER, 0),
            (digital[0], "", "Tiền gửi số truyền thống", Channel.APP, 1),
        ):
            records.extend(_table(table, skip, region, product, channel, effective))
        return records


def _table(
    table: Table, skip: int, region: str, product: str, channel: Channel, effective: object
) -> list[Record]:
    """`skip`: extra header rows above the amount/payment headers (digital table has one)."""
    rows = table.rows[skip:]
    if len(rows) < 3:
        raise AdapterBroken(f"{product} ({region or 'all'}): table too short")
    if [fold(c) for c in rows[0]] != AMOUNT_HEADER or [fold(c) for c in rows[1]] != PAYMENT_HEADER:
        raise AdapterBroken(f"{product} ({region or 'all'}): header changed: {rows[:2]!r}")

    records: list[Record] = []
    terms: set[tuple[int, int]] = set()
    for row in rows[2:]:
        if len(row) != 7:
            raise AdapterBroken(f"{product}: row has {len(row)} cells: {row!r}")
        try:
            term_months, term_days = parse_term(row[0])
            rates = [parse_rate(cell) for cell in row[1:]]
        except ValueError as exc:
            raise AdapterBroken(str(exc)) from exc
        if (term_months, term_days) in terms:
            raise AdapterBroken(f"{product}: term {row[0]!r} appears twice")
        terms.add((term_months, term_days))
        for (payment, amount, cond), rate in zip(COLUMNS, rates, strict=True):
            if rate is None:
                continue  # e.g. no up-front option for KKH or weekly terms
            records.append(
                SavingsRateRecord(
                    region=region,
                    product_name=product,
                    channel=channel,
                    term_months=term_months,
                    term_days=term_days,
                    min_amount_vnd=amount,
                    interest_payment=payment,
                    rate_pct=rate,
                    conditions_text=cond,
                    effective_from=effective,
                )
            )
    missing = CORE_TERMS - terms
    if missing:
        raise AdapterBroken(f"{product} ({region or 'all'}): terms missing {sorted(missing)}")
    return records
