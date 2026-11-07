"""Fund statistics by group (phase A): derived figures only, never raw NAV series.

For every fund in data/funds/universe.yaml with monthly NAVs (or ETF closes), at a month
end `as_of`:
- annualised return over 1, 3 and 5 years (both month ends must exist; no filling);
- annualised volatility of monthly log returns over the last 36 months (>= 30 needed);
- maximum drawdown over the last 60 months.
Groups (equity, bond, balanced funds, ETFs) report count, quartiles, min and max, and the
share of funds beating the group's benchmark over the same window:
- equity funds and ETFs: VN30 total return (VNCMA eq_large: price + dividend yield);
- bond funds: 12-month deposits (VNCMA cash_vnd);
- balanced funds: 50/50 of the two, rebalanced monthly.
ETF figures are price returns (distributions not included), as the page says.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5)
VOL_MONTHS = 36
VOL_MIN = 30
MDD_MONTHS = 60
GROUPS = ("equity_fund", "bond_fund", "balanced_fund", "etf")
BENCHMARK = {
    "equity_fund": "eq_large",
    "etf": "eq_large",
    "bond_fund": "cash_vnd",
    "balanced_fund": "balanced",
}


def _at(levels: pd.Series, when: pd.Timestamp) -> float | None:
    v = levels.get(when)
    return None if v is None or pd.isna(v) or v <= 0 else float(v)


def annualised(levels: pd.Series, as_of: pd.Timestamp, years: int) -> float | None:
    """Percent a year between the month ends `years` apart; None if either is missing."""
    start = as_of - pd.DateOffset(years=years) + pd.offsets.MonthEnd(0)
    a, b = _at(levels, start), _at(levels, as_of)
    if a is None or b is None:
        return None
    return float(100 * ((b / a) ** (1 / years) - 1))


def volatility(levels: pd.Series, as_of: pd.Timestamp) -> float | None:
    window = levels[
        (levels.index <= as_of) & (levels.index > as_of - pd.DateOffset(months=VOL_MONTHS + 1))
    ]
    full = (
        window.reindex(pd.date_range(window.index.min(), as_of, freq="ME"))
        if len(window)
        else window
    )
    logs = np.log(full / full.shift(1)).dropna()
    if len(logs) < VOL_MIN:
        return None
    return 100 * float(logs.std(ddof=1)) * math.sqrt(12)


def max_drawdown(levels: pd.Series, as_of: pd.Timestamp) -> float | None:
    window = levels[
        (levels.index <= as_of) & (levels.index > as_of - pd.DateOffset(months=MDD_MONTHS))
    ].dropna()
    if len(window) < 12:
        return None
    peak = window.cummax()
    return 100 * float((window / peak - 1).min())


def class_annualised(log_returns: pd.Series, as_of: pd.Timestamp, years: int) -> float | None:
    """Annualised percent from monthly log returns over `years` to as_of (every month needed)."""
    months = pd.date_range(
        as_of - pd.DateOffset(years=years) + pd.offsets.MonthEnd(1), as_of, freq="ME"
    )
    window = log_returns.reindex(months)
    if window.isna().any() or len(window) != 12 * years:
        return None
    return 100 * (math.exp(float(window.sum()) / years) - 1)


def summary(values: Sequence[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    a = np.array(values, dtype=float)
    return {
        "n": len(a),
        "min": float(a.min()),
        "p25": float(np.percentile(a, 25)),
        "p50": float(np.percentile(a, 50)),
        "p75": float(np.percentile(a, 75)),
        "max": float(a.max()),
    }


def compute(
    universe: Sequence[Mapping[str, Any]],
    levels: Mapping[str, pd.Series],
    benchmarks: Mapping[str, pd.Series],
    as_of: pd.Timestamp,
) -> dict[str, Any]:
    """The full statistics payload (the `funds` rows stay internal until each fund's NAV is
    confirmed with its manager in phase B)."""
    bench_logs = dict(benchmarks)
    if "eq_large" in bench_logs and "cash_vnd" in bench_logs:
        both = pd.concat([bench_logs["eq_large"], bench_logs["cash_vnd"]], axis=1).dropna()
        bench_logs["balanced"] = np.log(
            0.5 * np.exp(both.iloc[:, 0]) + 0.5 * np.exp(both.iloc[:, 1])
        )
    bench = {
        k: {str(h): class_annualised(v, as_of, h) for h in HORIZONS} for k, v in bench_logs.items()
    }

    funds = []
    for f in universe:
        s = levels.get(f["code"])
        if s is None or s.empty:
            continue
        s = s[s.index <= as_of]
        returns = {str(h): annualised(s, as_of, h) for h in HORIZONS}
        funds.append(
            {
                "ticker": f["ticker"],
                "group": f["group"],
                "manager": f.get("manager", ""),
                "first": s.index.min().strftime("%Y-%m"),
                "returns": returns,
                "volatility": volatility(s, as_of),
                "max_drawdown": max_drawdown(s, as_of),
            }
        )

    groups: dict[str, Any] = {}
    for g in GROUPS:
        rows = [f for f in funds if f["group"] == g]
        b = bench.get(BENCHMARK[g], {})
        horizons = {}
        for h in map(str, HORIZONS):
            vals = [f["returns"][h] for f in rows if f["returns"][h] is not None]
            target = b.get(h)
            horizons[h] = {
                "stats": summary(vals),
                "benchmark": target,
                "beat": (sum(v > target for v in vals) / len(vals))
                if vals and target is not None
                else None,
            }
        groups[g] = {
            "count": len(rows),
            "benchmark": BENCHMARK[g],
            "horizons": horizons,
            "volatility": summary([f["volatility"] for f in rows if f["volatility"] is not None]),
            "max_drawdown": summary(
                [f["max_drawdown"] for f in rows if f["max_drawdown"] is not None]
            ),
        }
    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "horizons": list(HORIZONS),
        "groups": groups,
        "benchmarks": bench,
        "funds": funds,
    }
