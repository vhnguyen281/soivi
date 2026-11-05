"""MB savings adapter, against the rendered /fee page saved on 2026-10-26."""

import datetime as dt
import unicodedata
from decimal import Decimal

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.mb import MbSavings
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PAGE = fixture_bytes("mb", "savings_2026-10-26.html")
TEXT = unicodedata.normalize("NFC", PAGE.decode())  # the page mixes accent encodings
END, UPFRONT, MONTHLY = InterestPayment.END, InterestPayment.UPFRONT, InterestPayment.MONTHLY
B = 1_000_000_000

Key = tuple[str, str, int, int, int, InterestPayment]


@pytest.fixture(scope="module")
def records() -> dict[Key, SavingsRateRecord]:
    parsed: list[SavingsRateRecord] = MbSavings.parse_content(PAGE)  # type: ignore[assignment]
    out: dict[Key, SavingsRateRecord] = {}
    for r in parsed:
        key = (
            r.region,
            r.product_name,
            r.term_months,
            r.term_days,
            r.min_amount_vnd,
            r.interest_payment,
        )
        assert key not in out
        out[key] = r
    return out


SAVINGS = "Tiết kiệm khách hàng cá nhân"
DIGITAL = "Tiền gửi số truyền thống"


@pytest.mark.parametrize(
    ("region", "product", "months", "days", "amount", "payment", "rate"),
    [
        ("north", SAVINGS, 0, 0, 0, END, "0.05"),  # KKH
        ("north", SAVINGS, 0, 7, 0, END, "0.50"),  # 01 tuần
        ("north", SAVINGS, 1, 0, 0, END, "3.70"),
        ("north", SAVINGS, 1, 0, B, END, "3.90"),
        ("north", SAVINGS, 6, 0, 0, UPFRONT, "4.01"),
        ("north", SAVINGS, 12, 0, 0, END, "5.70"),
        ("north", SAVINGS, 12, 0, 0, MONTHLY, "5.55"),
        ("north", SAVINGS, 60, 0, B, UPFRONT, "4.90"),
        ("central_south", SAVINGS, 1, 0, 0, END, "3.80"),
        ("central_south", SAVINGS, 11, 0, B, MONTHLY, "4.32"),
        ("central_south", SAVINGS, 12, 0, 0, END, "5.70"),
        ("", DIGITAL, 1, 0, 0, END, "4.50"),
        ("", DIGITAL, 12, 0, B, END, "5.85"),
        ("", DIGITAL, 0, 21, 0, END, "0.50"),
    ],
)
def test_exact_rates(
    records: dict[Key, SavingsRateRecord],
    region: str,
    product: str,
    months: int,
    days: int,
    amount: int,
    payment: InterestPayment,
    rate: str,
) -> None:
    assert records[(region, product, months, days, amount, payment)].rate_pct == Decimal(rate)


def test_regions_differ_where_the_bank_says(records: dict[Key, SavingsRateRecord]) -> None:
    def rate(region: str, months: int) -> Decimal:
        return records[(region, SAVINGS, months, 0, 0, END)].rate_pct

    assert rate("central_south", 1) - rate("north", 1) == Decimal("0.10")
    assert rate("central_south", 24) == rate("north", 24)


def test_fields(records: dict[Key, SavingsRateRecord]) -> None:
    for (_region, product, _, _, amount, _), r in records.items():
        assert r.effective_from == dt.date(2026, 10, 21)
        assert r.channel == (Channel.APP if product == DIGITAL else Channel.COUNTER)
        assert r.conditions_text == ("Số tiền trên 1 tỷ VND" if amount else None)
    # KKH and weekly terms only have the end-of-term column
    assert (("north", SAVINGS, 0, 0, 0, UPFRONT)) not in records


def test_counts(records: dict[Key, SavingsRateRecord]) -> None:
    by = {}
    for (region, product, *_), _ in records.items():
        by[(region, product)] = by.get((region, product), 0) + 1
    # savings: 4 rows x 2 (KKH + 3 weeks), 2 months x 4 (no monthly), 19 rows x 6
    assert by[("north", SAVINGS)] == by[("central_south", SAVINGS)] == 4 * 2 + 2 * 4 + 17 * 6
    # digital: 3 weeks x 2, 2 months x 4, 17 rows x 6 (no KKH row)
    assert by[("", DIGITAL)] == 3 * 2 + 2 * 4 + 17 * 6


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<html><body>Too many requests</body></html>", "found 0, 0, 0"),
        (
            TEXT.replace(
                "cá nhân (áp dụng: các chi nhánh thuộc miền Trung và miền Nam).", "cá nhân.", 1
            ),
            "found 2, 0, 1",
        ),
        (
            TEXT.replace("(áp dụng: Khách hàng Mass)", "(áp dụng: Khách hàng phổ thông)"),
            "found 1, 1, 0",
        ),
        (TEXT.replace("có hiệu lực từ ngày 21-10-2026", "cập nhật"), "no 'hiệu lực"),
        (
            # the first two are the North savings table's monthly columns
            TEXT.replace("<strong> hàng tháng (%/năm)", "<strong> hàng quý (%/năm)", 2),
            "header changed",
        ),
        (TEXT.replace("Số tiền dưới 1 tỷ VND", "Số tiền dưới 2 tỷ VND"), "header changed"),
        (TEXT.replace("5.70%", "5,70 % / tháng", 1), "not a rate"),
        (TEXT.replace("13 tháng", "12 tháng", 1), "appears twice"),
    ],
    ids=[
        "blocked",
        "region label gone",
        "digital caption",
        "date",
        "payment header",
        "amount header",
        "rate",
        "duplicate",
    ],
)
def test_layout_change_raises(content: str, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        MbSavings.parse_content(content.encode())
