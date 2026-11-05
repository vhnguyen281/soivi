"""Techcombank cards: the saved tariff PDF and card page, with mocked API answers.

The answers (tests/fixtures/techcombank/card_*_llm_answers.json) quote the saved
documents; three tariff facts are deliberately wrong to test the checks.
"""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from core.enums import CardNetwork
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.techcombank_cards import (
    TECHCOMBANK_CARDS,
    TechcombankCardProducts,
    TechcombankCardTariff,
)
from pipeline.cards.adapter import LlmCardAdapter
from pipeline.cards.build import Built
from pipeline.cards.llm import CardExtractor
from pipeline.records import CardPerkRecord, CardRewardRecord, CardTermsRecord
from tests.cards.conftest import PRODUCTS_HTML, TARIFF_PDF, FakeClient, saved_answers


def use_answers(
    monkeypatch: pytest.MonkeyPatch, adapter: type[LlmCardAdapter], answers: dict[int, Any]
) -> FakeClient:
    client = FakeClient(answers)
    extractor = CardExtractor(adapter.catalogue, adapter.mode, client=client)
    monkeypatch.setattr(adapter, "extractor", classmethod(lambda cls: extractor))
    return client


@pytest.fixture
def tariff(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Built, FakeClient]]:
    client = use_answers(
        monkeypatch, TechcombankCardTariff, saved_answers("card_tariff_llm_answers.json")
    )
    yield TechcombankCardTariff.build_from(TARIFF_PDF.read_bytes()), client


def terms_by_card(built: Built) -> dict[str, CardTermsRecord]:
    return {r.card_name: r for r in built.records if isinstance(r, CardTermsRecord)}


def test_one_call_per_page(tariff: tuple[Built, FakeClient]) -> None:
    _, client = tariff
    assert len(client.requests) == 8


def test_terms_for_every_published_card(tariff: tuple[Built, FakeClient]) -> None:
    built, _ = tariff
    terms = terms_by_card(built)
    assert sorted(terms) == sorted(
        [
            "Techcombank Visa Signature",
            "Techcombank Spark",
            "Techcombank Everyday",
            "Techcombank Style",
            "Techcombank Visa Eco",
            "Techcombank Visa Classic",
            "Vietnam Airlines Techcombank Visa Platinum",
            "Vietnam Airlines Techcombank Visa Gold",
            "Vietnam Airlines Techcombank Visa Classic",
        ]
    )
    assert all(isinstance(r, CardTermsRecord) for r in built.records)
    assert "DreamCard" not in terms  # network not stated: never published


def test_visa_signature_values_and_evidence(tariff: tuple[Built, FakeClient]) -> None:
    sig = terms_by_card(tariff[0])["Techcombank Visa Signature"]
    assert sig.network is CardNetwork.VISA and sig.tier == "signature"
    assert sig.annual_fee_primary_vnd == 1_499_000
    assert sig.fx_fee_pct == Decimal("1.1")
    assert (sig.cash_advance_pct, sig.cash_advance_min_vnd) == (Decimal("4"), 100_000)
    assert (sig.late_fee_pct, sig.late_fee_min_vnd) == (Decimal("6"), 200_000)
    assert sig.fee_waiver_spend_vnd == 250_000_000
    # not in the tariff: stays null, never guessed
    assert sig.interest_rate_pct is None and sig.interest_free_days is None
    assert sig.annual_fee_supp_vnd is None and sig.min_monthly_income_vnd is None
    assert sig.evidence is not None
    assert sig.evidence["annual_fee_primary_vnd"] == {
        "page": 1,
        "quote": "Thẻ tín dụng Visa Signature | 1.499.000 VND/thẻ",
        "value": "1.499.000 VND/thẻ",
    }
    assert sig.evidence["late_fee_min_vnd"]["page"] == 5
    assert sig.evidence["fee_waiver_spend_vnd"]["page"] == 8
    assert sig.source_page == 1


@pytest.mark.parametrize(
    ("card", "annual", "fx", "late_min", "waiver"),
    [
        ("Techcombank Spark", 899_000, "2.59", 150_000, 150_000_000),
        ("Techcombank Everyday", 599_000, "2.95", 150_000, 150_000_000),
        ("Techcombank Visa Eco", 599_000, "2.95", 150_000, 150_000_000),
        ("Vietnam Airlines Techcombank Visa Platinum", 990_000, "2.59", 150_000, 150_000_000),
        ("Vietnam Airlines Techcombank Visa Gold", 590_000, "2.95", 150_000, 100_000_000),
        ("Vietnam Airlines Techcombank Visa Classic", 390_000, "2.95", 150_000, 80_000_000),
    ],
)
def test_card_terms(
    tariff: tuple[Built, FakeClient],
    card: str,
    annual: int,
    fx: str,
    late_min: int,
    waiver: int,
) -> None:
    t = terms_by_card(tariff[0])[card]
    assert t.annual_fee_primary_vnd == annual
    assert t.fx_fee_pct == Decimal(fx)
    assert t.late_fee_min_vnd == late_min
    assert t.fee_waiver_spend_vnd == waiver


def test_bad_facts_are_dropped_with_a_note(tariff: tuple[Built, FakeClient]) -> None:
    built, _ = tariff
    terms = terms_by_card(built)
    notes = {(n.rule, n.key["card"], n.field) for n in built.notes}

    # Style's row says 2.59%; the answer said 2.95% -> value not in its quote
    assert terms["Techcombank Style"].fx_fee_pct is None
    assert ("dropped_unreadable", "Techcombank Style", "fx_fee_pct") in notes
    # a quote that isn't on the page
    assert terms["Techcombank Everyday"].interest_free_days is None
    assert ("dropped_quote_not_found", "Techcombank Everyday", "interest_free_days") in notes
    # two different readings of the waiver spend -> neither is used
    assert terms["Techcombank Visa Classic"].fee_waiver_spend_vnd is None
    conflict = next(n for n in built.notes if n.rule == "dropped_conflict")
    assert conflict.key == {"card": "Techcombank Visa Classic"}
    assert "500.000 VNĐ" in conflict.message and "80.000.000 VNĐ" in conflict.message
    # DreamCard was read but is not published
    assert ("not_published", "DreamCard", None) in notes
    assert len(built.notes) == 4


def test_unknown_card_in_document_breaks_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = saved_answers("card_tariff_llm_answers.json")
    answers[1]["unlisted_cards"] = ["Thẻ tín dụng Techcombank Mới"]
    use_answers(monkeypatch, TechcombankCardTariff, answers)
    with pytest.raises(AdapterBroken, match="Techcombank Mới"):
        TechcombankCardTariff.parse_content(TARIFF_PDF.read_bytes())


def test_missing_annual_fee_breaks_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = saved_answers("card_tariff_llm_answers.json")
    answers[1]["cards"] = [c for c in answers[1]["cards"] if c["card"] != "TCB_SPARK"]
    use_answers(monkeypatch, TechcombankCardTariff, answers)
    with pytest.raises(AdapterBroken, match="no verified annual fee for: Techcombank Spark"):
        TechcombankCardTariff.parse_content(TARIFF_PDF.read_bytes())


def test_nothing_verifiable_breaks_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    use_answers(monkeypatch, TechcombankCardProducts, {})
    with pytest.raises(AdapterBroken, match="no value could be verified"):
        TechcombankCardProducts.parse_content(PRODUCTS_HTML.read_bytes())


def test_product_page_rewards_and_perks(monkeypatch: pytest.MonkeyPatch) -> None:
    use_answers(
        monkeypatch, TechcombankCardProducts, saved_answers("card_products_llm_answers.json")
    )
    built = TechcombankCardProducts.build_from(PRODUCTS_HTML.read_bytes(), "text/html")
    # The list page gives only the headline "Hoàn tiền lên tới 5 triệu/tháng, tới 10%":
    # an "up to" rate is a ceiling, not the reward rate, so nothing is stored
    # (DECISIONS 2026-10-30). The rates need each card's own page.
    assert [r for r in built.records if isinstance(r, CardRewardRecord)] == []
    dropped = [n for n in built.notes if n.rule == "dropped_unreadable" and "ceiling" in n.message]
    assert {n.key["card"] for n in dropped} >= {
        "Techcombank Visa Signature",
        "Techcombank Priority Visa Signature",
    }

    perks = {r.card_name: r for r in built.records if isinstance(r, CardPerkRecord)}
    assert perks["Techcombank Priority Visa Signature"].other_perks_text == (
        "Đặc quyền sử dụng phòng chờ sân bay miễn phí"
    )
    infinite = perks["Techcombank Visa Infinite"]
    assert infinite.lounge_unlimited is False  # not stated
    # several perks add up; each keeps its own quote
    assert infinite.other_perks_text == (
        "Đặc quyền phòng chờ sân bay hạng thương gia; Đặc quyền đón tiễn cao cấp tại sân bay"
    )
    assert infinite.evidence is not None
    assert [e["quote"] for e in infinite.evidence["other_perks_text"]["also"]] == [
        "Đặc quyền đón tiễn\ncao cấp tại sân bay"
    ]

    # "Tích điểm tới 8%" is points without a points-per-spend rate: can't be stored
    assert ("dropped_incomplete_reward", "Techcombank Everyday") in {
        (n.rule, n.key["card"]) for n in built.notes
    }


def test_catalogue_is_consistent() -> None:
    names = [c.name for c in TECHCOMBANK_CARDS.cards]
    assert len(names) == len(set(names))
    assert [c.code for c in TECHCOMBANK_CARDS.cards if not c.publish] == ["DREAMCARD"]
