"""A small, realistic history in the test DB, built through core/versioning.

VIDU (bank, source checked recently)
  savings 12 months, counter, end:  6.00% approved 2026-09-01, 6.20% approved 2026-10-20
  savings 12 months, online, monthly: 5.80% approved 2026-10-20, re-seen 2026-10-27
  savings  6 months, counter, end:  5.00% approved 2026-10-20
  savings 12 months, app, end:      9.90% PENDING (must never appear)
  card "Ví Dụ Visa": terms + dining cashback + perks, approved 2026-10-21 (LLM, evidence)
CU (bank whose only source is stale)
  savings 12 months, counter, end:  6.10% approved 2026-10-20
"""

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from api.app import create_app
from api.reports import Captcha, NoCaptcha
from core.config import Settings
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
from core.versioning import approve_version, propose_version
from pipeline.fetch.storage import MemoryStore

SEP_1 = dt.datetime(2026, 9, 1, 3, 0, tzinfo=dt.UTC)
OCT_20 = dt.datetime(2026, 10, 20, 3, 0, tzinfo=dt.UTC)
OCT_21 = dt.datetime(2026, 10, 21, 3, 0, tzinfo=dt.UTC)
OCT_27 = dt.datetime(2026, 10, 27, 3, 0, tzinfo=dt.UTC)
RATES_URL = "https://vidu.example/lai-suat"
CARDS_URL = "https://vidu.example/bieu-phi-the.pdf"


@dataclass
class World:
    vidu: Institution
    cu: Institution
    old_12m: int  # 6.00%, replaced
    live_12m: int  # 6.20%
    monthly_12m: int
    live_6m: int
    pending_12m: int
    cu_12m: int
    card: CardProduct
    terms: int


def _snapshot(db: Session, source: Source, url: str, at: dt.datetime, n: int) -> Snapshot:
    s = Snapshot(
        source_id=source.id,
        url=url,
        fetched_at=at,
        http_status=200,
        content_type="text/html",
        sha256=f"{n:064x}",
        storage_key=f"x/{n}",
        size_bytes=1,
    )
    db.add(s)
    db.flush()
    return s


def _put(
    db: Session,
    model: type[Versioned],
    data: dict[str, Any],
    snap: Snapshot,
    at: dt.datetime | None,
    method: ExtractionMethod = ExtractionMethod.HTML,
    **kw: Any,
) -> int:
    version = propose_version(
        db, model, data, snapshot_id=snap.id, extraction_method=method, now=at, **kw
    ).version
    if at is not None:
        approve_version(db, model, version.id, reviewer="tester", now=at)
    return version.id


def _rate(inst: Institution, **kw: Any) -> dict[str, Any]:
    data = {
        "institution_id": inst.id,
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
def world(db: Session) -> World:
    now = dt.datetime.now(dt.UTC)
    vidu = Institution(
        legal_name_vi="Ngân hàng TMCP Ví Dụ",
        short_name="VIDU",
        type=InstitutionType.JOINT_STOCK_BANK,
        website="https://vidu.example",
        deposit_insurance=True,
    )
    cu = Institution(
        legal_name_vi="Ngân hàng TMCP Cũ",
        short_name="CU",
        type=InstitutionType.JOINT_STOCK_BANK,
        deposit_insurance=True,
    )
    db.add_all([vidu, cu])
    db.flush()
    fresh = Source(
        institution_id=vidu.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        url=RATES_URL,
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name="vidu",
        last_success_at=now,
    )
    stale = Source(
        institution_id=cu.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        url="https://cu.example/lai-suat",
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name="cu",
        last_success_at=now - dt.timedelta(days=10),
    )
    db.add_all([fresh, stale])
    db.flush()
    s1 = _snapshot(db, fresh, RATES_URL, SEP_1, 1)
    s2 = _snapshot(db, fresh, RATES_URL, OCT_20, 2)
    s3 = _snapshot(db, fresh, RATES_URL, OCT_27, 3)
    s_cu = _snapshot(db, stale, "https://cu.example/lai-suat", OCT_20, 4)
    s_card = _snapshot(db, fresh, CARDS_URL, OCT_21, 5)

    old = _put(db, SavingsRate, _rate(vidu), s1, SEP_1, effective_from=dt.date(2026, 9, 1))
    live = _put(
        db,
        SavingsRate,
        _rate(vidu, rate_pct=Decimal("6.20")),
        s2,
        OCT_20,
        effective_from=dt.date(2026, 10, 18),
    )
    monthly_data = _rate(
        vidu,
        channel=Channel.ONLINE,
        interest_payment=InterestPayment.MONTHLY,
        rate_pct=Decimal("5.80"),
        conditions_text="Mức lãi suất tối đa",
    )
    monthly = _put(db, SavingsRate, monthly_data, s2, OCT_20)
    # a later fetch saw the same value: checked_at moves, no new version
    propose_version(
        db,
        SavingsRate,
        monthly_data,
        snapshot_id=s3.id,
        extraction_method=ExtractionMethod.HTML,
        now=OCT_27,
    )
    six = _put(db, SavingsRate, _rate(vidu, term_months=6, rate_pct=Decimal("5.00")), s2, OCT_20)
    pending = _put(
        db, SavingsRate, _rate(vidu, channel=Channel.APP, rate_pct=Decimal("9.90")), s3, None
    )
    cu_rate = _put(db, SavingsRate, _rate(cu, rate_pct=Decimal("6.10")), s_cu, OCT_20)

    card = CardProduct(
        institution_id=vidu.id,
        name="Ví Dụ Visa",
        network=CardNetwork.VISA,
        card_type=CardType.CREDIT,
        tier="gold",
    )
    db.add(card)
    db.flush()
    evidence = {
        "annual_fee_primary_vnd": {
            "page": 1,
            "quote": "Ví Dụ Visa | 500.000 VND",
            "value": "500.000 VND",
        }
    }
    terms = _put(
        db,
        CardTerms,
        {
            "card_product_id": card.id,
            "annual_fee_primary_vnd": 500_000,
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
        },
        s_card,
        OCT_21,
        ExtractionMethod.LLM,
        evidence=evidence,
    )
    _put(
        db,
        CardReward,
        {
            "card_product_id": card.id,
            "category": RewardCategory.DINING,
            "reward_type": RewardType.CASHBACK,
            "rate_pct": Decimal("5"),
            "points_per_spend": None,
            "spend_unit_vnd": None,
            "monthly_cap_vnd": 100_000,
            "conditions_text": None,
        },
        s_card,
        OCT_21,
        ExtractionMethod.LLM,
    )
    _put(
        db,
        CardPerk,
        {
            "card_product_id": card.id,
            "lounge_visits_per_year": 2,
            "lounge_unlimited": False,
            "travel_insurance": True,
            "travel_insurance_cover_vnd": None,
            "other_perks_text": "Golf",
        },
        s_card,
        OCT_21,
        ExtractionMethod.LLM,
    )
    db.commit()  # visible to the app's own sessions (still inside the test transaction)
    return World(vidu, cu, old, live, monthly, six, pending, cu_rate, card, terms)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def make_client(
    db: Session, store: MemoryStore, clock: Clock, captcha: Captcha | None = None, **settings: Any
) -> TestClient:
    conn = db.connection()
    assert isinstance(conn, Connection)
    app = create_app(
        lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        settings=Settings(**{"report_rate_limit_per_hour": 3, **settings}),
        store=store,
        captcha=captcha or NoCaptcha(),
        clock=clock,
    )
    return TestClient(app)


@pytest.fixture
def client(db: Session, store: MemoryStore, clock: Clock) -> Iterator[TestClient]:
    with make_client(db, store, clock) as c:
        yield c
