"""Tests for core/versioning.py and the database guards behind it."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
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
    VersionStatus,
)
from core.models import (
    CardProduct,
    CardReward,
    CardTerms,
    ChangeEvent,
    Institution,
    SavingsRate,
    Snapshot,
    Source,
)
from core.versioning import (
    SYSTEM_REVIEWER,
    VersioningError,
    approve_version,
    current_select,
    get_current,
    get_pending,
    propose_version,
    reject_version,
    value_columns,
)

pytestmark = pytest.mark.db

HTML = ExtractionMethod.HTML
HOUR = dt.timedelta(hours=1)


# --------------------------------------------------------------------------- fixtures


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
def source(db: Session, bank: Institution) -> Source:
    src = Source(
        institution_id=bank.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        url="https://vidu.example/lai-suat",
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name="vidu",
    )
    db.add(src)
    db.flush()
    return src


@pytest.fixture
def snap(db: Session, source: Source, t0: dt.datetime) -> Snapshot:
    return make_snapshot(db, source, t0)


def make_snapshot(db: Session, source: Source, at: dt.datetime) -> Snapshot:
    s = Snapshot(
        source_id=source.id,
        url=source.url,
        fetched_at=at,
        http_status=200,
        content_type="text/html",
        sha256=f"{int(at.timestamp()):064x}",
        storage_key=f"vidu/{at.isoformat()}.html",
        size_bytes=1024,
    )
    db.add(s)
    db.flush()
    return s


def rate(bank: Institution, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "institution_id": bank.id,
        "region": "",
        "product_name": "Tiết kiệm Online",
        "channel": Channel.ONLINE,
        "term_months": 12,
        "term_days": 0,
        "min_amount_vnd": 0,
        "interest_payment": InterestPayment.END,
        "rate_pct": Decimal("5.90"),
        "conditions_text": None,
        "is_cd": False,
    }
    data.update(overrides)
    return data


def key_of(data: dict[str, Any]) -> dict[str, Any]:
    return {k: data[k] for k in SavingsRate.__version_key__}


def propose(db: Session, data: dict[str, Any], snap: Snapshot, at: dt.datetime) -> Any:
    return propose_version(
        db, SavingsRate, data, snapshot_id=snap.id, extraction_method=HTML, now=at
    )


def count(db: Session, model: Any) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- propose


def test_first_proposal_is_pending_and_not_live(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    data = rate(bank)
    result = propose(db, data, snap, t0)

    assert result.outcome == "proposed"
    assert result.version.status == VersionStatus.PENDING
    assert result.version.snapshot_id == snap.id
    assert get_current(db, SavingsRate, **key_of(data)) is None
    assert get_pending(db, SavingsRate, **key_of(data)) is result.version

    events = db.scalars(select(ChangeEvent).order_by(ChangeEvent.field)).all()
    # Every non-null value is a change from "nothing"; conditions_text stays None.
    assert {e.field for e in events} == {"is_cd", "rate_pct"}
    assert all(e.old_value is None and e.entity == "savings_rate" for e in events)
    assert next(e for e in events if e.field == "rate_pct").new_value == "5.90"


def test_approve_makes_version_live(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    data = rate(bank)
    pending = propose(db, data, snap, t0).version

    approved = approve_version(db, SavingsRate, pending.id, reviewer="lan", now=t0 + HOUR)

    assert approved.status == VersionStatus.APPROVED
    assert approved.reviewer == "lan"
    assert approved.valid_from == approved.decided_at == t0 + HOUR
    assert approved.valid_to is None
    assert get_current(db, SavingsRate, **key_of(data)) is approved
    assert db.scalars(current_select(SavingsRate)).all() == [approved]


def test_unchanged_values_pass_automatically(
    db: Session, bank: Institution, source: Source, snap: Snapshot, t0: dt.datetime
) -> None:
    data = rate(bank)
    live = propose(db, data, snap, t0).version
    approve_version(db, SavingsRate, live.id, reviewer="lan", now=t0 + HOUR)
    events_before = count(db, ChangeEvent)

    later = make_snapshot(db, source, t0 + 24 * HOUR)
    # Same rate written differently (5.9 vs 5.90) is still the same value.
    result = propose(db, rate(bank, rate_pct=Decimal("5.9")), later, t0 + 24 * HOUR)

    assert result.outcome == "unchanged"
    assert result.version is live
    assert live.last_seen_snapshot_id == later.id
    assert live.last_seen_at == t0 + 24 * HOUR
    assert count(db, SavingsRate) == 1
    assert count(db, ChangeEvent) == events_before


def test_change_needs_approval_and_keeps_history(
    db: Session, bank: Institution, source: Source, snap: Snapshot, t0: dt.datetime
) -> None:
    old = propose(db, rate(bank), snap, t0).version
    approve_version(db, SavingsRate, old.id, reviewer="lan", now=t0 + HOUR)

    later = make_snapshot(db, source, t0 + 24 * HOUR)
    data = rate(bank, rate_pct=Decimal("6.10"))
    new = propose(db, data, later, t0 + 24 * HOUR).version

    # Until approved, the old value is still the live one.
    assert get_current(db, SavingsRate, **key_of(data)) is old

    events = db.scalars(select(ChangeEvent).where(ChangeEvent.entity_id == new.id)).all()
    assert [(e.field, e.old_value, e.new_value) for e in events] == [("rate_pct", "5.900", "6.10")]

    approve_version(db, SavingsRate, new.id, reviewer="minh", now=t0 + 25 * HOUR)

    assert get_current(db, SavingsRate, **key_of(data)) is new
    assert old.valid_to == t0 + 25 * HOUR
    assert old.status == VersionStatus.APPROVED  # history: it was approved, now closed
    assert old.rate_pct == Decimal("5.90")  # never overwritten
    assert count(db, SavingsRate) == 2


def test_same_proposal_twice_keeps_one_pending(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    first = propose(db, rate(bank), snap, t0)
    second = propose(db, rate(bank), snap, t0 + HOUR)

    assert second.outcome == "already_pending"
    assert second.version is first.version
    assert count(db, SavingsRate) == 1


def test_newer_proposal_supersedes_unreviewed_one(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    first = propose(db, rate(bank), snap, t0).version
    second = propose(db, rate(bank, rate_pct=Decimal("6.00")), snap, t0 + HOUR)

    assert second.outcome == "proposed"
    assert second.superseded is first
    assert first.status == VersionStatus.SUPERSEDED
    assert first.reviewer == SYSTEM_REVIEWER
    assert get_pending(db, SavingsRate, **key_of(rate(bank))) is second.version


def test_reverting_to_live_value_drops_stale_proposal(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    live = propose(db, rate(bank), snap, t0).version
    approve_version(db, SavingsRate, live.id, reviewer="lan", now=t0 + HOUR)
    stale = propose(db, rate(bank, rate_pct=Decimal("6.00")), snap, t0 + 2 * HOUR).version

    result = propose(db, rate(bank), snap, t0 + 3 * HOUR)

    assert result.outcome == "unchanged"
    assert result.superseded is stale
    assert stale.status == VersionStatus.SUPERSEDED
    assert get_pending(db, SavingsRate, **key_of(rate(bank))) is None


def test_different_tiers_are_separate_series(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    low = propose(db, rate(bank), snap, t0).version
    high = propose(db, rate(bank, min_amount_vnd=1_000_000_000), snap, t0).version
    approve_version(db, SavingsRate, low.id, reviewer="lan", now=t0 + HOUR)
    approve_version(db, SavingsRate, high.id, reviewer="lan", now=t0 + HOUR)

    assert len(db.scalars(current_select(SavingsRate)).all()) == 2


# --------------------------------------------------------------------------- reject


def test_reject_leaves_live_value_alone(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    live = propose(db, rate(bank), snap, t0).version
    approve_version(db, SavingsRate, live.id, reviewer="lan", now=t0 + HOUR)
    bad = propose(db, rate(bank, rate_pct=Decimal("59.0")), snap, t0 + 2 * HOUR).version

    reject_version(db, SavingsRate, bad.id, reviewer="lan", now=t0 + 3 * HOUR)

    assert bad.status == VersionStatus.REJECTED
    assert bad.decided_at == t0 + 3 * HOUR
    assert get_current(db, SavingsRate, **key_of(rate(bank))) is live
    assert live.valid_to is None


def test_decided_versions_cannot_be_decided_again(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    v = propose(db, rate(bank), snap, t0).version
    reject_version(db, SavingsRate, v.id, reviewer="lan", now=t0 + HOUR)

    with pytest.raises(VersioningError, match="rejected, not pending"):
        approve_version(db, SavingsRate, v.id, reviewer="lan")
    with pytest.raises(VersioningError, match="rejected, not pending"):
        reject_version(db, SavingsRate, v.id, reviewer="lan")
    with pytest.raises(VersioningError, match="does not exist"):
        approve_version(db, SavingsRate, 999_999, reviewer="lan")


@pytest.mark.parametrize("reviewer", ["", "   ", SYSTEM_REVIEWER])
def test_approval_needs_a_named_human(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime, reviewer: str
) -> None:
    v = propose(db, rate(bank), snap, t0).version
    with pytest.raises(VersioningError, match="human reviewer"):
        approve_version(db, SavingsRate, v.id, reviewer=reviewer)
    assert v.status == VersionStatus.PENDING


# --------------------------------------------------------------------------- input checks


def test_partial_data_is_rejected(db: Session, bank: Institution, snap: Snapshot) -> None:
    data = rate(bank)
    del data["conditions_text"]
    with pytest.raises(VersioningError, match=r"missing fields \['conditions_text'\]"):
        propose(db, data, snap, dt.datetime.now(dt.UTC))
    assert count(db, SavingsRate) == 0


def test_unknown_field_is_rejected(db: Session, bank: Institution, snap: Snapshot) -> None:
    with pytest.raises(VersioningError, match=r"unknown fields \['bonus_pct'\]"):
        propose(db, rate(bank, bonus_pct=Decimal("0.5")), snap, dt.datetime.now(dt.UTC))


def test_float_is_rejected(db: Session, bank: Institution, snap: Snapshot) -> None:
    with pytest.raises(VersioningError, match="not float"):
        propose(db, rate(bank, rate_pct=5.9), snap, dt.datetime.now(dt.UTC))


def test_naive_datetime_is_rejected(db: Session, bank: Institution, snap: Snapshot) -> None:
    with pytest.raises(VersioningError, match="timezone-aware"):
        propose(db, rate(bank), snap, dt.datetime(2026, 1, 1))  # noqa: DTZ001


def test_key_lookup_must_be_complete(db: Session) -> None:
    with pytest.raises(VersioningError, match="key must be exactly"):
        get_current(db, SavingsRate, institution_id=1)


def test_value_columns_exclude_key_and_metadata() -> None:
    assert value_columns(SavingsRate) == ("rate_pct", "conditions_text", "is_cd")


# --------------------------------------------------------------------------- other tables


def test_card_tables_use_the_same_helpers(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    card = CardProduct(
        institution_id=bank.id,
        name="Ví Dụ Platinum",
        network=CardNetwork.VISA,
        card_type=CardType.CREDIT,
    )
    db.add(card)
    db.flush()
    terms = {
        "card_product_id": card.id,
        "annual_fee_primary_vnd": 999_000,
        "annual_fee_supp_vnd": 499_000,
        "fee_waiver_rule_text": "Chi tiêu 100 triệu/năm",
        "fee_waiver_spend_vnd": 100_000_000,
        "interest_rate_pct": Decimal("28.0"),
        "interest_free_days": 55,
        "cash_advance_pct": Decimal("4.0"),
        "cash_advance_min_vnd": 100_000,
        "fx_fee_pct": Decimal("3.5"),
        "late_fee_pct": Decimal("6.0"),
        "late_fee_min_vnd": 200_000,
        "min_monthly_income_vnd": 10_000_000,
    }
    v = propose_version(db, CardTerms, terms, snapshot_id=snap.id, extraction_method=HTML).version
    approve_version(db, CardTerms, v.id, reviewer="lan", now=t0)
    assert get_current(db, CardTerms, card_product_id=card.id) is v

    reward = {
        "card_product_id": card.id,
        "category": RewardCategory.DINING,
        "reward_type": RewardType.POINTS,
        "rate_pct": None,
        "points_per_spend": Decimal("1"),
        "spend_unit_vnd": 20_000,
        "monthly_cap_vnd": None,
        "conditions_text": None,
    }
    r = propose_version(db, CardReward, reward, snapshot_id=snap.id, extraction_method=HTML)
    assert r.outcome == "proposed"


def test_cashback_reward_needs_a_rate(db: Session, bank: Institution, snap: Snapshot) -> None:
    card = CardProduct(
        institution_id=bank.id,
        name="Ví Dụ Cashback",
        network=CardNetwork.MASTERCARD,
        card_type=CardType.CREDIT,
    )
    db.add(card)
    db.flush()
    reward = {
        "card_product_id": card.id,
        "category": RewardCategory.ALL,
        "reward_type": RewardType.CASHBACK,
        "rate_pct": None,
        "points_per_spend": None,
        "spend_unit_vnd": None,
        "monthly_cap_vnd": 600_000,
        "conditions_text": None,
    }
    with pytest.raises(IntegrityError, match="earn_rate_present"):
        propose_version(db, CardReward, reward, snapshot_id=snap.id, extraction_method=HTML)


# --------------------------------------------------------------------------- DB guards
# These bypass the helpers on purpose: the database must refuse on its own.


def approved_rate(db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime) -> SavingsRate:
    v = propose(db, rate(bank), snap, t0).version
    return approve_version(db, SavingsRate, v.id, reviewer="lan", now=t0 + HOUR)


def test_db_refuses_to_overwrite_a_value(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    v = approved_rate(db, bank, snap, t0)
    with pytest.raises(DBAPIError, match="values are immutable"), db.begin_nested():
        db.execute(
            update(SavingsRate).where(SavingsRate.id == v.id).values(rate_pct=Decimal("9.99"))
        )


def test_db_refuses_to_delete_a_version(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    v = approved_rate(db, bank, snap, t0)
    with pytest.raises(DBAPIError, match="never deleted"), db.begin_nested():
        db.delete(v)
        db.flush()


def test_db_refuses_to_reopen_a_decision(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    v = approved_rate(db, bank, snap, t0)
    with pytest.raises(DBAPIError, match="already decided"), db.begin_nested():
        db.execute(
            update(SavingsRate).where(SavingsRate.id == v.id).values(reviewer="someone-else")
        )


def test_db_allows_only_one_live_version_per_key(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    approved_rate(db, bank, snap, t0)
    twin = SavingsRate(
        **rate(bank, rate_pct=Decimal("7.00")),
        snapshot_id=snap.id,
        extraction_method=HTML,
        status=VersionStatus.APPROVED,
        valid_from=t0,
        reviewer="lan",
        decided_at=t0,
    )
    with pytest.raises(IntegrityError, match="uq_savings_rate_current"), db.begin_nested():
        db.add(twin)
        db.flush()


def test_db_refuses_approved_row_without_reviewer(
    db: Session, bank: Institution, snap: Snapshot, t0: dt.datetime
) -> None:
    row = SavingsRate(
        **rate(bank),
        snapshot_id=snap.id,
        extraction_method=HTML,
        status=VersionStatus.APPROVED,
        valid_from=t0,
        decided_at=t0,
    )
    with pytest.raises(IntegrityError, match="ck_savings_rate_lifecycle"), db.begin_nested():
        db.add(row)
        db.flush()


def test_snapshots_are_append_only(db: Session, snap: Snapshot) -> None:
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(update(Snapshot).where(Snapshot.id == snap.id).values(size_bytes=1))
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.delete(snap)
        db.flush()
