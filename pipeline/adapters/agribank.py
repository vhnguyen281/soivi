"""Agribank: personal savings rates (counter + online). Notes in docs/adapters/agribank.md."""

from core.enums import Channel, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.html_tables import Table, extract_tables
from pipeline.extract.vietnamese import fold, parse_rate, parse_term, parse_term_band
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

COUNTER_HEADER = ["ki han", "vnd", "usd", "eur", "jpy", "ngoai te khac"]
ONLINE_HEADING = "lai suat tien gui truc tuyen (vnd)"
ONLINE_HEADER = ["stt", "ky han", "muc lai suat toi da (%/nam)"]

SAVINGS = "Tiền gửi tiết kiệm"
PAYMENT_ACCOUNT = "Tiền gửi thanh toán"
ONLINE = "Tiền gửi trực tuyến"


@register
class AgribankSavings(BaseAdapter):
    name = "agribank_savings"
    institution = "AGRIBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP
    # Source URL: the personal-rate fragment that /vn/lai-suat-tien-gui loads:
    # https://www.agribank.com.vn/wcm/connect/ttkhac/lai-suat/lai-suat-cn?source=library&srv=cmpnt&cmpntid=c1687c7c-142f-4616-a8b0-02f09a14f844

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        tables = extract_tables(content.decode("utf-8", errors="replace"))
        counter = [t for t in tables if [fold(c) for c in t.header] == COUNTER_HEADER]
        online = [t for t in tables if ONLINE_HEADING in fold(t.caption)]
        if len(counter) != 1 or len(online) != 1:
            raise AdapterBroken(
                f"expected 1 counter and 1 online table, found {len(counter)} and {len(online)}"
            )
        records = _counter(counter[0]) + _online(online[0])
        keys = [(r.product_name, r.term_months, r.term_days) for r in records]  # type: ignore[attr-defined]
        if len(set(keys)) != len(keys):
            raise AdapterBroken("two rows map to the same product and term")
        return records


def _counter(table: Table) -> list[Record]:
    records: list[Record] = []
    for row in table.rows[1:]:
        if len(row) != len(COUNTER_HEADER):
            raise AdapterBroken(f"counter row has {len(row)} cells: {row!r}")
        label, vnd = row[0], row[1]
        product = PAYMENT_ACCOUNT if fold(label) == "tien gui thanh toan" else SAVINGS
        try:
            term_months, term_days = parse_term(label)
            rate = parse_rate(vnd)
        except ValueError as exc:
            raise AdapterBroken(str(exc)) from exc
        if rate is None:
            continue
        records.append(
            SavingsRateRecord(
                product_name=product,
                channel=Channel.COUNTER,
                term_months=term_months,
                term_days=term_days,
                interest_payment=InterestPayment.END,
                rate_pct=rate,
            )
        )
    terms = {r.term_months for r in records if r.product_name == SAVINGS}  # type: ignore[attr-defined]
    missing = [t for t in (0, 1, 3, 6, 12, 24) if t not in terms]
    if missing:
        raise AdapterBroken(f"counter: no VND rate for {missing} months")
    return records


def _online(table: Table) -> list[Record]:
    if [fold(c) for c in table.header] != ONLINE_HEADER:
        raise AdapterBroken(f"unexpected online header {table.header!r}")
    records: list[Record] = []
    for row in table.rows[1:]:
        if len(row) != len(ONLINE_HEADER):
            raise AdapterBroken(f"online row has {len(row)} cells: {row!r}")
        _, label, value = row
        try:
            lo, _hi = parse_term_band(label)
            rate = parse_rate(value)
        except ValueError as exc:
            raise AdapterBroken(str(exc)) from exc
        if lo is None or rate is None:
            raise AdapterBroken(f"online band without a start term: {label!r}")
        records.append(
            SavingsRateRecord(
                product_name=ONLINE,
                channel=Channel.ONLINE,
                term_months=lo,
                interest_payment=InterestPayment.END,
                rate_pct=rate,
                # The bank publishes a ceiling ("mức lãi suất tối đa"), not a fixed rate.
                conditions_text=f"Mức lãi suất tối đa; áp dụng cho kỳ hạn: {label}",
            )
        )
    if {r.term_months for r in records} != {1, 3, 6, 12, 24}:  # type: ignore[attr-defined]
        raise AdapterBroken(f"online bands changed: {[r[1] for r in table.rows[1:]]}")
    return records
