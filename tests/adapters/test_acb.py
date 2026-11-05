"""ACB savings adapter, against the page saved on 2026-10-26."""

import unicodedata
from decimal import Decimal

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.acb import BONUS_NOTE, AcbSavings
from pipeline.adapters.base import AdapterBroken
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PAGE = fixture_bytes("acb", "savings_2026-10-26.html")
TEXT = unicodedata.normalize("NFC", PAGE.decode())
END, QUARTERLY, MONTHLY, UPFRONT = (
    InterestPayment.END,
    InterestPayment.QUARTERLY,
    InterestPayment.MONTHLY,
    InterestPayment.UPFRONT,
)
TRAD = "Tiết kiệm Truyền Thống/Tiền gửi có kỳ hạn"
PAL = "Tiết kiệm Phúc An Lộc"
ONLINE = "Tiền gửi Online"
FLEX = "Tiền gửi Online kỳ hạn tùy chọn"
M = 1_000_000

Key = tuple[str, int, int, int, InterestPayment]


@pytest.fixture(scope="module")
def records() -> dict[Key, SavingsRateRecord]:
    parsed: list[SavingsRateRecord] = AcbSavings.parse_content(PAGE)  # type: ignore[assignment]
    return {
        (r.product_name, r.term_months, r.term_days, r.min_amount_vnd, r.interest_payment): r
        for r in parsed
    }


@pytest.mark.parametrize(
    ("product", "months", "days", "amount", "payment", "rate"),
    [
        (TRAD, 0, 7, 10 * M, END, "0.50"),  # 1 - 3 tuần, min 10 triệu
        (TRAD, 1, 0, 0, END, "4.00"),
        (TRAD, 2, 0, 0, END, "4.00"),  # rowspan from the 1T row
        (TRAD, 5, 0, 0, END, "4.00"),
        (TRAD, 6, 0, 0, MONTHLY, "3.95"),
        (TRAD, 6, 0, 10 * M, UPFRONT, "3.90"),
        (TRAD, 12, 0, 0, END, "4.80"),
        (TRAD, 12, 0, 0, QUARTERLY, "4.70"),
        (TRAD, 13, 0, 0, END, "4.90"),  # "4,90*"
        (TRAD, 13, 0, 200_000 * M, END, "6.50"),  # footnote (*)
        (TRAD, 13, 0, 200_000 * M, MONTHLY, "6.25"),  # footnote (**)
        (TRAD, 36, 0, 0, MONTHLY, "4.50"),
        (PAL, 12, 0, 0, END, "5.00"),
        (PAL, 18, 0, 0, END, "5.10"),
        (ONLINE, 1, 0, 0, END, "4.40"),
        (ONLINE, 12, 0, 5_000 * M, END, "5.40"),
        (ONLINE, 0, 7, 10 * M, END, "0.50"),
        (ONLINE, 12, 0, 10 * M, UPFRONT, "4.90"),
        (ONLINE, 12, 0, 1_000 * M, UPFRONT, "5.05"),
        (FLEX, 3, 0, 200 * M, END, "4.50"),
        (FLEX, 9, 0, 0, END, "4.60"),
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


def test_conditions_and_channels(records: dict[Key, SavingsRateRecord]) -> None:
    assert records[(TRAD, 6, 0, 0, END)].conditions_text == BONUS_NOTE
    assert records[(TRAD, 13, 0, 0, END)].conditions_text is None  # bonus only 1–12 months
    assert records[(TRAD, 13, 0, 200_000 * M, END)].conditions_text == "Mức gửi từ 200 tỷ (bậc 2)"
    assert (
        records[(FLEX, 3, 0, 0, END)].conditions_text == "Áp dụng cho kỳ hạn từ 3 đến dưới 6 tháng"
    )
    assert records[(FLEX, 1, 0, 0, END)].conditions_text is None  # "1T – <2T" is exactly 1 month
    assert records[(TRAD, 1, 0, 0, END)].channel == Channel.COUNTER
    assert records[(ONLINE, 1, 0, 0, END)].channel == Channel.ONLINE
    assert not any(k[0] == FLEX and k[1] == 0 for k in records)  # "Renew" column skipped


def test_counts(records: dict[Key, SavingsRateRecord]) -> None:
    assert len(records) == 126


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<html>503</html>", "found 0"),
        # the page writes accents as HTML entities
        (TEXT.replace("TK Ph&uacute;c An Lộc", "TK An Phúc", 1), "product header changed"),
        (TEXT.replace(">L&atilde;i trả trước<", ">Lãi trước hạn<", 1), "payment header changed"),
        (
            TEXT.replace("Tiền gửi Online L&atilde;i trả trước", "Tiền gửi Online trả trước"),
            "found 0",
        ),
        (TEXT.replace("1.000 - &lt; 5.000", "1.000 - &lt; 3.000", 1), "unknown amount tier"),
        (TEXT.replace("Lãi suất 6,50 %/ năm (LCK)", "Lãi suất theo thỏa thuận"), "footnote"),
        (TEXT.replace(">13T<", ">13 tháng linh hoạt<", 1), "not a term"),
    ],
    ids=["blocked", "product", "payment", "online table", "tier", "footnote", "term"],
)
def test_layout_change_raises(content: str, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        AcbSavings.parse_content(content.encode())
