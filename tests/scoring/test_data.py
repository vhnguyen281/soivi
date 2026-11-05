"""Scoring loaders use only approved, live values."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from core.enums import (
    CardNetwork,
    CardType,
    Channel,
    ExtractionMethod,
    FetchMethod,
    InstitutionType,
    InterestPayment,
    RewardCategory,
    RewardType,
    SourceKind,
)
from core.models import (
    CardInterest,
    CardPerk,
    CardProduct,
    CardReward,
    CardTerms,
    Institution,
    SavingsRate,
    Snapshot,
    Source,
    Versioned,
)
from core.scoring.data import card_offers, savings_offers
from core.versioning import approve_version, propose_version

pytestmark = pytest.mark.db
NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
def bank(db: Session) -> Institution:
    inst = Institution(
        legal_name_vi="Ngân hàng TMCP Ví Dụ",
        short_name="VIDU",
        type=InstitutionType.JOINT_STOCK_BANK,
        deposit_insurance=True,
    )
    db.add(inst)
    db.flush()
    return inst


@pytest.fixture
def snap(db: Session, bank: Institution) -> Snapshot:
    source = Source(
        institution_id=bank.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        url="https://vidu.example/lai-suat",
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name="vidu",
        last_success_at=NOW,
    )
    db.add(source)
    db.flush()
    s = Snapshot(
        source_id=source.id,
        url=source.url or "",
        fetched_at=NOW,
        http_status=200,
        content_type="text/html",
        sha256="a" * 64,
        storage_key="vidu/x.html",
        size_bytes=1,
    )
    db.add(s)
    db.flush()
    return s


def put(
    db: Session, snap: Snapshot, model: type[Versioned], data: dict[str, Any], approve: bool = True
) -> int:
    version = propose_version(
        db, model, data, snapshot_id=snap.id, extraction_method=ExtractionMethod.HTML
    ).version
    if approve:
        approve_version(db, model, version.id, reviewer="tester")
    return version.id


def rate(bank: Institution, **kw: Any) -> dict[str, Any]:
    data = {
        "institution_id": bank.id,
        "region": "",
        "product_name": "Tiết kiệm thường",
        "channel": Channel.COUNTER,
        "term_months": 12,
        "term_days": 0,
        "min_amount_vnd": 0,
        "interest_payment": InterestPayment.END,
        "rate_pct": Decimal("6.00"),
        "conditions_text": None,
        "is_cd": False,
    }
    data.update(kw)
    return data


@pytest.fixture
def rates(db: Session, bank: Institution, snap: Snapshot) -> None:
    put(db, snap, SavingsRate, rate(bank))
    put(
        db,
        snap,
        SavingsRate,
        rate(
            bank,
            interest_payment=InterestPayment.MONTHLY,
            rate_pct=Decimal("5.80"),
            conditions_text="Mức lãi suất tối đa",
        ),
    )
    put(
        db,
        snap,
        SavingsRate,
        rate(bank, channel=Channel.ONLINE, rate_pct=Decimal("9.00")),
        approve=False,
    )  # pending: never ranked
    put(db, snap, SavingsRate, rate(bank, term_months=6, rate_pct=Decimal("5.00")))


@pytest.fixture
def cards(db: Session, bank: Institution, snap: Snapshot) -> None:
    approved = CardProduct(
        institution_id=bank.id,
        name="Ví Dụ Visa",
        network=CardNetwork.VISA,
        card_type=CardType.CREDIT,
    )
    pending = CardProduct(
        institution_id=bank.id,
        name="Ví Dụ Mới",
        network=CardNetwork.VISA,
        card_type=CardType.CREDIT,
    )
    db.add_all([approved, pending])
    db.flush()
    terms = {
        "annual_fee_supp_vnd": None,
        "fee_waiver_rule_text": None,
        "fee_waiver_spend_vnd": 100_000_000,
        "interest_rate_pct": None,
        "interest_free_days": 45,
        "cash_advance_pct": Decimal("4"),
        "cash_advance_min_vnd": 100_000,
        "fx_fee_pct": Decimal("2.5"),
        "late_fee_pct": None,
        "late_fee_min_vnd": None,
        "min_monthly_income_vnd": 8_000_000,
    }
    put(
        db,
        snap,
        CardTerms,
        {"card_product_id": approved.id, "annual_fee_primary_vnd": 500_000, **terms},
    )
    put(
        db,
        snap,
        CardTerms,
        {"card_product_id": pending.id, "annual_fee_primary_vnd": 0, **terms},
        approve=False,
    )
    put(
        db,
        snap,
        CardReward,
        {
            "card_product_id": approved.id,
            "category": RewardCategory.DINING,
            "reward_type": RewardType.CASHBACK,
            "rate_pct": Decimal("5"),
            "points_per_spend": None,
            "spend_unit_vnd": None,
            "monthly_cap_vnd": 100_000,
            "conditions_text": None,
        },
    )
    put(
        db,
        snap,
        CardPerk,
        {
            "card_product_id": approved.id,
            "lounge_visits_per_year": 2,
            "lounge_unlimited": False,
            "travel_insurance": True,
            "travel_insurance_cover_vnd": None,
            "other_perks_text": "Golf",
        },
    )


# --------------------------------------------------------------------------- loaders


def test_savings_loader_uses_approved_current_rates_only(db: Session, rates: None) -> None:
    offers = savings_offers(db, 12)
    assert sorted((o.channel.value, o.interest_payment.value, o.rate_pct) for o in offers) == [
        ("counter", "end", Decimal("6.000")),
        ("counter", "monthly", Decimal("5.800")),
    ]
    assert all(o.deposit_insurance and o.verified for o in offers)
    assert offers[0].institution == "VIDU"


def test_card_loader(db: Session, cards: None) -> None:
    [offer] = card_offers(db)  # the pending-only card is left out
    assert offer.name == "Ví Dụ Visa" and offer.annual_fee_vnd == 500_000
    assert offer.rewards[0].category is RewardCategory.DINING
    assert offer.travel_insurance and offer.lounge_visits_per_year == 2
    assert offer.interest_rate_pct is None


def test_card_page_interest_is_used(db: Session, cards: None, snap: Snapshot) -> None:
    [offer] = card_offers(db)
    put(
        db,
        snap,
        CardInterest,
        {
            "card_product_id": offer.card_product_id,
            "interest_rate_pct": Decimal("20"),
            "interest_free_days": 45,
        },
    )
    [offer] = card_offers(db)
    assert offer.interest_rate_pct == Decimal("20")  # the fee schedule gave none
