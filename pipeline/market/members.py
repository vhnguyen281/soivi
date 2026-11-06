"""Index aggregates built from the current members of a vnstock index (VNCMA Prompt 7).

vnstock has no dividend yield for any index and no P/E for VNMID/VNSML, so both are
built bottom-up from the index's current members (owner's decision 2026-11-06):

- report "summary": today's cap-weighted dividend yield, Σ(D/P_i * cap_i) ÷ Σ cap_i,
  in % per year, and today's aggregate P/E, Σ cap_i ÷ Σ earnings_i, where
  earnings_i = cap_i ÷ P/E_i (losses count as negative earnings). One
  `Market().equity(s).summary()` call per member.
- report "ratio": the same aggregate P/E for each closed quarter since 2018, from
  `Fundamental().equity(s).ratio()` (quarter-end market cap and P/E). A quarter is
  closed 45 days after its end (the reporting deadline), and is stored only when at
  least half of today's members have data for it; earlier quarters are gaps.

Survivorship: today's members are used for every quarter, so the history describes
today's basket. P/E_0 and P/E_target come from the same series, so the level bias
cancels in ln(P/E_target ÷ P/E_0).

A member whose call fails or has no market cap is listed under "missing" in the
payload. If members with data hold less than MIN_COVERAGE of the members, the
fetch raises: an aggregate over a few names is not the index.
"""

import datetime as dt
import math
import re
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from pipeline.market.client import MarketDataError, Step, describe
from pipeline.market.monthend import Point

REPORTS = frozenset({"summary", "ratio"})
MIN_COVERAGE = 0.8  # share of today's members that must have data (summary)
MIN_QUARTER_COVERAGE = 0.5  # share of today's members with data for a past quarter (ratio)
REPORTING_DAYS = 45
RATIO_IDS = {"RT_VALUE_PE": "pe", "RT_VALUE_MARKET_CAP": "market_cap"}
QUARTER = re.compile(r"(\d{4})-Q([1-4])")

Call = Callable[[Sequence[Step]], Any]


def members_chain(index: str) -> list[Step]:
    return [("Reference", (), {}), ("index", None, {}), ("members", (index,), {})]


def summary_chain(symbol: str) -> list[Step]:
    return [("Market", (), {}), ("equity", (symbol,), {}), ("summary", (), {})]


def ratio_chain(symbol: str) -> list[Step]:
    return [("Fundamental", (), {}), ("equity", (symbol,), {}), ("ratio", (), {})]


def quarter_end(label: str) -> dt.date | None:
    m = QUARTER.fullmatch(label.strip())
    if not m:
        return None
    year, q = int(m.group(1)), int(m.group(2))
    month = q * 3
    return (dt.date(year + (month == 12), month % 12 + 1, 1)) - dt.timedelta(days=1)


def last_closed_quarter(today: dt.date) -> dt.date:
    """The last quarter end at least REPORTING_DAYS before today."""
    day = today - dt.timedelta(days=REPORTING_DAYS + 1)
    month = ((day.month - 1) // 3) * 3  # the quarter before day's quarter ends in this month
    if month == 0:
        return dt.date(day.year - 1, 12, 31)
    return dt.date(day.year, month + 1, 1) - dt.timedelta(days=1)


def _number(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def read_members(call: Call, index: str) -> list[str]:
    chain = members_chain(index)
    df = call(chain)
    if df is None or "symbol" not in getattr(df, "columns", []) or len(df) == 0:
        raise MarketDataError(f"{describe(chain)} returned no members")
    return sorted({str(s).strip().upper() for s in df["symbol"] if str(s).strip()})


def aggregate_pe(caps_and_pes: Sequence[tuple[float, float]]) -> float | None:
    """Σ cap ÷ Σ (cap ÷ P/E); None if total earnings are not positive."""
    caps = sum(c for c, _ in caps_and_pes)
    earnings = sum(c / pe for c, pe in caps_and_pes if pe != 0)
    if earnings <= 0 or caps <= 0:
        return None
    return caps / earnings


def _d(x: float) -> Decimal:
    return Decimal(repr(round(x, 8)))


def summary(
    call: Call, index: str, today: dt.date
) -> tuple[dict[str, Any], dict[str, list[Point]]]:
    symbols = read_members(call, index)
    rows: dict[str, dict[str, float | None]] = {}
    missing: dict[str, str] = {}
    for s in symbols:
        try:
            df = call(summary_chain(s))
        except MarketDataError as exc:
            if exc.transient:  # still failing after retries: stop, do not skip the member
                raise
            missing[s] = str(exc)[:200]
            continue
        if df is None or len(df) == 0:
            missing[s] = "empty summary"
            continue
        first = df.iloc[0]
        cap = _number(first.get("market_cap"))
        if cap is None or cap <= 0:
            missing[s] = "no market cap"
            continue
        rows[s] = {
            "market_cap": cap,
            "dividend_yield": _number(first.get("dividend_yield")),
            "pe": _number(first.get("pe")),
        }
    _check_coverage(index, len(rows), len(symbols))
    caps = sum(r["market_cap"] or 0.0 for r in rows.values())
    dp = sum((r["dividend_yield"] or 0.0) * (r["market_cap"] or 0.0) for r in rows.values()) / caps
    pe = aggregate_pe(
        [(r["market_cap"] or 0.0, r["pe"]) for r in rows.values() if r["pe"] is not None]
    )
    if pe is None:
        raise MarketDataError(f"{index} members: total earnings are not positive")
    payload = {
        "index": index,
        "report": "summary",
        "date": today.isoformat(),
        "members": symbols,
        "missing": missing,
        "rows": rows,
    }
    points = {
        "dividend_yield": [Point(today, _d(dp * 100))],
        "pe": [Point(today, _d(pe))],
    }
    return payload, points


def ratio(call: Call, index: str, today: dt.date) -> tuple[dict[str, Any], dict[str, list[Point]]]:
    symbols = read_members(call, index)
    closed = last_closed_quarter(today)
    rows: dict[str, dict[str, dict[str, float]]] = {}
    missing: dict[str, str] = {}
    for s in symbols:
        try:
            df = call(ratio_chain(s))
        except MarketDataError as exc:
            if exc.transient:  # still failing after retries: stop, do not skip the member
                raise
            missing[s] = str(exc)[:200]
            continue
        if df is None or len(df) == 0 or not {"period", "id", "value"} <= set(df.columns):
            missing[s] = "no ratio table"
            continue
        by_quarter: dict[str, dict[str, float]] = {}
        for period, id_, value in zip(df["period"], df["id"], df["value"], strict=True):
            name = RATIO_IDS.get(str(id_))
            end = quarter_end(str(period))
            number = _number(value)
            if name is None or end is None or end > closed or number is None:
                continue
            by_quarter.setdefault(str(period), {})[name] = number
        if not by_quarter:
            missing[s] = "no quarterly P/E or market cap"
            continue
        rows[s] = dict(sorted(by_quarter.items()))
    _check_coverage(index, len(rows), len(symbols))
    quarters = sorted({q for r in rows.values() for q in r}, key=lambda q: quarter_end(q) or closed)
    points: list[Point] = []
    for q in quarters:
        pairs = [
            (r[q]["market_cap"], r[q]["pe"])
            for r in rows.values()
            if q in r and r[q].get("market_cap", 0) > 0 and "pe" in r[q]
        ]
        if len(pairs) < MIN_QUARTER_COVERAGE * len(symbols):
            continue
        pe = aggregate_pe(pairs)
        end = quarter_end(q)
        if pe is not None and end is not None:
            points.append(Point(end, _d(pe)))
    if not points:
        raise MarketDataError(f"{index} members: no quarter with enough members")
    payload = {
        "index": index,
        "report": "ratio",
        "closed_through": closed.isoformat(),
        "members": symbols,
        "missing": missing,
        "rows": rows,
    }
    return payload, {"pe": points}


def _check_coverage(index: str, have: int, total: int) -> None:
    if total == 0 or have < MIN_COVERAGE * total:
        raise MarketDataError(
            f"{index} members: only {have} of {total} have data (need {MIN_COVERAGE:.0%})"
        )
