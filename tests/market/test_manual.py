"""`market manual`: a hand-entered value with full provenance."""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import MarketObservation, MarketSeries, Snapshot
from core.seed import load_market, parse_market
from pipeline.fetch.storage import MemoryStore
from pipeline.market.client import MarketDataError
from pipeline.market.manual import ManualEntry, enter

pytestmark = pytest.mark.db
SEEDS = Path(__file__).resolve().parents[2] / "data" / "seeds" / "market_series.yaml"
NOW = dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.UTC)
URL = "https://sjc.com.vn/bieu-do-gia-vang"


@pytest.fixture
def seeded(db: Session) -> Session:
    load_market(db, *parse_market(SEEDS))
    return db


def entry(value: str = "139000000", period: str = "2026-10") -> ManualEntry:
    return ManualEntry(
        "sjc_sell_close_vnd_luong", period, Decimal(value), URL, "Hùng", "SJC API down"
    )


def rows(db: Session) -> list[MarketObservation]:
    return list(
        db.scalars(
            select(MarketObservation)
            .join(MarketSeries)
            .where(MarketSeries.code == "sjc_sell_close_vnd_luong")
            .order_by(MarketObservation.revision)
        )
    )


def test_manual_value_is_stored_with_its_source(seeded: Session) -> None:
    store = MemoryStore()
    message = enter(seeded, store, entry(), NOW)
    assert "stored 139000000" in message and "revision 1" in message
    (obs,) = rows(seeded)
    assert obs.period_end == dt.date(2026, 10, 31) and obs.obs_date == dt.date(2026, 10, 31)
    snap = seeded.get(Snapshot, obs.snapshot_id)
    assert snap is not None and snap.url == URL
    payload = json.loads(store.get(snap.storage_key))
    assert payload["entered_by"] == "Hùng" and payload["note"] == "SJC API down"


def test_same_value_twice_adds_nothing_and_a_new_value_is_a_revision(seeded: Session) -> None:
    store = MemoryStore()
    enter(seeded, store, entry(), NOW)
    assert "nothing stored" in enter(seeded, store, entry(), NOW)
    enter(seeded, store, entry("139500000"), NOW)
    assert [(o.revision, o.value) for o in rows(seeded)] == [
        (1, Decimal("139000000")),
        (2, Decimal("139500000")),
    ]


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (entry(period="2026-11"), "not a closed period"),
        (entry(period="2026-13"), "does not fit"),
        (ManualEntry("nope", "2026-10", Decimal(1), URL, "a", "b"), "unknown series"),
        (
            ManualEntry("sjc_sell_close_vnd_luong", "2026-10", Decimal(1), "sjc", "a", "b"),
            "source-url",
        ),
        (
            ManualEntry("sjc_sell_close_vnd_luong", "2026-10", Decimal(1), URL, " ", "b"),
            "entered-by",
        ),
    ],
)
def test_bad_entries_are_refused(seeded: Session, bad: ManualEntry, message: str) -> None:
    with pytest.raises(MarketDataError, match=message):
        enter(seeded, MemoryStore(), bad, NOW)
