"""ACB: personal savings rates. Notes in docs/adapters/acb.md."""

import re
from decimal import Decimal

from core.enums import Channel, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.html_tables import Table, extract_tables
from pipeline.extract.vietnamese import clean, fold, parse_rate, parse_term
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

END, QUARTERLY, MONTHLY, UPFRONT = (
    InterestPayment.END,
    InterestPayment.QUARTERLY,
    InterestPayment.MONTHLY,
    InterestPayment.UPFRONT,
)
TRADITIONAL = "Tiết kiệm Truyền Thống/Tiền gửi có kỳ hạn"
PHUC_AN_LOC = "Tiết kiệm Phúc An Lộc"
ONLINE = "Tiền gửi Online"
ONLINE_FLEX = "Tiền gửi Online kỳ hạn tùy chọn"

# Counter table: column index -> (product, payment). Col 0 = term, col 1 = USD, col 9 = Tích Lũy.
COUNTER_COLUMNS = {
    2: (TRADITIONAL, END),
    3: (TRADITIONAL, QUARTERLY),
    4: (TRADITIONAL, MONTHLY),
    5: (TRADITIONAL, UPFRONT),
    6: (PHUC_AN_LOC, END),
    7: (PHUC_AN_LOC, QUARTERLY),
    8: (PHUC_AN_LOC, MONTHLY),
}
COUNTER_HEADER = [
    ["ky han", "usd"] + ["vnd"] * 8,
    ["ky han", "usd"]
    + ["tk truyen thong/ tien gui co ky han"] * 4
    + ["tk phuc an loc"] * 3
    + ["tich luy tuong lai"],
]
PAYMENT_ROW = [
    "lai cuoi ky",
    "lai quy",
    "lai thang",
    "lai tra truoc",
    "lai cuoi ky",
    "lai quy",
    "lai thang",
]

# Online tables: amount tier label (triệu VND) -> min_amount_vnd
TIERS = {
    "< 200": 0,
    "200 – < 1.000": 200_000_000,
    "1.000 - < 5.000": 1_000_000_000,
    ">= 5.000": 5_000_000_000,
}
ONLINE_TABLES = {
    # header text -> (product, payment)
    "tien gui online (lck)": (ONLINE, END),
    "tien gui online lai tra truoc": (ONLINE, UPFRONT),
    "tien gui online ky han tuy chon (lck)": (ONLINE_FLEX, END),
}
MIN_WEEKLY_OR_UPFRONT = (
    10_000_000  # "Mức gửi tối thiểu ... kỳ hạn tuần/ lãnh lãi trước là 10 triệu VND"
)
BONUS_NOTE = (
    "Lãi suất thưởng bậc thang (kỳ hạn 1–12 tháng): 200 triệu–<1 tỷ +0,10; "
    "1 tỷ–<5 tỷ +0,15; ≥5 tỷ +0,20 (%/năm)"
)
FOOTNOTES = {  # marker -> (min amount, rate) from "Lưu ý: (*) ... (**) ..."
    "*": re.compile(
        r"\(\*\):\s*Đối với mức gửi từ 200 tỷ \(bậc 2\): Lãi suất ([\d,]+) ?%/ ?năm \(LCK\)"
    ),
    "**": re.compile(
        r"\(\s?\*\*\):\s*Đối với mức gửi từ 200 tỷ \(bậc 2\): Lãi suất ([\d,]+) ?%/ ?năm \(LT\)"
    ),
}


@register
class AcbSavings(BaseAdapter):
    name = "acb_savings"
    institution = "ACB"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP
    # Source URL: https://acb.com.vn/lai-suat-tien-gui

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        html = content.decode("utf-8", errors="replace")
        tables = extract_tables(html)
        counter = [t for t in tables if [fold(c) for c in t.rows[0]] == COUNTER_HEADER[0]]
        if len(counter) != 1:
            raise AdapterBroken(f"expected one counter rate table, found {len(counter)}")
        text = clean(re.sub(r"<[^>]+>", " ", html))
        records = _counter(counter[0], text)
        for header, (product, payment) in ONLINE_TABLES.items():
            found = [t for t in tables if t.rows and fold(t.rows[0][1]) == header]
            if len(found) != 1:
                raise AdapterBroken(f"expected one online table {header!r}, found {len(found)}")
            records += _online(found[0], product, payment)
        keys = [
            (r.product_name, r.term_months, r.term_days, r.min_amount_vnd, r.interest_payment)  # type: ignore[attr-defined]
            for r in records
        ]
        if len(set(keys)) != len(keys):
            raise AdapterBroken("two cells map to the same product, term, tier and payment")
        return records


def _counter(table: Table, page_text: str) -> list[Record]:
    if [fold(c) for c in table.rows[1]] != COUNTER_HEADER[1]:
        raise AdapterBroken(f"counter product header changed: {table.rows[1]!r}")
    if [fold(c) for c in table.rows[2][2:9]] != PAYMENT_ROW:
        raise AdapterBroken(f"counter payment header changed: {table.rows[2]!r}")
    footnotes = _footnotes(page_text)

    records: list[Record] = []
    data = [r for r in table.rows[2:] if fold(r[0]) != "ky han"]
    for row in data:
        if len(row) != 10:
            raise AdapterBroken(f"counter row has {len(row)} cells: {row!r}")
        months, days, band = _term(row[0])
        for col, (product, payment) in COUNTER_COLUMNS.items():
            cell = row[col]
            marker = re.search(r"\*+$", cell)
            rate = _rate(cell.rstrip("*"))
            if rate is None:
                continue
            records.append(
                _record(
                    product,
                    Channel.COUNTER,
                    months,
                    days,
                    payment,
                    rate,
                    _counter_conditions(product, months, days, band),
                )
            )
            if marker:
                stars = marker.group(0)
                if stars not in footnotes:
                    raise AdapterBroken(f"footnote {stars!r} on {row[0]} not found under the table")
                records.append(
                    _record(
                        product,
                        Channel.COUNTER,
                        months,
                        days,
                        payment,
                        footnotes[stars],
                        "Mức gửi từ 200 tỷ (bậc 2)",
                        min_amount=200_000_000_000,
                    )
                )
    have = {(r.product_name, r.term_months) for r in records}  # type: ignore[attr-defined]
    for months in (1, 3, 6, 12, 24, 36):
        if (TRADITIONAL, months) not in have:
            raise AdapterBroken(f"counter: no {months}-month rate for {TRADITIONAL}")
    return records


def _online(table: Table, product: str, payment: InterestPayment) -> list[Record]:
    if len(table.rows) != 6 or fold(table.rows[1][0]) != "(trieu vnd)":
        raise AdapterBroken(f"{product} ({payment.value}): table shape changed")
    terms = table.rows[1][1:]
    records: list[Record] = []
    for row in table.rows[2:]:
        if len(row) != len(terms) + 1:
            raise AdapterBroken(f"{product}: row has {len(row)} cells: {row!r}")
        tier_label = clean(row[0])
        if tier_label not in TIERS:
            raise AdapterBroken(f"{product}: unknown amount tier {tier_label!r}")
        for term_label, cell in zip(terms, row[1:], strict=True):
            if fold(term_label) == "renew":
                continue  # rollover rate, not a term
            months, days, band = _term(term_label)
            rate = _rate(cell)
            if rate is None:
                continue
            floor = TIERS[tier_label]
            if days or payment is UPFRONT:
                floor = max(floor, MIN_WEEKLY_OR_UPFRONT)
            records.append(
                _record(
                    product, Channel.ONLINE, months, days, payment, rate, band, min_amount=floor
                )
            )
    if not {1, 6, 12} <= {r.term_months for r in records}:  # type: ignore[attr-defined]
        raise AdapterBroken(f"{product} ({payment.value}): core terms missing")
    return records


def _term(label: str) -> tuple[int, int, str | None]:
    """'1T' -> (1, 0, None); '1 – 3 tuần' -> (0, 7, band note); '3T – < 6T' -> (3, 0, band note)."""
    s = clean(label).replace("–", "-")
    if fold(s) in {"1 - 3 tuan", "1 - 3 tuần"}:
        return 0, 7, "Áp dụng cho kỳ hạn 1–3 tuần"
    m = re.fullmatch(r"(\d+)T - ?< ?(\d+)T", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi <= lo:
            raise AdapterBroken(f"empty band {label!r}")
        return lo, 0, None if hi == lo + 1 else f"Áp dụng cho kỳ hạn từ {lo} đến dưới {hi} tháng"
    try:
        months, days = parse_term(s)
    except ValueError as exc:
        raise AdapterBroken(str(exc)) from exc
    return months, days, None


def _rate(cell: str) -> Decimal | None:
    try:
        return parse_rate(cell)
    except ValueError as exc:
        raise AdapterBroken(str(exc)) from exc


def _footnotes(text: str) -> dict[str, Decimal]:
    found = {}
    for stars, pattern in FOOTNOTES.items():
        m = pattern.search(text)
        if m:
            found[stars] = _rate(m.group(1)) or Decimal(0)
    return found


def _counter_conditions(product: str, months: int, days: int, band: str | None) -> str | None:
    parts = [band] if band else []
    if product in (TRADITIONAL, PHUC_AN_LOC) and 1 <= months <= 12:
        parts.append(BONUS_NOTE)
    return "; ".join(parts) or None


def _record(
    product: str,
    channel: Channel,
    months: int,
    days: int,
    payment: InterestPayment,
    rate: Decimal,
    conditions: str | None,
    min_amount: int | None = None,
) -> SavingsRateRecord:
    if min_amount is None:
        min_amount = MIN_WEEKLY_OR_UPFRONT if (days or payment is UPFRONT) else 0
    return SavingsRateRecord(
        product_name=product,
        channel=channel,
        term_months=months,
        term_days=days,
        min_amount_vnd=min_amount,
        interest_payment=payment,
        rate_pct=rate,
        conditions_text=conditions,
    )
