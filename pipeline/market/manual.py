"""`python -m pipeline market manual`: enter one value by hand when a fetch fails.

The entry keeps full provenance: a `snapshot` of the provider "manual" whose payload
is the entry itself (series, period, value, source URL, who entered it, note) and
whose url is the source the value was read from. The value is a new observation,
or a new revision if it differs from the current one. A later fetch that finds a
different value becomes the next revision, so the provider's value wins.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import Frequency, SourceKind
from core.models import MarketObservation, MarketSeries, Snapshot, Source
from pipeline.fetch.storage import SnapshotStore
from pipeline.market.client import MarketDataError
from pipeline.market.monthend import period_end
from pipeline.market.source import canonical_json

VN = ZoneInfo("Asia/Ho_Chi_Minh")
QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True)
class ManualEntry:
    series: str
    period: str  # YYYY-MM for monthly series, YYYY for yearly, YYYY-MM-DD for daily
    value: Decimal
    source_url: str
    entered_by: str
    note: str
    obs_date: dt.date | None = None  # the date the value is for; default: the period end


def parse_period(text: str, period: Frequency) -> dt.date:
    try:
        if period is Frequency.DAILY:
            return dt.date.fromisoformat(text)
        if period is Frequency.YEARLY:
            return period_end(dt.date(int(text), 1, 1), period)
        year, month = (int(x) for x in text.split("-"))
        return period_end(dt.date(year, month, 1), period)
    except ValueError as exc:
        raise MarketDataError(f"period {text!r} does not fit a {period.value} series") from exc


def enter(session: Session, store: SnapshotStore, entry: ManualEntry, now: dt.datetime) -> str:
    """Store one manual value; returns what happened. The caller commits."""
    series = session.scalar(select(MarketSeries).where(MarketSeries.code == entry.series))
    if series is None:
        raise MarketDataError(f"unknown series {entry.series!r}")
    if not entry.source_url.startswith(("http://", "https://")):
        raise MarketDataError("--source-url must be the http(s) page the value was read from")
    if not entry.entered_by.strip() or not entry.note.strip():
        raise MarketDataError("--entered-by and --note are required")
    end = parse_period(entry.period, series.period)
    today = now.astimezone(VN).date()
    if end > today or (series.period is not Frequency.DAILY and end >= today):
        raise MarketDataError(f"{entry.period} is not a closed period yet")
    obs_date = entry.obs_date or end
    if obs_date > end:
        raise MarketDataError(f"obs date {obs_date} is after the period end {end}")
    manual = session.scalar(
        select(Source).where(Source.kind == SourceKind.MARKET_DATA, Source.variant == "manual")
    )
    if manual is None:
        raise MarketDataError("no 'manual' provider: run `make seed`")
    value = entry.value.quantize(QUANTUM)
    revision = session.scalar(
        select(func.max(MarketObservation.revision)).where(
            MarketObservation.series_id == series.id, MarketObservation.period_end == end
        )
    )
    if revision is not None:
        current = session.scalar(
            select(MarketObservation).where(
                MarketObservation.series_id == series.id,
                MarketObservation.period_end == end,
                MarketObservation.revision == revision,
            )
        )
        if current is not None and current.value == value and current.obs_date == obs_date:
            return f"{series.code} {end}: already {value}, nothing stored"
    payload = canonical_json(
        {
            "series": series.code,
            "period_end": end.isoformat(),
            "obs_date": obs_date.isoformat(),
            "value": str(value),
            "source_url": entry.source_url,
            "entered_by": entry.entered_by,
            "note": entry.note,
            "entered_at": now.isoformat(),
        }
    )
    snapshot = Snapshot(
        source_id=manual.id,
        url=entry.source_url,
        fetched_at=now,
        http_status=None,
        content_type="application/json",
        sha256=_sha(payload),
        storage_key="",
        size_bytes=len(payload),
    )
    snapshot.storage_key = (
        f"MARKET/manual/{series.code}/{now.astimezone(dt.UTC).date()}/{snapshot.sha256}.json"
    )
    store.put(snapshot.storage_key, payload, "application/json")
    session.add(snapshot)
    session.flush()
    new_revision = 1 if revision is None else revision + 1
    session.add(
        MarketObservation(
            series_id=series.id,
            period_end=end,
            revision=new_revision,
            obs_date=obs_date,
            value=value,
            snapshot_id=snapshot.id,
        )
    )
    return f"{series.code} {end}: stored {value} (revision {new_revision}, snapshot {snapshot.id})"


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
