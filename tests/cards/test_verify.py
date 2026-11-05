"""Normalising amounts and percentages, and checking quotes against the page."""

from decimal import Decimal

import pytest

from pipeline.cards.fields import BY_NAME
from pipeline.cards.verify import Rejected, check, money, pct, quote_on_page


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("1.000.000 VNĐ", 1_000_000),
        ("1 triệu", 1_000_000),
        ("1.499.000 VND/thẻ", 1_499_000),
        ("100.000 VND", 100_000),
        ("66.000VND/giao dịch", 66_000),
        ("5 triệu/tháng", 5_000_000),
        ("7 triệu/ tháng", 7_000_000),
        ("700 nghìn điểm", 700_000),
        ("250.000.000 VNĐ", 250_000_000),
        ("Miễn phí", 0),
        ("miễn phí hoàn toàn", 0),
        ("Không thu phí", 0),
    ],
)
def test_money(text: str, amount: int) -> None:
    assert money(text) == amount


@pytest.mark.parametrize(
    ("text", "rate"),
    [
        ("2.59%*số tiền giao dịch", Decimal("2.59")),
        ("1,1%", Decimal("1.1")),
        ("4%*số tiền giao dịch", Decimal("4")),
        ("6% * số tiền chậm thanh toán", Decimal("6")),
        ("Miễn phí", Decimal("0")),
    ],
)
def test_pct(text: str, rate: Decimal) -> None:
    assert pct(text) == rate


@pytest.mark.parametrize("text", ["không có", "theo thể lệ", ""])
def test_unreadable_values_are_rejected(text: str) -> None:
    with pytest.raises(Rejected):
        money(text)
    with pytest.raises(Rejected):
        pct(text)


def test_quote_must_be_on_the_page_whitespace_aside() -> None:
    page = "4.1 | | Thẻ tín dụng Visa Signature | 1.499.000 VND/thẻ\nPhí\nthường niên"
    assert quote_on_page("Thẻ tín dụng Visa Signature | 1.499.000 VND/thẻ", page)
    assert quote_on_page("Phí thường niên", page)  # wrapped line
    assert not quote_on_page("Thẻ tín dụng Visa Signature | 1.500.000 VND/thẻ", page)
    assert not quote_on_page("", page)


def test_value_must_be_in_its_quote() -> None:
    row = "Thẻ tín dụng Techcombank Style | 2.59%*số tiền giao dịch"
    assert check(BY_NAME["fx_fee_pct"], "2.59%", row) == Decimal("2.59")
    with pytest.raises(Rejected, match="not in the quote"):
        check(BY_NAME["fx_fee_pct"], "2.95%", row)
    fee = "Thẻ tín dụng Visa Signature | 1.499.000 VND/thẻ"
    assert check(BY_NAME["annual_fee_primary_vnd"], "1.499.000 VND/thẻ", fee) == 1_499_000
    with pytest.raises(Rejected, match="not in the quote"):
        check(BY_NAME["annual_fee_primary_vnd"], "1.299.000 VND", fee)
    free = "Phí phát hành (trên cơ sở hợp đồng tín dụng mới)* | Miễn phí"
    assert check(BY_NAME["annual_fee_primary_vnd"], "Miễn phí", free) == 0
    with pytest.raises(Rejected):
        check(BY_NAME["annual_fee_primary_vnd"], "Miễn phí", fee)  # not free per the quote
    assert check(BY_NAME["interest_free_days"], "45 ngày", "Miễn lãi tới 45 ngày") == 45


def test_text_fields_take_the_quote_verbatim() -> None:
    quote = "Đặc quyền sử dụng phòng chờ sân bay\nmiễn phí"
    value = check(BY_NAME["other_perks_text"], "free lounge (paraphrase)", quote)
    assert value == "Đặc quyền sử dụng phòng chờ sân bay miễn phí"


def test_booleans() -> None:
    assert check(BY_NAME["lounge_unlimited"], "true", "không giới hạn số lần") is True
    with pytest.raises(Rejected):
        check(BY_NAME["lounge_unlimited"], "maybe", "x")


def test_interest_needs_a_stated_period() -> None:
    spec = BY_NAME["interest_rate_pct"]
    assert check(spec, "36%", "Lãi suất thẻ tín dụng: 36%/năm") == Decimal("36")
    with pytest.raises(Rejected, match="per year"):
        check(spec, "3.99%", "VPBank MC2 MasterCard | 3.99%")  # monthly? yearly? not stated
    with pytest.raises(Rejected, match="per year"):
        check(spec, "18%", "Thẻ Visa Infinite/Private Banking | 18%")


def test_up_to_rates_are_not_rewards() -> None:
    spec = BY_NAME["rate_pct"]
    assert check(spec, "15%", "Hoàn 15% cho giao dịch Ăn uống (*), tối đa 500,000") == Decimal("15")
    for value, quote in (
        ("10%", "Lên đến 10% giá trị giao dịch"),
        ("10%", "Hoàn tiền tới 10%"),
        ("5%", "up to 5% cashback"),
    ):
        with pytest.raises(Rejected, match="ceiling"):
            check(spec, value, quote)


def test_travel_insurance_must_say_travel() -> None:
    spec = BY_NAME["travel_insurance"]
    assert check(spec, "true", "Bảo hiểm du lịch toàn cầu giá trị tới 11,65 tỷ đồng") is True
    with pytest.raises(Rejected, match="travel"):
        check(spec, "true", "Bảo hiểm cho chủ thẻ giá trị tới 13,2 tỷ VND")
    assert check(spec, "false", "Bảo hiểm cho chủ thẻ") is False


def test_interest_ranges_are_rejected() -> None:
    spec = BY_NAME["interest_rate_pct"]
    assert check(spec, "20%", "Lãi suất: 20%/năm, miễn lãi tối đa 45 ngày") == Decimal("20")
    with pytest.raises(Rejected, match="range"):
        check(spec, "15,5%", "Lãi suất: 15,5% - 16,5%/năm")


def test_ranges_with_words_and_numbers_with_units() -> None:
    with pytest.raises(Rejected, match="range"):
        check(BY_NAME["interest_rate_pct"], "17%", "Lãi suất: 17% đến 18%/năm")
    spec = BY_NAME["points_per_spend"]
    assert check(spec, "20 điểm", "Nhận 20 điểm/1,000 VND chi tiêu") == Decimal("20")
    assert check(spec, "1 dặm", "Chi tiêu nước ngoài: 25,000 VND = 1 dặm") == Decimal("1")
    with pytest.raises(Rejected, match="not a number"):
        check(spec, "20 hoặc 30 điểm", "Nhận 20 hoặc 30 điểm")
