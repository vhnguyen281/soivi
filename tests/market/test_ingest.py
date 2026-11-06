"""`market ingest` against soivi_test: idempotent, append-only, never partial."""

import datetime as dt
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.enums import FetchMethod, Frequency, MonthEndRule, SourceKind
from core.models import MarketObservation, MarketSeries, Snapshot, Source
from core.seed import load_market, parse_market
from pipeline.fetch.storage import MemoryStore
from pipeline.market.client import MarketDataError
from pipeline.market.ingest import ingest
from pipeline.market.monthend import Point
from pipeline.market.source import Fetched, canonical_json

pytestmark = pytest.mark.db
SEEDS = Path(__file__).resolve().parents[2] / "data" / "seeds" / "market_series.yaml"
NOW = dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.UTC)


class FakeFetcher:
    """Returns `data[value_field]` as points; payload is their canonical JSON."""

    def __init__(self, data: dict[str, list[tuple[dt.date, str]]]) -> None:
        self.data = data
        self.calls = 0
        self.fail: str | None = None

    def fetch(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        self.calls += 1
        if self.fail:
            raise MarketDataError(self.fail)
        points = {f: [Point(d, Decimal(v)) for d, v in self.data[f]] for f in value_fields}
        payload = canonical_json(
            {f: [[d.isoformat(), v] for d, v in self.data[f]] for f in value_fields}
        )
        return Fetched("fake:call", "application/json", payload, points)


@pytest.fixture
def factory(db: Session) -> Callable[[], Session]:
    conn = db.connection()
    assert isinstance(conn, Connection)
    return lambda: Session(bind=conn, join_transaction_mode="create_savepoint")


def add_series(db: Session, source: Source, code: str, field: str, request: dict[str, Any]) -> None:
    db.add(
        MarketSeries(
            code=code,
            source_id=source.id,
            request=request,
            value_field=field,
            unit="pct_pa",
            native_frequency=Frequency.DAILY,
            period=Frequency.MONTHLY,
            month_end_rule=MonthEndRule.LAST_ON_OR_BEFORE,
            max_gap_days=7,
            grade="B",
        )
    )


@pytest.fixture
def setup(db: Session) -> dict[str, FakeFetcher]:
    for name in ("fakea", "fakeb"):
        db.add(
            Source(
                kind=SourceKind.MARKET_DATA,
                variant=name,
                url=f"https://{name}.example/",
                fetch_method=FetchMethod.API,
                cadence_hours=744,
            )
        )
    db.flush()
    a, b = (db.scalar(select(Source).where(Source.variant == n)) for n in ("fakea", "fakeb"))
    assert a and b
    add_series(db, a, "cpi_x", "total", {"call": "shared"})
    add_series(db, a, "cpi_y", "core", {"call": "shared"})  # same request: one fetch
    add_series(db, b, "other", "close", {"call": "other"})
    db.flush()
    days = [(dt.date(2026, 9, 30), "1.5"), (dt.date(2026, 10, 30), "1.6")]
    return {
        "fakea": FakeFetcher({"total": days, "core": [(d, "2.0") for d, _ in days]}),
        "fakeb": FakeFetcher({"close": days}),
    }


def counts(db: Session) -> tuple[int, int]:
    return (
        db.scalar(select(func.count()).select_from(MarketObservation)) or 0,
        db.scalar(select(func.count()).select_from(Snapshot)) or 0,
    )


def run(factory: Callable[[], Session], fetchers: dict[str, FakeFetcher]) -> list[Any]:
    return ingest(factory, MemoryStore(), fetchers, now=lambda: NOW, log=lambda _: None)


def test_two_ingests_in_a_row_the_second_adds_nothing(
    db: Session, factory: Callable[[], Session], setup: dict[str, FakeFetcher]
) -> None:
    first = run(factory, setup)
    assert [r.status for r in first] == ["stored", "stored"]
    assert setup["fakea"].calls == 1  # two series, one fetch
    assert counts(db) == (6, 2)  # 3 series x 2 months; one snapshot per group
    second = run(factory, setup)
    assert [r.status for r in second] == ["unchanged", "unchanged"]
    assert counts(db) == (6, 2)
    obs = db.scalars(select(MarketObservation).order_by(MarketObservation.id)).first()
    assert obs is not None and obs.obs_date == dt.date(2026, 9, 30)
    assert obs.period_end == dt.date(2026, 9, 30) and obs.revision == 1


def test_a_corrected_value_is_a_new_revision(
    db: Session, factory: Callable[[], Session], setup: dict[str, FakeFetcher]
) -> None:
    run(factory, setup)
    setup["fakeb"].data["close"][0] = (dt.date(2026, 9, 30), "1.55")
    results = run(factory, setup)
    other = next(r for r in results if r.label == "other")
    assert (other.new, other.revised) == (0, 1)
    assert other.revisions == ["other 2026-09-30: 1.50000000 -> 1.55000000"]
    rows = db.scalars(
        select(MarketObservation)
        .join(MarketSeries)
        .where(MarketSeries.code == "other", MarketObservation.period_end == dt.date(2026, 9, 30))
        .order_by(MarketObservation.revision)
    ).all()
    assert [(r.revision, r.value) for r in rows] == [(1, Decimal("1.5")), (2, Decimal("1.55"))]


def test_a_failing_group_writes_nothing_and_the_others_still_run(
    db: Session, factory: Callable[[], Session], setup: dict[str, FakeFetcher]
) -> None:
    setup["fakea"].fail = "Macro().economy().cpi() returned an empty table"
    results = run(factory, setup)
    assert [(r.label, r.status) for r in results] == [
        ("cpi_x, cpi_y", "failed"),
        ("other", "stored"),
    ]
    assert "cpi() returned an empty table" in (results[0].error or "")
    assert counts(db) == (2, 1)
    src = db.scalar(select(Source).where(Source.variant == "fakea"))
    assert src is not None and src.last_status == "ingest_failed"


def test_observations_cannot_be_changed_or_deleted(
    db: Session, factory: Callable[[], Session], setup: dict[str, FakeFetcher]
) -> None:
    run(factory, setup)
    for sql in ("UPDATE market_observation SET value = 0", "DELETE FROM market_observation"):
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(text(sql))


def test_the_seed_file_loads_and_reloads_without_changes(db: Session) -> None:
    providers, series = parse_market(SEEDS)
    first = load_market(db, providers, series)
    assert first.inserted == len(providers) + len(series)
    again = load_market(db, providers, series)
    assert (again.inserted, again.updated) == (0, 0)
    vn30 = db.scalar(select(MarketSeries).where(MarketSeries.code == "vn30_close"))
    assert vn30 is not None and vn30.request["call"][2][2]["source"] == "vci"


def test_a_wider_gap_limit_adds_the_month_from_the_same_snapshot(
    db: Session, factory: Callable[[], Session], setup: dict[str, FakeFetcher]
) -> None:
    # Tết: the last trading day of January 2009 was the 22nd, 9 days before the month end.
    setup["fakeb"].data["close"] = [(dt.date(2009, 1, 22), "300"), (dt.date(2009, 2, 27), "250")]
    run(factory, setup)
    other = db.scalar(select(MarketSeries).where(MarketSeries.code == "other"))
    assert other is not None
    stored = db.scalars(select(MarketObservation).where(MarketObservation.series_id == other.id))
    assert [o.period_end for o in stored] == [dt.date(2009, 2, 28)]
    snapshots = counts(db)[1]
    other.max_gap_days = 10
    db.flush()
    result = next(r for r in run(factory, setup) if r.label == "other")
    assert (result.status, result.new) == ("stored", 1)
    assert counts(db)[1] == snapshots  # same bytes: no new snapshot
    jan = db.scalar(
        select(MarketObservation).where(
            MarketObservation.series_id == other.id,
            MarketObservation.period_end == dt.date(2009, 1, 31),
        )
    )
    assert jan is not None and jan.snapshot_id == other.last_snapshot_id
