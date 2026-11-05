"""BIDV savings adapters, against the servlet responses saved on 2026-10-26."""

import json
from decimal import Decimal
from typing import Any

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.bidv import BidvSavingsCounter, BidvSavingsOnline, js_unescape
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

COUNTER = fixture_bytes("bidv", "savings_2026-10-26.json")
ONLINE = fixture_bytes("bidv", "savings_online_2026-10-26.json")


def rates(adapter: Any, content: bytes) -> dict[tuple[int, int], Decimal]:
    records: list[SavingsRateRecord] = adapter.parse_content(content)
    return {(r.term_months, r.term_days): r.rate_pct for r in records}


def test_counter_exact_rates() -> None:
    r = rates(BidvSavingsCounter, COUNTER)
    assert len(r) == 13
    assert r[(0, 0)] == Decimal("0.1")  # Không kỳ hạn
    assert r[(1, 0)] == Decimal("2.1")
    assert r[(3, 0)] == Decimal("2.4")
    assert r[(5, 0)] == Decimal("2.4")
    assert r[(6, 0)] == Decimal("3.0")
    assert r[(12, 0)] == Decimal("5.4")
    assert r[(13, 0)] == Decimal("5.4")
    assert r[(36, 0)] == Decimal("5.5")


def test_online_exact_rates() -> None:
    r = rates(BidvSavingsOnline, ONLINE)
    assert len(r) == 20  # 3 weekly terms, 1-13 months, 15, 18, 24, 36
    assert r[(0, 7)] == Decimal("0.5")  # 1 tuần
    assert r[(0, 21)] == Decimal("0.5")  # 3 tuần
    assert r[(1, 0)] == Decimal("4.75")
    assert r[(6, 0)] == Decimal("6.6")
    assert r[(12, 0)] == Decimal("6.8")
    assert r[(15, 0)] == Decimal("6.6")
    assert r[(36, 0)] == Decimal("6.8")


def test_record_fields() -> None:
    counter = BidvSavingsCounter.parse_content(COUNTER)
    online = BidvSavingsOnline.parse_content(ONLINE)
    assert {(r.product_name, r.channel) for r in counter} == {  # type: ignore[attr-defined]
        ("Tiền gửi tại quầy", Channel.COUNTER)
    }
    assert {(r.product_name, r.channel) for r in online} == {  # type: ignore[attr-defined]
        ("Tiền gửi Online", Channel.ONLINE)
    }
    for r in counter + online:
        assert r.interest_payment == InterestPayment.END  # type: ignore[attr-defined]
        assert r.effective_from is None  # no effective date stated on either page


def test_note_is_decoded() -> None:
    note = js_unescape(json.loads(ONLINE)["note_vi"])
    assert note.startswith("Lãi suất trên áp dụng cho tiền gửi trả lãi cuối kỳ")


def test_effective_date_is_read_from_note_when_present() -> None:
    def with_note(p: dict[str, Any]) -> None:
        p["note_vi"] = (
            "Bi%u1EC3u l%E3i su%u1EA5t c%F3 hi%u1EC7u l%u1EF1c t%u1EEB ng%E0y 22/10/2026."
        )

    [first, *_] = BidvSavingsCounter.parse_content(mutate(COUNTER, with_note))
    assert str(first.effective_from) == "2026-10-22"


# --------------------------------------------------------------------------- layout changes


def mutate(content: bytes, change: Any) -> bytes:
    payload = json.loads(content)
    change(payload)
    return json.dumps(payload).encode()


def _row(region: str, i: int, **kw: str) -> Any:
    def apply(p: dict[str, Any]) -> None:
        p[region]["data"][i].update(kw)

    return apply


def _both(i: int, **kw: str) -> Any:
    def apply(p: dict[str, Any]) -> None:
        for region in ("hanoi", "hcm"):
            p[region]["data"][i].update(kw)

    return apply


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<html>Service Unavailable</html>", "not JSON"),
        (mutate(COUNTER, lambda p: p.update(status=0)), "status is not 1"),
        (mutate(COUNTER, lambda p: p.pop("hcm")), "missing region block 'hcm'"),
        (mutate(COUNTER, _both(7, VND="5,4 %/tháng")), "not a rate"),
        (mutate(COUNTER, _both(7, title_vi="Kỳ hạn đặc biệt")), "not a term"),
        (
            mutate(COUNTER, lambda p: [b["visible"].clear() for b in (p["hanoi"], p["hcm"])]),
            "VND column is hidden",
        ),
        (
            mutate(COUNTER, lambda p: [b["data"].pop(7) for b in (p["hanoi"], p["hcm"])]),
            r"no VND rate for \[12\] months",
        ),
        (
            mutate(COUNTER, lambda p: [b["data"][0].pop("VND") for b in (p["hanoi"], p["hcm"])]),
            "row without",
        ),
    ],
)
def test_counter_layout_change_raises(content: bytes, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        BidvSavingsCounter.parse_content(content)


def test_regions_are_stored_separately_when_they_differ() -> None:
    records = BidvSavingsCounter.parse_content(mutate(COUNTER, _row("hcm", 7, VND="5.6")))
    by_region = {(r.region, r.term_months): r.rate_pct for r in records}  # type: ignore[attr-defined]
    assert by_region[("hanoi", 12)] == Decimal("5.4")
    assert by_region[("hcm", 12)] == Decimal("5.6")
    assert {r.region for r in records} == {"hanoi", "hcm"}  # type: ignore[attr-defined]
    assert len(records) == 26


def test_identical_regions_are_nationwide() -> None:
    assert {r.region for r in BidvSavingsCounter.parse_content(COUNTER)} == {""}  # type: ignore[attr-defined]


def test_online_preferential_column_raises() -> None:
    with pytest.raises(AdapterBroken, match="TGVND"):
        BidvSavingsOnline.parse_content(mutate(ONLINE, _both(14, TGVND="+0.2")))
