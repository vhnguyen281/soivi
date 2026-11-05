"""Vietcombank savings adapter, against the API response saved on 2026-10-26."""

import json
from decimal import Decimal
from typing import Any

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.vietcombank import VietcombankSavings
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

FIXTURE = fixture_bytes("vietcombank", "savings_2026-10-26.json")


def parse(content: bytes = FIXTURE) -> list[SavingsRateRecord]:
    records = VietcombankSavings.parse_content(content)
    assert all(isinstance(r, SavingsRateRecord) for r in records)
    return records  # type: ignore[return-value]


def rate(records: list[SavingsRateRecord], product: str, months: int, days: int = 0) -> Decimal:
    [match] = [
        r
        for r in records
        if (r.product_name, r.term_months, r.term_days) == (product, months, days)
    ]
    return match.rate_pct


COUNTER = "Tiết kiệm tại quầy"
FIXED = "Tiền gửi có kỳ hạn tại quầy"
ONLINE = "Tiền gửi trực tuyến"


def test_counts_vnd_only() -> None:
    records = parse()
    assert len(records) == 13 + 10 + 7  # Savings, FixedDeposit, Online rows in VND


@pytest.mark.parametrize(
    ("product", "months", "days", "expected"),
    [
        (COUNTER, 0, 0, "0.1"),  # Không kỳ hạn
        (COUNTER, 0, 7, "0.2"),  # 7 ngày
        (COUNTER, 0, 14, "0.2"),
        (COUNTER, 1, 0, "2.1"),
        (COUNTER, 3, 0, "2.4"),
        (COUNTER, 6, 0, "3"),
        (COUNTER, 12, 0, "5.4"),
        (COUNTER, 24, 0, "5.5"),
        (COUNTER, 60, 0, "4.8"),
        (FIXED, 12, 0, "5.4"),
        (ONLINE, 0, 14, "0.2"),
        (ONLINE, 24, 0, "5.5"),
    ],
)
def test_exact_rates(product: str, months: int, days: int, expected: str) -> None:
    assert rate(parse(), product, months, days) == Decimal(expected)


def test_channels_and_defaults() -> None:
    records = parse()
    assert {r.channel for r in records if r.product_name == ONLINE} == {Channel.ONLINE}
    assert {r.channel for r in records if r.product_name != ONLINE} == {Channel.COUNTER}
    assert {r.interest_payment for r in records} == {InterestPayment.END}
    assert {r.min_amount_vnd for r in records} == {0}
    assert not any(r.is_cd for r in records)
    assert all(r.effective_from is None for r in records)  # the API gives no effective date


def test_no_float_rounding() -> None:
    # 0.054 as a float * 100 would be 5.4000000000000004
    assert rate(parse(), COUNTER, 12) == Decimal("5.4")
    assert str(rate(parse(), COUNTER, 12)) == "5.4"


# --------------------------------------------------------------------------- layout changes


def mutate(change: Any) -> bytes:
    payload = json.loads(FIXTURE)
    change(payload)
    return json.dumps(payload).encode()


def _set(path: str, value: object) -> Any:
    def apply(p: dict[str, Any]) -> None:
        p[path] = value

    return apply


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<html>Bao tri he thong</html>", "not JSON"),
        (FIXTURE[: len(FIXTURE) // 2], "not JSON"),
        (mutate(lambda p: p.pop("Data")), "'Data' list"),
        (mutate(_set("AccountType", "Corporate")), "not 'Personal'"),
        (mutate(lambda p: p["Data"].pop()), "Count"),
        (mutate(lambda p: p["Data"][0].pop("rates")), "missing keys"),
        (mutate(lambda p: p["Data"][0].update(tenorType="Premium")), "unknown tenorType"),
        (mutate(lambda p: p["Data"][0].update(rates="0,1%")), "not a fraction"),
        (
            mutate(lambda p: p["Data"][0].update(rates=5.4)),
            "not a fraction",
        ),  # percent, not fraction
        (mutate(lambda p: p["Data"][9].update(tenorDisplay="3 tháng")), "does not match"),
        (mutate(lambda p: p["Data"][9].update(tenorDisplay="Kỳ hạn linh hoạt")), "not a term"),
        (mutate(lambda p: p["Data"][9].update(tenor="1-weeks")), "unknown tenor key"),
    ],
)
def test_layout_change_raises(content: bytes, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        VietcombankSavings.parse_content(content)


def test_missing_product_raises() -> None:
    def drop_online(p: dict[str, Any]) -> None:
        p["Data"] = [r for r in p["Data"] if r["tenorType"] != "Online"]
        p["Count"] = len(p["Data"])

    with pytest.raises(AdapterBroken, match="products missing"):
        VietcombankSavings.parse_content(mutate(drop_online))


def test_missing_core_term_raises() -> None:
    def drop_12m_vnd(p: dict[str, Any]) -> None:
        p["Data"] = [
            r for r in p["Data"] if not (r["tenor"] == "12-months" and r["currencyCode"] == "VND")
        ]
        p["Count"] = len(p["Data"])

    with pytest.raises(AdapterBroken, match="12-month VND rate missing"):
        VietcombankSavings.parse_content(mutate(drop_12m_vnd))
