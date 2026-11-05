"""The scheduler: run due sources, read news feeds, alert on broken adapters, send
the daily summary.

    python -m pipeline schedule --once          # one tick (for system cron)
    python -m pipeline schedule --loop          # tick every 5 minutes (Docker service)

Ticks never overlap: a file lock (settings.pipeline_lock_file) makes a second
process skip its tick. The rate limit is per process, so this also keeps us
polite. Each source runs in its own transaction.
"""

import datetime as dt
import fcntl
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Source
from pipeline.adapters.base import AdapterContext
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.storage import SnapshotStore
from pipeline.monitor import alert_for, daily_summary, summary_due
from pipeline.news.service import NewsRunResult, news_due
from pipeline.notify import Notifier, notify
from pipeline.runner import RunResult, due_sources, run_source
from pipeline.validate.rules import staleness_policy

Clock = Callable[[], dt.datetime]
# Reads the feeds and re-checks sources, sharing the tick's fetchers (and rate limit).
NewsJob = Callable[[Fetchers, Clock], NewsRunResult]


@dataclass
class TickResult:
    skipped: bool = False  # another tick held the lock
    results: list[RunResult] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    summary_sent: bool = False
    news: NewsRunResult | None = None


class LockBusy(Exception):
    pass


@contextmanager
def single_run(path: str) -> Iterator[None]:
    handle = open(path, "a+")  # noqa: SIM115
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusy(path) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        handle.close()  # releases the lock


def tick(
    settings: Settings,
    session_factory: Callable[[], Session],
    fetchers_factory: Callable[[], Fetchers],
    store: SnapshotStore,
    notifier: Notifier,
    clock: Clock = lambda: dt.datetime.now(dt.UTC),
    news: NewsJob | None = None,
) -> TickResult:
    out = TickResult()
    tz = ZoneInfo(settings.timezone)
    shared: list[Fetchers] = []

    def fetchers() -> Fetchers:
        if not shared:
            shared.append(fetchers_factory())
        return shared[0]

    def record(result: RunResult, previous: str | None) -> None:
        out.results.append(result)
        print(result, flush=True)
        alert = alert_for(result, previous)
        if alert:
            kind, text = alert
            with session_factory() as session, session.begin():
                notify(session, notifier, kind, text, source_id=result.source_id, now=clock())
            out.alerts.append(kind)

    try:
        with single_run(settings.pipeline_lock_file):
            now = clock()
            with session_factory() as session:
                due = [(s.id, s.last_status) for s in due_sources(session, now)]
            try:
                for source_id, previous in due:
                    with session_factory() as session, session.begin():
                        source = session.get(Source, source_id)
                        assert source is not None
                        ctx = AdapterContext(session=session, fetchers=fetchers(), store=store)
                        result = run_source(ctx, source, trigger="schedule", now=clock)
                    record(result, previous)

                if news is not None:
                    with session_factory() as session:
                        news_is_due = news_due(session, clock(), tz)
                    if news_is_due:
                        out.news = news(fetchers(), clock)
                        for line in out.news.lines():
                            print(f"news: {line}", flush=True)
                        for result, previous in out.news.runs:
                            record(result, previous)
            finally:
                if shared:
                    shared[0].close()

            with session_factory() as session, session.begin():
                now = clock()
                if summary_due(session, now, tz, settings.daily_summary_hour):
                    text = daily_summary(session, now, tz, staleness_policy())
                    out.summary_sent = notify(session, notifier, "daily_summary", text, now=now)
    except LockBusy:
        out.skipped = True
    return out


def loop(interval_seconds: int, run_tick: Callable[[], TickResult]) -> None:  # pragma: no cover
    while True:
        started = time.monotonic()
        try:
            result = run_tick()
            if result.skipped:
                print("another tick is running; skipped", flush=True)
        except Exception as exc:  # keep the scheduler alive; the next tick retries
            print(f"tick failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(max(5.0, interval_seconds - (time.monotonic() - started)))
