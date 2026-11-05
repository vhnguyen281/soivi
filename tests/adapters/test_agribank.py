"""Agribank savings adapter, against the rate fragment saved on 2026-10-26."""

from decimal import Decimal

import pytest

from core.enums import Channel
from pipeline.adapters.agribank import AgribankSavings
from pipeline.adapters.base import AdapterBroken
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PAGE = fixture_bytes("agribank", "savings_2026-10-26.html")
TEXT = PAGE.decode()


def parse(content: bytes = PAGE) -> dict[tuple[str, int], SavingsRateRecord]:
    records: list[SavingsRateRecord] = AgribankSavings.parse_content(content)  # type: ignore[assignment]
    return {(r.product_name, r.term_months): r for r in records}


@pytest.mark.parametrize(
    ("product", "months", "rate"),
    [
        ("Tiền gửi tiết kiệm", 0, "0.2"),
        ("Tiền gửi tiết kiệm", 1, "2.6"),
        ("Tiền gửi tiết kiệm", 3, "2.9"),
        ("Tiền gửi tiết kiệm", 6, "3.5"),
        ("Tiền gửi tiết kiệm", 12, "5.4"),
        ("Tiền gửi tiết kiệm", 15, "5.4"),
        ("Tiền gửi tiết kiệm", 24, "5.5"),
        ("Tiền gửi thanh toán", 0, "0.2"),
        ("Tiền gửi trực tuyến", 1, "4.75"),
        ("Tiền gửi trực tuyến", 6, "6.6"),
        ("Tiền gửi trực tuyến", 24, "6.8"),
    ],
)
def test_exact_rates(product: str, months: int, rate: str) -> None:
    assert parse()[(product, months)].rate_pct == Decimal(rate)


def test_counts_and_fields() -> None:
    r = parse()
    assert len(r) == 17 + 1 + 5  # savings terms, payment account, online bands
    online = [x for (p, _), x in r.items() if p == "Tiền gửi trực tuyến"]
    assert {x.channel for x in online} == {Channel.ONLINE}
    assert r[("Tiền gửi trực tuyến", 6)].conditions_text == (
        "Mức lãi suất tối đa; áp dụng cho kỳ hạn: Từ 06 tháng đến dưới 12 tháng"
    )
    assert r[("Tiền gửi trực tuyến", 24)].conditions_text.endswith("Từ 24 tháng trở lên")  # type: ignore[union-attr]
    assert r[("Tiền gửi tiết kiệm", 12)].conditions_text is None
    assert r[("Tiền gửi tiết kiệm", 12)].channel == Channel.COUNTER


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<p>Đang cập nhật</p>", "found 0 and 0"),
        (TEXT.replace("LÃI SUẤT TIỀN GỬI TRỰC TUYẾN", "LÃI SUẤT ƯU ĐÃI"), "found 1 and 0"),
        (TEXT.replace("Ngoại tệ khác", "GBP"), "found 0 and 1"),
        (TEXT.replace("Mức lãi suất tối đa", "Mức lãi suất"), "unexpected online header"),
        (TEXT.replace("5.4%", "5.4%/tháng", 1), "not a rate"),
        (TEXT.replace("Từ 24 tháng trở lên", "Từ 36 tháng trở lên"), "online bands changed"),
        (TEXT.replace("15 Tháng", "Linh hoạt"), "not a term"),
    ],
    ids=[
        "maintenance",
        "online heading",
        "counter header",
        "online header",
        "rate",
        "bands",
        "term",
    ],
)
def test_layout_change_raises(content: str, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        AgribankSavings.parse_content(content.encode())
