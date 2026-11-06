"""`python -m pipeline market ...` commands."""

import argparse
import sys
from collections.abc import Callable

from pipeline.market.client import MarketClient, MarketDataError, VnstockClient


def add_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    market = sub.add_parser("market", help="VNCMA market and macro data (vnstock)")
    msub = market.add_subparsers(dest="market_command", required=True)
    msub.add_parser("check", help="vnstock version, tier and one VN30 close (live)")


def run(args: argparse.Namespace, client_factory: Callable[[], MarketClient] | None) -> int:
    if args.market_command == "check":
        return _check(client_factory or VnstockClient)
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
