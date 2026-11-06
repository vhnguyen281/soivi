"""`python -m pipeline market ...` commands."""

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pipeline.market.client import MarketClient, MarketDataError, VnstockClient

if TYPE_CHECKING:
    from pipeline.market.source import Fetcher


def add_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    market = sub.add_parser("market", help="VNCMA market and macro data (vnstock)")
    msub = market.add_subparsers(dest="market_command", required=True)
    msub.add_parser("check", help="vnstock version, tier and one VN30 close (live)")
    probe = msub.add_parser("probe", help="try every vnstock call VNCMA needs (live, slow)")
    probe.add_argument("--only", help="run only calls whose name contains this text")
    probe.add_argument("--pause", type=float, default=1.0, help="seconds between calls")
    probe.add_argument("--out", type=Path, default=Path("docs/vncma/probe-results.md"))
    probe.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/vnstock"))
    ingest = msub.add_parser("ingest", help="fetch every active series; store monthly values")
    ingest.add_argument("--series", help="comma-separated series codes (default: all active)")
    returns = msub.add_parser("returns", help="monthly total returns by asset class + coverage")
    returns.add_argument("--csv", type=Path, help="also write the monthly log returns here")
    msub.add_parser("stats", help="volatilities and the correlation matrix (VNCMA Prompt 6)")
    compute = msub.add_parser("compute", help="building blocks: store a VNCMA run (Prompt 7)")
    compute.add_argument("--by", required=True, help="your name (stored with the run)")
    compute.add_argument("--config", type=Path, default=Path("data/cma/config.yaml"))
    compute.add_argument("--as-of", type=dt.date.fromisoformat, help="month end (default: latest)")
    report = msub.add_parser("report", help="write the draft (xlsx, json, md) of a run (Prompt 8)")
    report.add_argument("--run", type=int, help="cma_run id (default: the latest)")
    report.add_argument("--out", type=Path, default=Path("reports/vncma"))
    manual = msub.add_parser("manual", help="enter one value by hand (with its source)")
    manual.add_argument("--series", required=True)
    manual.add_argument("--period", required=True, help="YYYY-MM (daily: YYYY-MM-DD, yearly: YYYY)")
    manual.add_argument("--value", required=True, type=Decimal)
    manual.add_argument("--source-url", required=True, help="the page the value was read from")
    manual.add_argument("--entered-by", required=True, help="your name (provenance)")
    manual.add_argument("--note", required=True, help="why it was entered by hand")
    manual.add_argument("--obs-date", type=dt.date.fromisoformat, help="date of the value")


def run(args: argparse.Namespace, client_factory: Callable[[], MarketClient] | None) -> int:
    if args.market_command == "check":
        return _check(client_factory or VnstockClient)
    if args.market_command == "probe":
        return _probe(args, client_factory or VnstockClient)
    if args.market_command == "ingest":
        return _ingest(args, client_factory or VnstockClient)
    if args.market_command == "manual":
        return _manual(args)
    if args.market_command == "returns":
        return _returns(args)
    if args.market_command == "stats":
        return _stats()
    if args.market_command == "compute":
        return _compute(args)
    if args.market_command == "report":
        return _report(args)
    raise AssertionError(args.market_command)


def _check(client_factory: Callable[[], MarketClient]) -> int:
    try:
        client = client_factory()
        status = client.status()
    except MarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"vnstock {status.version}")
    print(f"tier: {status.tier} (plan expires {status.expires_at or 'unknown'})")
    if status.release_expires_on:
        print(
            f"this release works until {status.release_expires_on} "
            f"({status.release_days_left} days left)"
        )
    if not (status.authenticated and status.active):
        print("error: not logged in or plan inactive: run `vnstock register`", file=sys.stderr)
        return 1
    try:
        vn30 = client.latest_index_close("VN30")
    except MarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"VN30 close {vn30.date.isoformat()}: {vn30.close} (source {vn30.source})")
    return 0


def _probe(args: argparse.Namespace, client_factory: Callable[[], MarketClient]) -> int:
    from pipeline.market import probe

    if args.pause < 0.1:
        print("error: --pause below 0.1 s is above the Golden rate limit", file=sys.stderr)
        return 2
    try:
        client = client_factory()
        status = client.status()
    except MarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not (status.authenticated and status.active):
        print("error: not logged in or plan inactive: run `vnstock register`", file=sys.stderr)
        return 1
    spec_list = [s for s in probe.specs() if not args.only or args.only in s.name]
    results = probe.run_probe(client, spec_list, args.fixtures, pause=args.pause)
    header = [
        f"run: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}",
        f"vnstock {status.version}, tier {status.tier}",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(probe.render(results, header), "utf-8")
    ok = sum(r.ok for r in results)
    print(f"{ok}/{len(results)} calls work; report: {args.out}; fixtures: {args.fixtures}/")
    return 0


class _LazyFetchers(dict[str, "Fetcher"]):
    """Builds a provider's fetcher on first use, so a run of HNX series never imports vnstock."""

    def __init__(self, client_factory: Callable[[], MarketClient]) -> None:
        super().__init__()
        self.client_factory = client_factory
        self.closers: list[Callable[[], None]] = []

    def get(self, key: str, default: "Fetcher | None" = None) -> "Fetcher | None":  # type: ignore[override]
        if key not in self:
            built = self._build(key)
            if built is None:
                return default
            self[key] = built
        return self[key]

    def _build(self, provider: str) -> "Fetcher | None":
        from pipeline.fetch.polite import PoliteHttp
        from pipeline.market.source import (
            HnxFetcher,
            SbvFetcher,
            ShillerFetcher,
            SjcFetcher,
            VnstockFetcher,
            WorldBankFetcher,
            hnx_ssl_context,
        )

        if provider == "vnstock":
            return VnstockFetcher(self.client_factory())
        if provider == "hnx":
            http = PoliteHttp(verify=hnx_ssl_context())
            self.closers.append(http.close)
            return HnxFetcher(http)
        if provider in ("sjc", "sbv"):
            http = PoliteHttp()
            self.closers.append(http.close)
            return SjcFetcher(http) if provider == "sjc" else SbvFetcher(http)
        if provider in ("worldbank", "shiller"):
            http = PoliteHttp()
            self.closers.append(http.close)
            return WorldBankFetcher(http) if provider == "worldbank" else ShillerFetcher(http)
        return None


def _ingest(args: argparse.Namespace, client_factory: Callable[[], MarketClient]) -> int:
    from core.db import SessionLocal
    from pipeline.fetch.storage import MinioStore
    from pipeline.market.ingest import ingest

    codes = [c.strip() for c in args.series.split(",") if c.strip()] if args.series else None
    fetchers = _LazyFetchers(client_factory)
    try:
        results = ingest(SessionLocal, MinioStore(), fetchers, codes)
    except MarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        for close in fetchers.closers:
            close()
    failed = [r for r in results if r.status == "failed"]
    new = sum(r.new for r in results)
    revised = sum(r.revised for r in results)
    print(f"{len(results)} groups: {new} new values, {revised} revised, {len(failed)} failed")
    return 1 if failed else 0


def _manual(args: argparse.Namespace) -> int:
    from core.db import session_scope
    from pipeline.fetch.storage import MinioStore
    from pipeline.market.manual import ManualEntry, enter

    entry = ManualEntry(
        series=args.series,
        period=args.period,
        value=args.value,
        source_url=args.source_url,
        entered_by=args.entered_by,
        note=args.note,
        obs_date=args.obs_date,
    )
    try:
        with session_scope() as session:
            print(enter(session, MinioStore(), entry, dt.datetime.now(dt.UTC)))
    except MarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _load_returns() -> tuple[Any, Any]:
    from core.cma.series import (
        Inputs,
        SeriesConfig,
        build_returns,
        load_observations,
        load_savings_12m,
        month_index,
        needed_codes,
    )
    from core.db import SessionLocal

    config = SeriesConfig()
    with SessionLocal() as session:
        observations = load_observations(session, needed_codes(config))
        ends = [s.index.max() for s in observations.values() if not s.empty]
        starts = [s.index.min() for s in observations.values() if not s.empty]
        months = month_index(min(starts), max(ends)) if ends else []
        savings = load_savings_12m(session, config.big_banks, months)
    return build_returns(Inputs(observations, savings), config)


def _returns(args: argparse.Namespace) -> int:
    from core.cma.series import coverage_table

    frame, coverage = _load_returns()
    rows = coverage_table(coverage)
    widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in rows[0] if k != "notes"}
    print("  ".join(k.ljust(w) for k, w in widths.items()) + "  notes")
    for r in rows:
        print("  ".join(str(r[k]).ljust(w) for k, w in widths.items()) + "  " + r["notes"])
    if args.csv:
        frame.to_csv(args.csv, index_label="month_end", float_format="%.8f")
        print(f"monthly log returns: {args.csv}")
    return 0


def _stats() -> int:
    from core.cma.stats import compute_stats, summary_rows

    frame, _ = _load_returns()
    stats = compute_stats(frame)
    print(f"{'class':12} {'vol':>7} {'raw':>7} {'phi':>5} {'months':>6}")
    for r in summary_rows(stats):
        print(
            f"{r['class']:12} {r['vol']:7.2%} {r['vol_raw']:7.2%} {r['phi']:5.2f} {r['months']:6d}"
        )
    print(
        f"\nLedoit-Wolf shrinkage {stats.shrinkage:.3f} over {stats.common_months} common months; "
        f"repaired: {stats.repaired}"
    )
    print(stats.corr.round(2).to_string())
    for note in stats.notes:
        print(f"note: {note}")
    return 0


def _compute(args: argparse.Namespace) -> int:
    import pandas as pd

    from core.cma.blocks import BlockError
    from core.cma.config import ConfigError, load_config
    from core.cma.run import create_run
    from core.db import SessionLocal

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        for e in exc.errors:
            print(f"error: {e}", file=sys.stderr)
        return 1
    as_of = pd.Timestamp(args.as_of) if args.as_of else None
    try:
        with SessionLocal() as session, session.begin():
            run = create_run(session, cfg, args.by, as_of)
            run_id, out = run.id, run.output
    except BlockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"cma_run {run_id}: as of {out['as_of']}, methodology {out['methodology_version']}")
    print("\nmacro")
    for name, m in out["macro"].items():
        print(f"  {name:10} {m['value']:6.2f}  {m['derivation']}")
    print(
        f"\n{'class':12} {'model':>6} {'adj':>5} {'final':>6} {'arith':>6} {'vol':>6} "
        f"{'adverse':>7} {'favour':>7}  {'band 80%':>13}"
    )
    for cls, c in out["classes"].items():
        vol = "" if c["vol"] is None else f"{100 * c['vol']:.1f}"
        arith = "" if c["arithmetic"] is None else f"{c['arithmetic']:.2f}"
        band = "" if c["band_low"] is None else f"{c['band_low']:.1f}..{c['band_high']:.1f}"
        s = c["scenarios"]
        print(
            f"{cls:12} {c['model']:6.2f} {c['adjustment']:5.2f} {c['final']:6.2f} {arith:>6} "
            f"{vol:>6} {s['adverse']:7.2f} {s['favourable']:7.2f}  {band:>13}"
        )
    print()
    for line in out["checks"]:
        print(f"check {line}")
    return 0


def _report(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from core.cma.release import next_version, previous_payload, release_of
    from core.cma.report import payload, write_all
    from core.db import SessionLocal
    from core.models import CmaRun

    with SessionLocal() as session:
        query = select(CmaRun).order_by(CmaRun.id.desc())
        run = session.get(CmaRun, args.run) if args.run else session.scalar(query)
        if run is None:
            print("error: no such run: run `market compute` first", file=sys.stderr)
            return 1
        release = release_of(session, run.id)
        doc = release.payload if release else payload(run, f"{next_version(session, run)}-draft")
        previous = previous_payload(session, release) if release else previous_payload(session)
        for path in write_all(run, doc, args.out, previous):
            print(path)
    return 0
