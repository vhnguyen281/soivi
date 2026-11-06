"""`python -m pipeline market ...` commands."""

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from pathlib import Path

from pipeline.market.client import MarketClient, MarketDataError, VnstockClient


def add_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    market = sub.add_parser("market", help="VNCMA market and macro data (vnstock)")
    msub = market.add_subparsers(dest="market_command", required=True)
    msub.add_parser("check", help="vnstock version, tier and one VN30 close (live)")
    probe = msub.add_parser("probe", help="try every vnstock call VNCMA needs (live, slow)")
    probe.add_argument("--only", help="run only calls whose name contains this text")
    probe.add_argument("--pause", type=float, default=1.0, help="seconds between calls")
    probe.add_argument("--out", type=Path, default=Path("docs/vncma/probe-results.md"))
    probe.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/vnstock"))


def run(args: argparse.Namespace, client_factory: Callable[[], MarketClient] | None) -> int:
    if args.market_command == "check":
        return _check(client_factory or VnstockClient)
    if args.market_command == "probe":
        return _probe(args, client_factory or VnstockClient)
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
