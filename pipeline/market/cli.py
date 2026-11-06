"""`python -m pipeline market ...` commands."""

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

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


def _returns(args: argparse.Namespace) -> int:
    from core.cma.series import (
        Inputs,
        SeriesConfig,
        build_returns,
        coverage_table,
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
    frame, coverage = build_returns(Inputs(observations, savings), config)
    rows = coverage_table(coverage)
    widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in rows[0] if k != "notes"}
    print("  ".join(k.ljust(w) for k, w in widths.items()) + "  notes")
    for r in rows:
        print("  ".join(str(r[k]).ljust(w) for k, w in widths.items()) + "  " + r["notes"])
    if args.csv:
        frame.to_csv(args.csv, index_label="month_end", float_format="%.8f")
        print(f"monthly log returns: {args.csv}")
    return 0
