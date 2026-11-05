"""VietinBank savings adapter, against the page saved on 2026-10-26."""

import unicodedata
from decimal import Decimal

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.vietinbank import VietinbankSavings
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PAGE = fixture_bytes("vietinbank", "savings_2026-10-26.html")


def parse(content: bytes = PAGE) -> dict[int, SavingsRateRecord]:
    records: list[SavingsRateRecord] = VietinbankSavings.parse_content(content)  # type: ignore[assignment]
    return {r.term_months: r for r in records}


def test_exact_rates() -> None:
    r = parse()
    expected = {
        0: "0.1",  # Không kỳ hạn
        1: "2.1",
        2: "2.1",
        3: "2.4",
        5: "2.4",
        6: "3",
        11: "3",
        12: "5.4",
        13: "5.4",  # Trên 12 tháng đến 13 tháng
        14: "5.4",  # Trên 13 tháng đến dưới 18 tháng
        18: "5.4",
        24: "5.5",
        36: "5.5",
    }
    for term, rate in expected.items():
        assert r[term].rate_pct == Decimal(rate), term


def test_terms_and_bands() -> None:
    r = parse()
    # 0, 1..11, 12, 13, 14 (13-18), 18 (18-24), 24 (24-36), 36. Open bands skipped.
    assert sorted(r) == [0, *range(1, 12), 12, 13, 14, 18, 24, 36]
    assert r[14].conditions_text == "Áp dụng cho kỳ hạn: Trên 13 tháng đến dưới 18 tháng"
    assert r[24].conditions_text == "Áp dụng cho kỳ hạn: Từ 24 tháng đến dưới 36 tháng"
    assert r[12].conditions_text is None and r[13].conditions_text is None
    assert all(x.term_days == 0 for x in r.values())


def test_record_fields() -> None:
    for x in parse().values():
        assert x.product_name == "Tiền gửi thông thường"
        assert x.channel == Channel.COUNTER
        assert x.interest_payment == InterestPayment.END
        assert x.min_amount_vnd == 0 and x.effective_from is None


# --------------------------------------------------------------------------- layout changes

TEXT = PAGE.decode()
NFC = unicodedata.normalize("NFC", TEXT)  # the page mixes composed and decomposed accents


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<html><body>Bảo trì</body></html>", "found 0"),
        (TEXT.replace("LÃI SUẤT HUY ĐỘNG ĐỐI VỚI CÁC KỲ HẠN", "BIỂU LÃI SUẤT"), "found 0"),
        (TEXT.replace("VND (%/", "Lãi VND (%/"), "unexpected header"),
        # one copy of the 12-month row changes, the other doesn't
        (
            TEXT.replace(
                '>12 tháng</td><td class="p-4">5,4', '>12 tháng</td><td class="p-4">5,6', 1
            ),
            "twice with different",
        ),
        (TEXT.replace(">12 tháng</td>", ">Kỳ hạn 12 tháng (ưu đãi)</td>"), "not a term band"),
        (TEXT.replace(">5,4<!-- --> %", ">5,4%/tháng<!-- --> %"), "not a rate"),
        # the page uses a non-breaking space inside band labels
        (
            NFC.replace("Từ 6 tháng\xa0đến dưới 7 tháng", "Từ 6 tháng\xa0đến dưới 6 tháng"),
            "empty band",
        ),
    ],
    ids=["maintenance", "heading", "header", "copies", "term", "rate", "band"],
)
def test_layout_change_raises(content: str, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        VietinbankSavings.parse_content(content.encode())


def test_missing_core_term_raises() -> None:
    import re

    no_12 = re.sub(r"<tr[^>]*><td[^>]*>12 tháng</td>.*?</tr>", "", TEXT)
    with pytest.raises(AdapterBroken, match=r"\[12\]"):
        VietinbankSavings.parse_content(no_12.encode())
