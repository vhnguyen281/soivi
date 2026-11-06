"""`python -m pipeline market ingest`: fetch every active series and store monthly
observations (docs/vncma/design-market-data.md §4).

- Series with an equal `request` share one fetch ("a group"). Each group runs in
  its own transaction: it is stored completely or not at all.
- The raw payload goes to S3 under MARKET/<provider>/<group>/<date>/<sha256>.<ext>
  with a `snapshot` row. A payload equal to the group's last snapshot is not stored
  again, and an unchanged value is not written again, so a second run adds nothing.
- A value that differs from the stored one is a new row with revision + 1 (append-only).
"""

import datetime as dt
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import MarketObservation, MarketSeries, Snapshot, Source
from pipeline.fetch.storage import SnapshotStore, extension_for
from pipeline.market.client import MarketDataError
from pipeline.market.monthend import to_periods
from pipeline.market.source import Fetched, Fetcher

VN = ZoneInfo("Asia/Ho_Chi_Minh")
QUANTUM = Decimal("0.00000001")  # market_observation.value is NUMERIC(20, 8)


@dataclass
class GroupResult:
    label: str
    provider: str
    status: str  # stored | unchanged | failed
    new: int = 0
    revised: int = 0
    gaps: int = 0
    error: str | None = None
    revisions: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.status == "failed":
            return f"[FAIL] {self.label}: {self.error}"
        extra = f", {self.gaps} gap months" if self.gaps else ""
        return f"[{self.status}] {self.label}: {self.new} new, {self.revised} revised{extra}"


def _label(codes: Sequence[str]) -> str:
    return ", ".join(codes) if len(codes) <= 3 else f"{codes[0]} +{len(codes) - 1}"


def _group_key(series: MarketSeries) -> tuple[int, str]:
    return series.source_id, json.dumps(series.request, sort_keys=True)


def _current(session: Session, series_ids: Sequence[int]) -> dict[int, dict[dt.date, Any]]:
    """series_id -> period_end -> the current (highest revision) observation."""
    latest = (
        select(
            MarketObservation.series_id,
            MarketObservation.period_end,
            func.max(MarketObservation.revision).label("revision"),
        )
        .where(MarketObservation.series_id.in_(series_ids))
        .group_by(MarketObservation.series_id, MarketObservation.period_end)
        .subquery()
    )
    rows = session.scalars(
        select(MarketObservation).join(
            latest,
            (MarketObservation.series_id == latest.c.series_id)
            & (MarketObservation.period_end == latest.c.period_end)
            & (MarketObservation.revision == latest.c.revision),
        )
    )
    out: dict[int, dict[dt.date, Any]] = {i: {} for i in series_ids}
    for row in rows:
        out[row.series_id][row.period_end] = row
    return out


def _store_snapshot(
    session: Session,
    store: SnapshotStore,
    source: Source,
    group_code: str,
    fetched: Fetched,
    now: dt.datetime,
) -> Snapshot:
    assert fetched.payload is not None
    sha = fetched.sha256
    ext = extension_for(fetched.content_type)
    key = f"MARKET/{source.variant}/{group_code}/{now.astimezone(dt.UTC).date()}/{sha}.{ext}"
    if not store.exists(key):
        store.put(key, fetched.payload, fetched.content_type)
    snapshot = Snapshot(
        source_id=source.id,
        url=fetched.url,
        fetched_at=now,
        http_status=fetched.http_status,
        content_type=fetched.content_type,
        sha256=sha,
        storage_key=key,
        size_bytes=len(fetched.payload),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


@dataclass(frozen=True)
class _Group:
    provider: str
    codes: list[str]
    request: dict[str, Any]
    value_fields: list[str]
    have: set[dt.date]


def _read_group(session: Session, series_ids: Sequence[int]) -> _Group:
    series = list(
        session.scalars(
            select(MarketSeries).where(MarketSeries.id.in_(series_ids)).order_by(MarketSeries.code)
        )
    )
    source = session.get(Source, series[0].source_id)
    assert source is not None
    current = _current(session, series_ids)
    return _Group(
        provider=source.variant,
        codes=[s.code for s in series],
        request=dict(series[0].request),
        value_fields=[s.value_field for s in series],
        have=set.intersection(*(set(current[s.id]) for s in series)),
    )


def _write(
    session: Session,
    store: SnapshotStore,
    series_ids: Sequence[int],
    fetched: Fetched,
    now: dt.datetime,
    result: GroupResult,
) -> None:
    """Store one fetch: snapshot (unless identical to the last one) and changed values."""
    series = list(
        session.scalars(
            select(MarketSeries).where(MarketSeries.id.in_(series_ids)).order_by(MarketSeries.code)
        )
    )
    source = session.get(Source, series[0].source_id)
    assert source is not None
    source.last_attempt_at = now
    source.last_success_at, source.last_status, source.last_error = now, "ok", None
    for s in series:
        s.last_checked_at = now
    if fetched.payload is None:  # nothing new to fetch (e.g. every HNX month is stored)
        return

    # The same bytes as last time: reuse that snapshot rather than storing a copy. The
    # values are still recomputed, so a changed month-end rule takes effect.
    previous = {s.last_snapshot_id for s in series}
    snapshot = None
    if len(previous) == 1 and None not in previous:
        last = session.get(Snapshot, next(iter(previous)))
        if last is not None and last.sha256 == fetched.sha256:
            snapshot = last
    if snapshot is None:
        snapshot = _store_snapshot(session, store, source, series[0].code, fetched, now)
        result.status = "stored"
    today = now.astimezone(VN).date()
    current = _current(session, series_ids)
    for s in series:
        periods = to_periods(
            fetched.points.get(s.value_field, []),
            s.month_end_rule,
            s.period,
            s.max_gap_days,
            today,
        )
        result.gaps += len(periods.gaps)
        for end, pv in sorted(periods.values.items()):
            value = pv.value.quantize(QUANTUM)
            old = current[s.id].get(end)
            if old is not None and old.value == value and old.obs_date == pv.obs_date:
                continue
            revision = 1 if old is None else old.revision + 1
            session.add(
                MarketObservation(
                    series_id=s.id,
                    period_end=end,
                    revision=revision,
                    obs_date=pv.obs_date,
                    value=value,
                    snapshot_id=snapshot.id,
                )
            )
            result.status = "stored"
            if old is None:
                result.new += 1
            else:
                result.revised += 1
                result.revisions.append(f"{s.code} {end}: {old.value} -> {value}")
        s.last_snapshot_id = snapshot.id


MAX_ROUNDS = 100  # a fetcher that keeps saying "more" is a bug, not a long history


def _ingest_group(
    session_factory: Callable[[], Session],
    store: SnapshotStore,
    fetchers: Mapping[str, Fetcher],
    series_ids: Sequence[int],
    now: Callable[[], dt.datetime],
) -> GroupResult:
    """Read state, fetch with no transaction open (fetches can take many minutes and
    Neon closes idle transactions), then write in a short transaction. A fetcher that
    works in chunks (HNX) sets `more`; each chunk is stored before the next one."""
    with session_factory() as session:
        group = _read_group(session, series_ids)
    result = GroupResult(_label(group.codes), group.provider, "unchanged")
    fetcher = fetchers.get(group.provider)
    if fetcher is None:
        raise MarketDataError(f"no fetcher for provider {group.provider!r}")
    for _ in range(MAX_ROUNDS):
        today = now().astimezone(VN).date()
        fetched = fetcher.fetch(group.request, group.value_fields, group.have, today)
        with session_factory() as session, session.begin():
            _write(session, store, series_ids, fetched, now(), result)
        if not fetched.more:
            return result
        with session_factory() as session:
            group = _read_group(session, series_ids)
    raise MarketDataError(f"{result.label}: still fetching after {MAX_ROUNDS} rounds")


def ingest(
    session_factory: Callable[[], Session],
    store: SnapshotStore,
    fetchers: Mapping[str, Fetcher],
    codes: Sequence[str] | None = None,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    log: Callable[[str], None] = print,
) -> list[GroupResult]:
    with session_factory() as session:
        query = select(MarketSeries).where(MarketSeries.active.is_(True))
        if codes:
            query = select(MarketSeries).where(MarketSeries.code.in_(codes))
        selected = list(session.scalars(query.order_by(MarketSeries.code)))
        if codes:
            unknown = sorted(set(codes) - {s.code for s in selected})
            if unknown:
                raise MarketDataError(f"unknown series: {unknown}")
        groups: dict[tuple[int, str], list[int]] = {}
        for s in selected:
            groups.setdefault(_group_key(s), []).append(s.id)
        providers = {src.id: src.variant for src in session.scalars(select(Source))}

    results: list[GroupResult] = []
    for (source_id, _), ids in groups.items():
        try:
            result = _ingest_group(session_factory, store, fetchers, ids, now)
        except Exception as exc:  # one group failing must not stop the others
            if not isinstance(exc, MarketDataError):
                exc = MarketDataError(f"{type(exc).__name__}: {exc}")
            with session_factory() as session:
                codes_ = sorted(
                    session.scalars(select(MarketSeries.code).where(MarketSeries.id.in_(ids)))
                )
            result = GroupResult(_label(codes_), providers[source_id], "failed", error=str(exc))
            with session_factory() as session, session.begin():
                src = session.get(Source, source_id)
                if src is not None:
                    src.last_attempt_at = now()
                    src.last_status, src.last_error = "ingest_failed", str(exc)[:2000]
        results.append(result)
        log(str(result))
        for line in result.revisions:
            log(f"    revised {line}")
    return results
