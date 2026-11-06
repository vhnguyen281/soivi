"""Pipeline CLI.

    python -m pipeline run --source 12            # one source (even if flagged; needs a URL)
    python -m pipeline run --institution ACB      # that institution's runnable sources
    python -m pipeline run --all-due              # every runnable source past its cadence
    python -m pipeline adapters                   # list registered adapters
    python -m pipeline status                     # institutions whose data is unverified
    python -m pipeline schedule --once | --loop   # scheduled runs + alerts + daily summary
    python -m pipeline summary [--send]           # the daily summary, now
    python -m pipeline news [--feed NAME] [--no-recheck]   # read news feeds now
    python -m pipeline save URL FILE [--method browser]   # save a page for test fixtures
    python -m pipeline market check               # vnstock version, tier, one VN30 close

Add --reparse to parse even when the page has not changed (e.g. after fixing an
adapter). Each source is committed on its own, so one failure keeps the others.
Exit code 1 if any source failed.
"""

import argparse
import datetime as dt
import hashlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from core.config import Settings
    from pipeline.market.client import MarketClient
    from pipeline.scheduler import NewsJob

from core.enums import FetchMethod
from core.models import Source
from pipeline.adapters.base import AdapterContext
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import FetchError, PoliteHttp
from pipeline.fetch.storage import MinioStore, SnapshotStore
from pipeline.market import cli as market_cli
from pipeline.registry import all_adapters, load_adapters
from pipeline.runner import RunResult, due_sources, institution_sources, run_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch, store and parse sources")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--source", type=int, metavar="ID", help="source.id")
    which.add_argument("--institution", metavar="SHORT_NAME", help="institution.short_name")
    which.add_argument("--all-due", action="store_true", help="every source past its cadence")
    run.add_argument("--reparse", action="store_true", help="parse even if the page is unchanged")

    sub.add_parser("adapters", help="list registered adapters")
    sub.add_parser("status", help="which institutions' data is unverified (stale sources)")

    sched = sub.add_parser("schedule", help="run due sources, send alerts and the daily summary")
    mode = sched.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="one tick (for system cron)")
    mode.add_argument("--loop", action="store_true", help="tick forever (Docker service)")
    sched.add_argument("--interval", type=int, default=300, help="seconds between ticks")

    summary = sub.add_parser("summary", help="print the daily summary (or send it)")
    summary.add_argument(
        "--send", action="store_true", help="send via Telegram instead of printing"
    )

    news = sub.add_parser(
        "news", help="read news feeds, classify, re-check banks that changed rates/fees"
    )
    news.add_argument("--feed", metavar="NAME", help="one feed from pipeline/news/feeds.yaml")
    news.add_argument(
        "--no-recheck", action="store_true", help="store and classify only; run no sources"
    )

    save = sub.add_parser("save", help="fetch one URL politely and save it (for test fixtures)")
    save.add_argument("url")
    save.add_argument("out", help="file to write, e.g. tests/fixtures/acb/savings_2026-10-26.html")
    save.add_argument("--method", choices=[m.value for m in FetchMethod], default="http")
    save.add_argument(
        "--post", action="store_true", help="send an (empty) form POST instead of GET"
    )
    market_cli.add_parser(sub)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    fetchers_factory: Callable[[], Fetchers] | None = None,
    store_factory: Callable[[], SnapshotStore] | None = None,
    market_client_factory: "Callable[[], MarketClient] | None" = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "market":
        return market_cli.run(args, market_client_factory)
    load_adapters()

    if args.command == "adapters":
        for name, cls in sorted(all_adapters().items()):
            print(f"{name}: {cls.institution}/{cls.source_kind.value} via {cls.fetch_method.value}")
        return 0

    if args.command == "status":
        return _status(session_factory)
    if args.command == "schedule":
        return _schedule(args, session_factory, fetchers_factory, store_factory)
    if args.command == "summary":
        return _summary(args.send, session_factory)
    if args.command == "news":
        return _news(args, session_factory, fetchers_factory, store_factory)

    if args.command == "save":
        return _save(args.url, args.out, FetchMethod(args.method), args.post, fetchers_factory)

    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal
    fetchers = (fetchers_factory or (lambda: Fetchers(PoliteHttp())))()
    store = (store_factory or MinioStore)()

    results: list[RunResult] = []
    try:
        with session_factory() as session:
            source_ids = _select(session, args)
        for source_id in source_ids:
            # One transaction per source: a crash later never loses earlier snapshots.
            with session_factory() as session, session.begin():
                source = session.get(Source, source_id)
                assert source is not None
                ctx = AdapterContext(session=session, fetchers=fetchers, store=store)
                result = run_source(ctx, source, reparse=args.reparse)
            print(result, flush=True)
            results.append(result)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        fetchers.close()

    failed = sum(not r.ok for r in results)
    print(f"{len(results)} sources, {failed} failed", file=sys.stderr)
    return 1 if failed else 0


def _save(
    url: str,
    out: str,
    method: FetchMethod,
    post: bool,
    fetchers_factory: Callable[[], Fetchers] | None,
) -> int:
    fetchers = (fetchers_factory or (lambda: Fetchers(PoliteHttp())))()
    try:
        fetcher = fetchers.for_method(method)
        result = fetcher.fetch(url, "POST", {}) if post else fetcher.fetch(url)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        fetchers.close()
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.content)
    sha = hashlib.sha256(result.content).hexdigest()
    print(f"saved {len(result.content)} bytes to {path} ({result.content_type}, sha256 {sha[:12]})")
    if result.final_url != url:
        print(f"note: redirected to {result.final_url}")
    return 0


def _schedule(
    args: argparse.Namespace,
    session_factory: Callable[[], Session] | None,
    fetchers_factory: Callable[[], Fetchers] | None,
    store_factory: Callable[[], SnapshotStore] | None,
) -> int:
    from core.config import get_settings
    from pipeline.notify import make_notifier
    from pipeline.scheduler import TickResult, loop, tick

    settings = get_settings()
    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal
    store = (store_factory or MinioStore)()
    notifier = make_notifier(settings)
    factory = session_factory

    def run_tick() -> "TickResult":
        return tick(
            settings,
            factory,
            fetchers_factory or (lambda: Fetchers(PoliteHttp())),
            store,
            notifier,
            news=_news_job(settings, factory, store),
        )

    if args.loop:
        print(f"scheduler: ticking every {args.interval}s ({settings.timezone})", flush=True)
        loop(args.interval, run_tick)
    result = run_tick()
    if result.skipped:
        print("another scheduler tick is running; skipped", file=sys.stderr)
    return 0 if all(r.ok for r in result.results) else 1


def _news_job(
    settings: "Settings", session_factory: Callable[[], Session], store: SnapshotStore
) -> "NewsJob":
    from zoneinfo import ZoneInfo

    from pipeline.news.feeds import load_config
    from pipeline.news.institutions import InstitutionMatcher
    from pipeline.news.llm import make_classifier
    from pipeline.news.service import NewsRunResult, run_news

    config = load_config()

    def job(fetchers: Fetchers, clock: Callable[[], dt.datetime]) -> NewsRunResult:
        with session_factory() as session:
            matcher = InstitutionMatcher.from_db(session)
        return run_news(
            session_factory,
            fetchers,
            store,
            config,
            tz=ZoneInfo(settings.timezone),
            llm=make_classifier(settings, matcher),
            matcher=matcher,
            now=clock,
        )

    return job


def _news(
    args: argparse.Namespace,
    session_factory: Callable[[], Session] | None,
    fetchers_factory: Callable[[], Fetchers] | None,
    store_factory: Callable[[], SnapshotStore] | None,
) -> int:
    from zoneinfo import ZoneInfo

    from core.config import get_settings
    from pipeline.news.feeds import load_config
    from pipeline.news.institutions import InstitutionMatcher
    from pipeline.news.llm import make_classifier
    from pipeline.news.service import run_news
    from pipeline.scheduler import LockBusy, single_run

    settings = get_settings()
    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal
    config = load_config()
    try:
        feeds = [config.get(args.feed)] if args.feed else None
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    fetchers = (fetchers_factory or (lambda: Fetchers(PoliteHttp())))()
    store = (store_factory or MinioStore)()
    try:
        # Same lock as the scheduler: one process, one rate limit per host.
        with single_run(settings.pipeline_lock_file):
            with session_factory() as session:
                matcher = InstitutionMatcher.from_db(session)
            result = run_news(
                session_factory,
                fetchers,
                store,
                config,
                tz=ZoneInfo(settings.timezone),
                llm=make_classifier(settings, matcher),
                matcher=matcher,
                feeds=feeds,
                do_recheck=not args.no_recheck,
            )
    except LockBusy:
        print("the scheduler is running; try again in a few minutes", file=sys.stderr)
        return 2
    finally:
        fetchers.close()
    for line in result.lines():
        print(line)
    return 0 if result.ok else 1


def _summary(send: bool, session_factory: Callable[[], Session] | None) -> int:
    from zoneinfo import ZoneInfo

    from core.config import get_settings
    from pipeline.monitor import daily_summary
    from pipeline.notify import make_notifier, notify
    from pipeline.validate.rules import staleness_policy

    settings = get_settings()
    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal
    now = dt.datetime.now(dt.UTC)
    with session_factory() as session, session.begin():
        text = daily_summary(session, now, ZoneInfo(settings.timezone), staleness_policy())
        if not send:
            print(text)
            return 0
        ok = notify(session, make_notifier(settings), "daily_summary", text, now=now)
    print("sent" if ok else "sending failed (see the notification table)")
    return 0 if ok else 1


def _status(session_factory: Callable[[], Session] | None) -> int:
    from core.freshness import institution_freshness
    from pipeline.validate.rules import staleness_policy

    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal
    with session_factory() as session:
        states = institution_freshness(session, policy=staleness_policy())
    for f in states.values():
        if f.state == "no_sources":
            continue
        print(f"{f.short_name:<18} {f.state}")
        for s in f.stale_sources:
            label = "/".join(x for x in (s.kind, s.variant) if x)
            print(f"    source {s.source_id} {label}: {'; '.join(s.reasons)}")
    without = sum(f.state == "no_sources" for f in states.values())
    print(f"({without} institutions have no monitored source yet)")
    return 0


def _select(session: Session, args: argparse.Namespace) -> list[int]:
    if args.source is not None:
        if session.get(Source, args.source) is None:
            raise LookupError(f"no source with id {args.source}")
        return [args.source]
    if args.institution:
        return [s.id for s in institution_sources(session, args.institution)]
    return [s.id for s in due_sources(session, dt.datetime.now(dt.UTC))]


if __name__ == "__main__":
    sys.exit(main())
