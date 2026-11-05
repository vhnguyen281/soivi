"""BIDV and VPBank credit cards: the saved fee schedules, with the model's real
answers saved from a live run on 2026-10-29 (tests/fixtures/<bank>/card_tariff_llm_answers.json).
Expected values were checked by hand against the PDFs."""

import json
from pathlib import Path
from typing import Any

import pytest

from core.enums import CardNetwork
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.bidv_cards import BIDV_CARDS, BidvCardTariff
from pipeline.adapters.vpbank_cards import VPBANK_CARDS, VpbankCardTariff, newest_card_schedule
from pipeline.cards.adapter import LlmCardAdapter
from pipeline.cards.build import Built
from pipeline.cards.llm import CardExtractor
from pipeline.records import CardTermsRecord
from tests.cards.conftest import FIXTURES as TCB
from tests.cards.conftest import FakeClient
from tests.cards.conftest import saved_answers as _tcb_answers  # noqa: F401

FIX = TCB.parent
BIDV_PDF = FIX / "bidv" / "card_tariff_2026-10-29.pdf"
VPB_PDF = FIX / "vpbank" / "card_tariff_2026-10-19.pdf"


def answers(bank: str) -> dict[int, Any]:
    data = json.loads((FIX / bank / "card_tariff_llm_answers.json").read_text(encoding="utf-8"))
    return {a.pop("page"): a for a in data}


def built(
    monkeypatch: pytest.MonkeyPatch, adapter: type[LlmCardAdapter], pdf: Path, bank: str
) -> tuple[Built, FakeClient]:
    client = FakeClient(answers(bank))
    extractor = CardExtractor(
        adapter.catalogue, "terms", client=client, notes=adapter.reading_notes
    )
    monkeypatch.setattr(adapter, "extractor", classmethod(lambda cls: extractor))
    return adapter.build_from(pdf.read_bytes(), "application/pdf"), client


def by_card(b: Built) -> dict[str, CardTermsRecord]:
    return {r.card_name: r for r in b.records if isinstance(r, CardTermsRecord)}


# --------------------------------------------------------------------------- BIDV


@pytest.fixture
def bidv(monkeypatch: pytest.MonkeyPatch) -> tuple[Built, FakeClient]:
    return built(monkeypatch, BidvCardTariff, BIDV_PDF, "bidv")


def test_bidv_reads_only_the_credit_card_section(bidv: tuple[Built, FakeClient]) -> None:
    _, client = bidv
    assert len(client.requests) == 6  # pages 1-6 of 24
    system = client.requests[0]["system"][0]["text"]
    assert "KHCN thông thường" in system and "Các trường hợp còn lại" in system


@pytest.mark.parametrize(
    ("card", "annual", "supp", "late_pct", "late_min"),
    [
        ("BIDV Visa Infinite (gói đặc quyền 30 triệu)", 30_000_000, 30_000_000, "4", 100_000),
        ("BIDV Visa Infinite (gói đặc quyền 5 triệu)", 5_000_000, 5_000_000, "4", 100_000),
        ("BIDV JCB Ultimate", 1_500_000, 600_000, "6", 100_000),
        ("BIDV Mastercard World Travel", 1_600_000, 1_000_000, "6", 200_000),
        ("BIDV Visa Cashback 360", 1_000_000, 600_000, "4", 100_000),
        ("BIDV Visa Easy", 200_000, 100_000, "4", 100_000),
        ("BIDV Mastercard Vietravel Platinum", 500_000, 250_000, "4", 100_000),
    ],
)
def test_bidv_terms(
    bidv: tuple[Built, FakeClient], card: str, annual: int, supp: int, late_pct: str, late_min: int
) -> None:
    t = by_card(bidv[0])[card]
    assert (t.annual_fee_primary_vnd, t.annual_fee_supp_vnd) == (annual, supp)
    assert (str(t.late_fee_pct), t.late_fee_min_vnd) == (late_pct, late_min)


def test_bidv_general_rows_and_what_stays_empty(bidv: tuple[Built, FakeClient]) -> None:
    cards = by_card(bidv[0])
    easy = cards["BIDV Visa Easy"]
    # the general rate, not the BIDV-machines-only 1%
    assert (str(easy.cash_advance_pct), easy.cash_advance_min_vnd) == ("3.64", 50_000)
    assert str(easy.fx_fee_pct) == "1"
    # interest is "12%"/"20%"/"22%" with no period stated: never stored as yearly
    assert all(r.interest_rate_pct is None for r in cards.values())
    # discontinued cards (annex): annual fees only
    assert cards["BIDV Visa Premier"].fx_fee_pct is None
    assert cards["BIDV Visa Premier"].annual_fee_primary_vnd == 1_000_000
    assert "BIDV Private Banking" not in cards  # network not stated
    assert len(cards) == 18


def test_bidv_catalogue_networks_come_from_card_names() -> None:
    for card in BIDV_CARDS.cards:
        if card.network is CardNetwork.VISA:
            assert "Visa" in card.name
        elif card.network is CardNetwork.MASTERCARD:
            assert "Mastercard" in card.name
        elif card.network is CardNetwork.JCB:
            assert "JCB" in card.name


# --------------------------------------------------------------------------- VPBank


@pytest.fixture
def vpbank(monkeypatch: pytest.MonkeyPatch) -> tuple[Built, FakeClient]:
    return built(monkeypatch, VpbankCardTariff, VPB_PDF, "vpbank")


def test_vpbank_values_carry_their_card_column(vpbank: tuple[Built, FakeClient]) -> None:
    b, client = vpbank
    content = client.requests[1]["messages"][0]["content"]
    assert "2.2. Thẻ phụ | [No.1] Không thu phí | [MC2] 150.000 VND" in content
    mc2 = by_card(b)["VPBank MC2 Mastercard"]
    assert mc2.evidence is not None
    # the quote carries the card's column label, which is what proves the mapping
    assert "[MC2] 359.000 VND" in mc2.evidence["annual_fee_primary_vnd"]["quote"]


@pytest.mark.parametrize(
    ("card", "annual", "supp", "waiver"),
    [
        ("VPBank MC2 Mastercard", 359_000, 150_000, 120_000_000),
        ("VPBank Z JCB", 599_000, 0, 120_000_000),
        ("VPBank Visa Signature Travel Miles", 1_200_000, 0, 180_000_000),
        ("VPBank YoJo Visa Platinum", 699_000, 250_000, 120_000_000),
        ("VPBank MWG Mastercard", 399_000, 250_000, 120_000_000),
        ("VPBank S Rewards Mastercard", 599_000, 249_000, 120_000_000),
        ("VPBank Private Visa Infinite Privilege", 25_000_000, 8_000_000, 250_000_000),
        ("VPBank Flex Mastercard", 359_000, None, 120_000_000),  # credit column, not debit
    ],
)
def test_vpbank_terms(
    vpbank: tuple[Built, FakeClient], card: str, annual: int, supp: int | None, waiver: int
) -> None:
    t = by_card(vpbank[0])[card]
    assert (t.annual_fee_primary_vnd, t.annual_fee_supp_vnd, t.fee_waiver_spend_vnd) == (
        annual,
        supp,
        waiver,
    )
    assert t.interest_rate_pct is None  # "3.99%" has no period


def test_vpbank_unpublished_cards(vpbank: tuple[Built, FakeClient]) -> None:
    b, _ = vpbank
    published = set(by_card(b))
    assert len(published) == 12
    held = {n.key["card"] for n in b.notes if n.rule == "not_published"}
    assert {"VPBank Lady", "VPBank Shopee Platinum", "VPBank Diamond World"} <= held
    assert not published & held
    assert [n for n in b.notes if n.rule != "not_published"] == []  # "Không thu phí" = 0


def test_vpbank_finds_the_newest_card_schedule() -> None:
    listing = (FIX / "vpbank" / "card_documents_2026-10-29.json").read_bytes()
    assert newest_card_schedule(listing) == (
        "/-/media/vpbank-latest/tai-lieu-bieu-mau/bieu-phi/khcn/2026/"
        "BIEU-PHI-THE-TIN-DUNG-TAI-VPBANK---KHOI-KHCN-202610.pdf"
    )
    with pytest.raises(AdapterBroken, match="no document titled"):
        newest_card_schedule(b'{"data": [{"title": "Something else", "itemList": []}]}')
    with pytest.raises(AdapterBroken, match="unexpected shape"):
        newest_card_schedule(b"<html>")


def test_vpbank_catalogue_has_every_card_in_the_schedule() -> None:
    codes = VPBANK_CARDS.codes
    assert len(codes) == len(set(codes)) == 33
    assert sum(c.publish for c in VPBANK_CARDS.cards) == 12
