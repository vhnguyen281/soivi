"""Sacombank savings adapter, against the PDF saved on 2026-10-26."""

import copy
import datetime as dt
from decimal import Decimal

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.sacombank import TABLES, SacombankSavings, _parse_grid
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PDF = fixture_bytes("sacombank", "savings_2026-10-26.pdf")
END, QUARTERLY, MONTHLY, UPFRONT = (
    InterestPayment.END,
    InterestPayment.QUARTERLY,
    InterestPayment.MONTHLY,
    InterestPayment.UPFRONT,
)
COUNTER = "Tiết kiệm có kỳ hạn truyền thống"
ONLINE = "Tiền gửi có kỳ hạn trực tuyến"
M = 1_000_000

Key = tuple[str, int, int, int, InterestPayment]


@pytest.fixture(scope="module")
def records() -> dict[Key, SavingsRateRecord]:
    parsed: list[SavingsRateRecord] = SacombankSavings.parse_content(PDF)  # type: ignore[assignment]
    return {
        (r.product_name, r.term_months, r.term_days, r.min_amount_vnd, r.interest_payment): r
        for r in parsed
    }


@pytest.mark.parametrize(
    ("product", "months", "days", "amount", "payment", "rate"),
    [
        (COUNTER, 0, 7, 0, END, "0.50"),  # Dưới 1 tháng
        (COUNTER, 1, 0, 0, END, "4.50"),  # Từ 1 đến dưới 2 tháng
        (COUNTER, 1, 0, 0, UPFRONT, "4.48"),
        (COUNTER, 6, 0, 0, QUARTERLY, "5.66"),
        (COUNTER, 6, 0, 500 * M, END, "5.80"),
        (COUNTER, 12, 0, 0, END, "5.40"),
        (COUNTER, 12, 0, 2_000 * M, MONTHLY, "5.46"),
        (COUNTER, 36, 0, 2_000 * M, UPFRONT, "5.37"),
        (ONLINE, 1, 0, 0, END, "4.50"),
        (ONLINE, 6, 0, 50 * M, QUARTERLY, "6.55"),
        (ONLINE, 12, 0, 0, END, "6.50"),
        (ONLINE, 12, 0, 500 * M, END, "7.00"),
        (ONLINE, 24, 0, 500 * M, END, "7.30"),
        (ONLINE, 36, 0, 0, MONTHLY, "6.12"),
    ],
)
def test_exact_rates(
    records: dict[Key, SavingsRateRecord],
    product: str,
    months: int,
    days: int,
    amount: int,
    payment: InterestPayment,
    rate: str,
) -> None:
    assert records[(product, months, days, amount, payment)].rate_pct == Decimal(rate)


def test_fields(records: dict[Key, SavingsRateRecord]) -> None:
    assert len(records) == 303
    for (product, *_), r in records.items():
        assert r.effective_from == dt.date(2026, 10, 20)
        assert r.region == ""  # "ÁP DỤNG CHO TẤT CẢ ĐỊA BÀN"
        assert r.channel == (Channel.ONLINE if product == ONLINE else Channel.COUNTER)
    # no quarterly option where the cell is empty (terms not divisible by 3)
    assert (COUNTER, 4, 0, 0, QUARTERLY) not in records
    assert (ONLINE, 1, 0, 0, UPFRONT) not in records  # online has no up-front column
    assert records[(COUNTER, 0, 7, 0, END)].conditions_text == "Áp dụng cho kỳ hạn dưới 1 tháng"


# --------------------------------------------------------------------------- layout changes

GRID = [
    [
        "Mức tiền",
        "Dưới 50 triệu đồng",
        "",
        "",
        "Từ 50 triệu đồng đến dưới 500 triệu đồng",
        "",
        "",
        "Từ 500 triệu đồng",
        "",
        "",
    ],
    ["Kỳ hạn gửi"] + ["Lãi cuối kỳ", "Lãi hàng quý", "Lãi hàng tháng"] * 3,
    ["1 tháng", "4.50%", "", "4.50%", "4.60%", "", "4.60%", "4.75%", "", "4.75%"],
    ["3 tháng", "4.50%", "", "4.48%", "4.60%", "", "4.58%", "4.75%", "", "4.73%"],
    ["6 tháng", "6.30%", "6.25%", "6.22%", "6.60%", "6.55%", "6.51%", "6.70%", "6.64%", "6.61%"],
    ["12 tháng", "6.50%", "", "6.31%", "6.80%", "", "6.60%", "7.00%", "", "6.78%"],
    ["24 tháng", "6.70%", "", "6.30%", "7.00%", "", "6.57%", "7.30%", "", "6.83%"],
    ["36 tháng", "6.70%", "", "6.12%", "7.00%", "", "6.37%", "7.30%", "", "6.62%"],
]
ONLINE_SPEC = TABLES[1]


def grid_with(change):  # type: ignore[no-untyped-def]
    g = copy.deepcopy(GRID)
    change(g)
    return g


def test_grid_parses() -> None:
    records = _parse_grid(GRID, ONLINE_SPEC, dt.date(2026, 10, 20))
    assert len(records) == 6 * 2 * 3 + 3  # 2 payments per tier, plus quarterly for 6 months


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda g: g[1].__setitem__(2, "Lãi hàng năm"), "payment header changed"),
        (lambda g: g[3].pop(), "row has 9 cells"),
        (lambda g: g[3].__setitem__(1, "4,50 %/tháng"), "not a rate"),
        (lambda g: g[3].__setitem__(0, "Kỳ hạn linh hoạt"), "not a term"),
        (lambda g: g[4].__setitem__(0, "3 tháng"), "appears twice"),
        (lambda g: g.pop(5), r"terms missing \[12\]"),
    ],
    ids=["header", "cells", "rate", "term", "duplicate", "core term"],
)
def test_grid_changes_raise(change, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AdapterBroken, match=message):
        _parse_grid(grid_with(change), ONLINE_SPEC, dt.date(2026, 10, 20))


def test_wide_band_raises() -> None:
    g = grid_with(lambda g: g[2].__setitem__(0, "Từ 1 đến dưới 3 tháng"))
    with pytest.raises(AdapterBroken, match="wider than one month"):
        _parse_grid(g, ONLINE_SPEC, dt.date(2026, 10, 20))


def test_other_documents_raise() -> None:
    with pytest.raises(AdapterBroken, match="not a PDF"):
        SacombankSavings.parse_content(b"<html>404</html>")
    other_bank = fixture_bytes("techcombank", "savings_2026-10-26.pdf")
    with pytest.raises(AdapterBroken, match="title"):
        SacombankSavings.parse_content(other_bank)
