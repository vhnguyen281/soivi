"""Card product pages read one source per card (BIDV, VPBank).

Synthetic model answers here test the rules, quoting the saved pages:
- a card's page only gives facts about its own card(s);
- a cashback rate without a cap is dropped unless the bank says it is unlimited;
- VPBank's details, shipped as page data, reach the model;
- BIDV's promotions list under the details does not.
"""

from typing import Any

import pytest

from core.enums import RewardCategory, RewardType
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.bidv_cards import BIDV_CARD_PAGES, BIDV_CARDS, BidvCardProducts
from pipeline.adapters.techcombank_cards import (
    TECHCOMBANK_CARD_PAGES,
    TECHCOMBANK_CARDS,
    TechcombankCardPages,
)
from pipeline.adapters.vpbank_cards import VPBANK_CARD_PAGES, VPBANK_CARDS, VpbankCardProducts
from pipeline.cards.adapter import LlmCardAdapter
from pipeline.cards.build import Built
from pipeline.cards.document import DocumentError, read_html
from pipeline.cards.llm import CardExtractor
from pipeline.records import CardRewardRecord
from tests.cards.conftest import FIXTURES as TCB
from tests.cards.conftest import FakeClient

FIX = TCB.parent
VPB_Z = FIX / "vpbank" / "card_page_z_2026-10-29.html"
BIDV_CB360 = FIX / "bidv" / "card_page_visa-cashback-360_2026-10-29.html"

Z_DINING = "Hoàn 15% cho giao dịch Ăn uống (*), tối đa 500,000"
Z_HEADLINE = "Hoàn tiền 15% cho mọi chi tiêu"


def run(
    monkeypatch: pytest.MonkeyPatch,
    adapter: type[LlmCardAdapter],
    page: bytes,
    variant: str,
    answer: dict[str, Any],
) -> tuple[Built, FakeClient]:
    client = FakeClient({1: answer})
    seen: list[str] = []

    def extractor(cls: type[LlmCardAdapter], focus: str = "") -> CardExtractor:
        seen.append(focus)
        notes = "\n".join(n for n in (cls.reading_notes, focus) if n)
        return CardExtractor(cls.catalogue, "products", client=client, notes=notes)

    monkeypatch.setattr(adapter, "extractor", classmethod(extractor))
    return adapter.build_from(page, "text/html", variant), client


def reward(card: str, category: str, quote: str, *facts: tuple[str, str]) -> dict[str, Any]:
    return {
        "card": card,
        "category": category,
        "reward_type": "cashback",
        "page": 1,
        "quote": quote,
        "facts": [{"field": f, "value": v, "page": 1, "quote": quote} for f, v in facts],
    }


def test_vpbank_page_data_reaches_the_model() -> None:
    [page] = read_html(VPB_Z.read_bytes())
    assert Z_HEADLINE in page.text  # the visible header
    assert Z_DINING in page.text  # the "Tính năng nổi bật" block, shipped as data
    assert "Lãi suất thẻ tín dụng VPBank Z là 3.99%/tháng." in page.text  # FAQ


def test_bidv_promotions_are_cut_off() -> None:
    [page] = read_html(BIDV_CB360.read_bytes(), until=BidvCardProducts.html_until)
    assert "Tích điểm lên tới 10% giá trị giao dịch chi tiêu tại siêu thị" in page.text
    assert "Koi Thé" not in page.text  # first item of the promotions list
    assert len(page.text) < 5_000
    with pytest.raises(DocumentError, match="layout changed"):
        read_html(BIDV_CB360.read_bytes(), until="NO SUCH MARKER")


def test_capped_reward_kept_headline_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {
        "cards": [],
        "unlisted_cards": ["Some Other Card"],
        "rewards": [
            reward(
                "VPB_Z", "dining", Z_DINING, ("rate_pct", "15%"), ("monthly_cap_vnd", "500,000")
            ),
            reward("VPB_Z", "all", Z_HEADLINE, ("rate_pct", "15%")),  # no cap: a headline
        ],
    }
    built, client = run(monkeypatch, VpbankCardProducts, VPB_Z.read_bytes(), "z", answer)
    [dining] = [r for r in built.records if isinstance(r, CardRewardRecord)]
    assert (dining.card_name, dining.category, dining.reward_type) == (
        "VPBank Z JCB",
        RewardCategory.DINING,
        RewardType.CASHBACK,
    )
    assert dining.monthly_cap_vnd == 500_000
    assert [n.rule for n in built.notes] == ["dropped_no_cap"]
    system = client.requests[0]["system"][0]["text"]
    assert "This is the product page of VPBank Z JCB" in system
    assert "A headline or summary" in system


def test_unlimited_cashback_needs_the_word(monkeypatch: pytest.MonkeyPatch) -> None:
    # same page, a quote that says "không giới hạn": invented page text for this rule
    page = VPB_Z.read_bytes().replace(
        "Hoàn tiền 15% cho mọi chi tiêu".encode(),
        "Hoàn tiền 15% cho mọi chi tiêu, không giới hạn".encode(),
        1,
    )
    quote = "Hoàn tiền 15% cho mọi chi tiêu, không giới hạn"
    answer = {"cards": [], "rewards": [reward("VPB_Z", "all", quote, ("rate_pct", "15%"))]}
    built, _ = run(monkeypatch, VpbankCardProducts, page, "z", answer)
    [r] = built.records
    assert isinstance(r, CardRewardRecord) and r.monthly_cap_vnd is None


def test_other_cards_on_a_card_page_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {
        "cards": [],
        "rewards": [
            reward(
                "VPB_MWG", "dining", Z_DINING, ("rate_pct", "15%"), ("monthly_cap_vnd", "500,000")
            )
        ],
    }
    built, _ = run(monkeypatch, VpbankCardProducts, VPB_Z.read_bytes(), "z", answer)
    assert built.records == []
    assert [(n.rule, n.key["card"]) for n in built.notes] == [
        ("other_card_on_page", "VPBank MWG Mastercard"),
        ("nothing_stored", "VPBank Z JCB"),  # an empty card page doesn't raise
    ]


def test_unmapped_page_raises() -> None:
    with pytest.raises(AdapterBroken, match="no card is mapped"):
        VpbankCardProducts.build_from(VPB_Z.read_bytes(), "text/html", "no-such-page")


@pytest.mark.parametrize(
    ("pages", "catalogue"),
    [
        (BIDV_CARD_PAGES, BIDV_CARDS),
        (VPBANK_CARD_PAGES, VPBANK_CARDS),
        (TECHCOMBANK_CARD_PAGES, TECHCOMBANK_CARDS),
    ],
)
def test_pages_name_published_cards(pages: dict[str, tuple[str, ...]], catalogue: Any) -> None:
    codes = [c for cs in pages.values() for c in cs]
    assert len(codes) == len(set(codes))  # one page per card
    assert all(catalogue.get(c).publish for c in codes)
    assert all(len(v) <= 32 for v in pages)  # source.variant is VARCHAR(32)


def test_every_page_has_a_seed_row() -> None:
    import csv

    from tests.cards.conftest import FIXTURES

    seeds = FIXTURES.parents[2] / "data" / "seeds" / "sources.csv"
    with seeds.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["kind"] == "card_product_page"]
    banks = (
        ("BIDV", BidvCardProducts),
        ("VPBANK", VpbankCardProducts),
        ("TECHCOMBANK", TechcombankCardPages),
    )
    for bank, adapter in banks:
        seeded = {r["variant"] for r in rows if r["institution"] == bank and r["adapter"]}
        assert seeded == set(adapter.card_pages), bank
        assert {r["adapter"] for r in rows if r["institution"] == bank and r["variant"]} == {
            adapter.name
        }


# ------------------------------------------------- real model answers (2026-10-30)


def recorded(
    monkeypatch: pytest.MonkeyPatch, adapter: type[LlmCardAdapter], bank: str, variant: str
) -> Built:
    import json

    page = FIX / bank / f"card_page_{variant}_2026-10-29.html"
    saved = json.loads(
        (FIX / bank / f"card_page_{variant}_llm_answers.json").read_text(encoding="utf-8")
    )
    [answer] = saved
    answer.pop("page")
    built, _ = run(monkeypatch, adapter, page.read_bytes(), variant, answer)
    return built


def rewards_of(built: Built) -> dict[tuple[str, str], CardRewardRecord]:
    return {
        (r.category.value, r.reward_type.value): r
        for r in built.records
        if isinstance(r, CardRewardRecord)
    }


def test_vpbank_z_only_the_capped_category(monkeypatch: pytest.MonkeyPatch) -> None:
    built = recorded(monkeypatch, VpbankCardProducts, "vpbank", "z")
    [(key, dining)] = rewards_of(built).items()
    assert key == ("dining", "cashback")
    assert (str(dining.rate_pct), dining.monthly_cap_vnd) == ("15", 500_000)


def test_vpbank_unionpay_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    got = {
        k: (str(r.rate_pct), r.monthly_cap_vnd)
        for k, r in rewards_of(
            recorded(monkeypatch, VpbankCardProducts, "vpbank", "unionpay")
        ).items()
    }
    assert got == {
        ("overseas", "cashback"): ("4", 500_000),
        ("dining", "cashback"): ("3", 500_000),
        ("travel", "cashback"): ("3", 500_000),
        ("other", "cashback"): ("0.1", 500_000),
    }


def test_bidv_tiered_reward_is_text_not_a_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    built = recorded(monkeypatch, BidvCardProducts, "bidv", "jcb-ultimate")
    assert rewards_of(built) == {}  # 10%/800k from 10M a month, 5%/300k below: tiers
    [perk] = [r for r in built.records if not isinstance(r, CardRewardRecord)]
    assert "dưới 10 triệu đồng/tháng, hoàn tối đa 300.000" in (perk.other_perks_text or "")


def test_bidv_points_stay_out_insurance_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    built = recorded(monkeypatch, BidvCardProducts, "bidv", "visa-cashback-360")
    assert rewards_of(built) == {}  # "Tích điểm lên tới 10%": points as a % of spend
    [perk] = built.records
    assert perk.travel_insurance is True  # "bảo hiểm du lịch toàn cầu"


def test_interest_from_a_card_page(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.records import CardInterestRecord

    quote = "Lãi suất: 20%/năm, miễn lãi tối đa 45 ngày"
    fact = {"page": 1, "quote": quote}
    answer = {
        "cards": [
            {
                "card": "BIDV_VISA_CASHBACK_360",
                "facts": [
                    {"field": "interest_rate_pct", "value": "20%", **fact},
                    {"field": "interest_free_days", "value": "45 ngày", **fact},
                ],
            }
        ],
        "rewards": [],
    }
    built, client = run(
        monkeypatch, BidvCardProducts, BIDV_CB360.read_bytes(), "visa-cashback-360", answer
    )
    [interest] = built.records
    assert isinstance(interest, CardInterestRecord)
    assert (str(interest.interest_rate_pct), interest.interest_free_days) == ("20", 45)
    assert "interest_rate_pct" in client.requests[0]["system"][0]["text"]


def test_approved_text_is_kept_while_the_page_still_says_it() -> None:
    from types import SimpleNamespace

    from core.enums import CardNetwork
    from pipeline.cards.build import keep_approved_text
    from pipeline.records import CardPerkRecord

    page = {1: "Tặng 10 lượt chơi Golf miễn phí\nBảo hiểm cho chủ thẻ giá trị tới 26,4 tỷ VND"}
    golf = {"page": 1, "quote": "Tặng 10 lượt chơi Golf miễn phí"}
    cover = {"page": 1, "quote": "Bảo hiểm cho chủ thẻ giá trị tới 26,4 tỷ VND"}
    approved = SimpleNamespace(
        other_perks_text=f"{golf['quote']}; {cover['quote']}",
        source_evidence={"other_perks_text": {**golf, "also": [cover]}},
    )
    # a fresh read picks only one of the sentences: the approved text still holds
    reread = CardPerkRecord(
        card_name="BIDV Visa Infinite",
        network=CardNetwork.VISA,
        other_perks_text="Tặng 10 lượt chơi Golf miễn phí",
        evidence={"other_perks_text": golf},
    )
    kept = keep_approved_text(reread, approved, page)
    assert isinstance(kept, CardPerkRecord)
    assert kept.other_perks_text == approved.other_perks_text
    assert kept.evidence is not None and kept.evidence["other_perks_text"]["also"] == [cover]
    # the bank removed the insurance sentence: the change goes to review
    changed = keep_approved_text(reread, approved, {1: "Tặng 10 lượt chơi Golf miễn phí"})
    assert isinstance(changed, CardPerkRecord)
    assert changed.other_perks_text == "Tặng 10 lượt chơi Golf miễn phí"
