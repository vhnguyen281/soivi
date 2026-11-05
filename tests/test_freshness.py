"""core/freshness: an institution's data is unverified when a monitored source is stale."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from core.enums import FetchMethod, InstitutionType, SourceKind
from core.freshness import StalenessPolicy, institution_freshness, source_staleness
from core.models import Institution, Source

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.UTC)
POLICY = StalenessPolicy(max_consecutive_failures=2, max_age_cadence_multiple=Decimal(2))


def bank(db: Session, short: str) -> Institution:
    inst = Institution(
        legal_name_vi=f"Ngân hàng {short}", short_name=short, type=InstitutionType.JOINT_STOCK_BANK
    )
    db.add(inst)
    db.flush()
    return inst


def source(db: Session, inst: Institution, variant: str = "", **kw: object) -> Source:
    values: dict[str, object] = {
        "institution_id": inst.id,
        "kind": SourceKind.SAVINGS_RATE_PAGE,
        "variant": variant,
        "url": f"https://{inst.short_name.lower()}.example/{variant or 'rates'}",
        "fetch_method": FetchMethod.HTTP,
        "cadence_hours": 12,
        "adapter_name": "x",
        "last_success_at": NOW - dt.timedelta(hours=1),
    }
    values.update(kw)
    src = Source(**values)
    db.add(src)
    db.flush()
    return src


@pytest.mark.parametrize(
    ("failures", "age_hours", "stale"),
    [
        (0, 1, False),
        (1, 1, False),
        (2, 1, True),  # consecutive_failures >= 2
        (0, 24, False),  # exactly 2 x 12 h: not older than the limit
        (0, 25, True),  # older than 2 x cadence
    ],
)
def test_source_staleness(db: Session, failures: int, age_hours: int, stale: bool) -> None:
    s = source(
        db,
        bank(db, "A"),
        consecutive_failures=failures,
        last_success_at=NOW - dt.timedelta(hours=age_hours),
    )
    assert bool(source_staleness(s, NOW, POLICY)) == stale


def test_never_fetched_is_stale(db: Session) -> None:
    s = source(db, bank(db, "A"), last_success_at=None)
    assert source_staleness(s, NOW, POLICY) == ["never fetched successfully"]


def test_reasons_are_readable(db: Session) -> None:
    s = source(
        db, bank(db, "A"), consecutive_failures=3, last_success_at=NOW - dt.timedelta(hours=50)
    )
    assert source_staleness(s, NOW, POLICY) == [
        "3 failed fetches in a row",
        "last success 50 h ago (limit 2 x 12 h)",
    ]


def test_institution_states(db: Session) -> None:
    fresh, mixed, empty = bank(db, "FRESH"), bank(db, "MIXED"), bank(db, "EMPTY")
    source(db, fresh)
    source(db, mixed)
    stale = source(db, mixed, variant="online", consecutive_failures=2)
    # Sources that aren't monitored don't count either way:
    source(db, empty, url=None, needs_check=True, last_success_at=None)
    source(db, empty, variant="x", adapter_name=None, last_success_at=None)
    source(db, empty, variant="y", active=False, last_success_at=None)

    states = institution_freshness(db, NOW, POLICY)

    assert states[fresh.id].state == "verified" and states[fresh.id].verified
    assert states[mixed.id].state == "unverified"
    assert [s.source_id for s in states[mixed.id].stale_sources] == [stale.id]
    assert states[empty.id].state == "no_sources"


def test_policy_comes_from_rules_yaml(db: Session) -> None:
    from pipeline.validate.rules import staleness_policy

    s = source(
        db, bank(db, "A"), consecutive_failures=1, last_success_at=NOW - dt.timedelta(hours=30)
    )
    assert source_staleness(s, NOW, staleness_policy()) == [
        "last success 30 h ago (limit 2 x 12 h)"
    ]
