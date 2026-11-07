import math

import numpy as np
import pandas as pd
import pytest

from core.funds.stats import (
    annualised,
    class_annualised,
    compute,
    max_drawdown,
    summary,
    volatility,
)

AS_OF = pd.Timestamp("2026-10-31")


def monthly(start: str, growth: float, months: int) -> pd.Series:
    idx = pd.date_range(start, periods=months, freq="ME")
    return pd.Series([100 * (1 + growth) ** i for i in range(months)], index=idx)


def test_annualised_uses_exact_month_ends_and_never_fills() -> None:
    s = monthly("2020-10-31", 0.01, 73)  # 2020-10 .. 2026-10
    assert annualised(s, AS_OF, 1) == pytest.approx(100 * (1.01**12 - 1))
    assert annualised(s, AS_OF, 5) == pytest.approx(100 * (1.01**12 - 1))
    assert annualised(s.drop(pd.Timestamp("2025-10-31")), AS_OF, 1) is None
    assert annualised(s, AS_OF, 10) is None


def test_volatility_and_drawdown() -> None:
    flat = monthly("2022-01-31", 0.0, 58)
    assert volatility(flat, AS_OF) == pytest.approx(0.0)
    short = monthly("2024-06-30", 0.01, 29)
    assert volatility(short, AS_OF) is None
    s = monthly("2022-01-31", 0.0, 58)
    s.iloc[30:] = 70.0
    assert max_drawdown(s, AS_OF) == pytest.approx(-30.0)


def test_class_annualised_needs_every_month() -> None:
    logs = pd.Series(math.log(1.01), index=pd.date_range("2020-01-31", "2026-10-31", freq="ME"))
    assert class_annualised(logs, AS_OF, 3) == pytest.approx(100 * (1.01**12 - 1))
    assert class_annualised(logs.drop(pd.Timestamp("2025-03-31")), AS_OF, 3) is None


def test_summary_quartiles() -> None:
    assert summary([]) is None
    s = summary([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s == {"n": 5, "min": 1.0, "p25": 2.0, "p50": 3.0, "p75": 4.0, "max": 5.0}


def test_groups_and_share_beating_the_benchmark() -> None:
    universe = [
        {"ticker": "AAA", "code": "fund_nav_aaa", "group": "equity_fund", "manager": "X"},
        {"ticker": "BBB", "code": "fund_nav_bbb", "group": "equity_fund", "manager": "Y"},
        {"ticker": "CCC", "code": "fund_nav_ccc", "group": "bond_fund", "manager": "X"},
        {"ticker": "NONE", "code": "fund_nav_none", "group": "etf", "manager": ""},
    ]
    levels = {
        "fund_nav_aaa": monthly("2020-10-31", 0.012, 73),  # ~15.4%/yr
        "fund_nav_bbb": monthly("2020-10-31", 0.005, 73),  # ~6.2%/yr
        "fund_nav_ccc": monthly("2020-10-31", 0.006, 73),
    }
    idx = pd.date_range("2018-01-31", "2026-10-31", freq="ME")
    bench = {
        "eq_large": pd.Series(np.log(1.008), index=idx),
        "cash_vnd": pd.Series(np.log(1.004), index=idx),
    }
    out = compute(universe, levels, bench, AS_OF)
    eq = out["groups"]["equity_fund"]
    assert eq["count"] == 2
    assert eq["horizons"]["3"]["stats"]["n"] == 2
    assert eq["horizons"]["3"]["beat"] == 0.5  # one of two beats ~10%/yr
    assert out["groups"]["bond_fund"]["horizons"]["1"]["beat"] == 1.0
    assert out["groups"]["etf"]["count"] == 0
    assert out["groups"]["etf"]["horizons"]["1"]["stats"] is None
    assert out["benchmarks"]["balanced"]["1"] is not None
    assert {f["ticker"] for f in out["funds"]} == {"AAA", "BBB", "CCC"}
