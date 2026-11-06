"""Run adapters against sources: fetch -> store snapshot -> parse.

Each source runs in its own savepoint, so one failure never undoes another
source's snapshot. After parsing, pipeline/diff proposes new or changed values as
pending versions and opens one review task per snapshot. The caller commits.
"""

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import SourceKind
from core.models import Institution, PipelineRun, Source
from pipeline.adapters.base import AdapterBroken, AdapterContext
from pipeline.diff import DiffResult, diff_snapshot
from pipeline.fetch.polite import RobotsDisallowed
from pipeline.records import Record
from pipeline.registry import get_adapter
from pipeline.schedule import is_due

Status = Literal["parsed", "unchanged", "fetch_failed", "parse_failed", "diff_failed"]


@dataclass
class RunResult:
    source_id: int
    label: str
    status: Status
    snapshot_id: int | None = None
    records: list[Record] = field(default_factory=list)
    diff: DiffResult | None = None
    error: str | None = None
    error_type: str | None = None  # exception class name, e.g. "AdapterBroken"

    @property
    def adapter_broken(self) -> bool:
        return self.error_type == "AdapterBroken"

    @property
    def ok(self) -> bool:
        return self.status in {"parsed", "unchanged"}

    def __str__(self) -> str:
        detail = {
            "parsed": f"{len(self.records)} records (snapshot {self.snapshot_id}): {self.diff}",
            "unchanged": f"same bytes as last time (snapshot {self.snapshot_id})",
        }.get(self.status, self.error or "")
        return f"[{self.status}] source {self.source_id} {self.label}: {detail}"


# --------------------------------------------------------------------------- selection


def runnable() -> Select[Source]:
    """Sources the scheduler may run: active, confirmed, with a URL and an adapter.

    Market-data providers (VNCMA) have their own path: `python -m pipeline market ingest`.
    """
    return select(Source).where(
        Source.kind != SourceKind.MARKET_DATA,
        Source.active.is_(True),
        Source.needs_check.is_(False),
        Source.url.is_not(None),
        Source.adapter_name.is_not(None),
    )


def due_sources(session: Session, now: dt.datetime) -> list[Source]:
    """Runnable sources whose schedule slot is due (pipeline/schedule.py)."""
    tz = ZoneInfo(get_settings().timezone)
    sources = session.scalars(runnable().order_by(Source.id)).all()
    return [s for s in sources if is_due(s, now, tz)]


def institution_sources(session: Session, short_name: str) -> list[Source]:
    inst = session.scalars(select(Institution).where(Institution.short_name == short_name)).first()
    if inst is None:
        raise LookupError(f"no institution {short_name!r}")
    return list(
        session.scalars(runnable().where(Source.institution_id == inst.id).order_by(Source.id))
    )


# --------------------------------------------------------------------------- running


def _label(session: Session, source: Source) -> str:
    inst = session.get(Institution, source.institution_id) if source.institution_id else None
    parts = [inst.short_name if inst else "-", source.kind.value, source.variant]
    return "/".join(p for p in parts if p)


def run_source(
    ctx: AdapterContext,
    source: Source,
    *,
    reparse: bool = False,
    trigger: str = "manual",
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> RunResult:
    """Run one source and record the outcome on the source and in pipeline_run.

    Only a fully successful run (fetched and, if changed, parsed and diffed) counts
    as a success. A fetched page the adapter can't read is a failure too, so a
    broken adapter makes the institution's data show as unverified.
    """
    session = ctx.session
    started = now()
    result = RunResult(source.id, _label(session, source), "fetch_failed")
    snapshot_at = _run(ctx, source, result, reparse)

    source.last_attempt_at = started
    source.last_status = result.status
    source.last_error = result.error
    if result.ok:
        source.last_success_at = snapshot_at or started
        source.consecutive_failures = 0
    else:
        source.consecutive_failures += 1
    diff = result.diff
    session.add(
        PipelineRun(
            source_id=source.id,
            started_at=started,
            finished_at=now(),
            status=result.status,
            error=result.error,
            snapshot_id=result.snapshot_id,
            new=diff.new if diff else 0,
            changed=diff.changed if diff else 0,
            removed=diff.removed if diff else 0,
            review_task_id=diff.review_task_id if diff else None,
            trigger=trigger,
        )
    )
    session.flush()
    return result


def _run(
    ctx: AdapterContext, source: Source, result: RunResult, reparse: bool
) -> dt.datetime | None:
    """Fetch, parse and diff; fills `result`. Returns the snapshot time if fetched."""
    session = ctx.session
    try:
        with session.begin_nested():
            if not source.adapter_name:
                raise LookupError("source has no adapter_name")
            adapter = get_adapter(source.adapter_name)(source, ctx)
            snapshot = adapter.fetch()
    except Exception as exc:  # report and move on to the next source
        result.error = f"{type(exc).__name__}: {exc}"
        result.error_type = type(exc).__name__
        if isinstance(exc, RobotsDisallowed):
            source.robots_ok = False
        return None

    source.robots_ok = True
    result.snapshot_id = snapshot.id
    # Same bytes as last time: skip parsing, unless last time's parse or diff failed
    # (e.g. an API outage during LLM extraction), so the page still gets read.
    retry = source.last_status in ("parse_failed", "diff_failed")
    if snapshot.unchanged and not reparse and not retry:
        result.status = "unchanged"
        return snapshot.fetched_at

    try:
        records = adapter.parse(snapshot)
        notes = list(adapter.notes)
        if not records and not adapter.allows_empty():
            raise AdapterBroken("parse() returned no records")
        bad = [type(r).__name__ for r in records if not isinstance(r, Record)]
        if bad:
            raise AdapterBroken(f"parse() returned non-records: {sorted(set(bad))}")
    except Exception as exc:
        result.status = "parse_failed"
        result.error = f"{type(exc).__name__}: {exc}"
        result.error_type = type(exc).__name__
        return snapshot.fetched_at

    result.records = records
    try:
        result.diff = diff_snapshot(
            session, source, snapshot, records, adapter.extraction_method, notes=notes
        )
    except Exception as exc:  # e.g. two records for one series; nothing was written
        result.status = "diff_failed"
        result.error = f"{type(exc).__name__}: {exc}"
        result.error_type = type(exc).__name__
        return snapshot.fetched_at
    result.status = "parsed"
    return snapshot.fetched_at


def run_sources(
    ctx: AdapterContext, sources: Sequence[Source], *, reparse: bool = False
) -> list[RunResult]:
    return [run_source(ctx, s, reparse=reparse) for s in sources]
