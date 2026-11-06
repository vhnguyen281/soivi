"""Monthly total-return series on synthetic data with known answers (VNCMA Prompt 5)."""

import math

import numpy as np
import pandas as pd
import pytest

from core.cma.series import (
    Inputs,
    SeriesConfig,
    bond_returns,
    build_returns,
    carry_returns,
    equal_weight,
    par_bond_risk,
    price_returns,
    splice_cash,
    to_vnd,
)


def monthly(values: list[float], start: str = "2015-01-31") -> pd.Series:
    return pd.Series(
        values, index=pd.date_range(start, periods=len(values), freq="ME"), dtype=float
    )


def test_constant_yield_earns_y_over_12() -> None:
    returns = bond_returns(monthly([5.0] * 13), years=10)
    assert len(returns) == 12
    assert np.allclose(returns, 0.05 / 12)


def test_par_bond_duration_matches_the_textbook_value() -> None:
    duration, convexity = par_bond_risk(0.05, 10)
    assert duration == pytest.approx(7.7217, abs=1e-4)  # 10y 5% annual-coupon par bond
    assert convexity == pytest.approx(74.998, abs=1e-3)  # checked by finite differences


def test_rising_yield_loses_about_duration_times_the_move() -> None:
    (r,) = bond_returns(monthly([5.0, 5.5]), years=10)
    duration, convexity = par_bond_risk(0.05, 10)
    assert r == pytest.approx(0.05 / 12 - duration * 0.005 + 0.5 * convexity * 0.005**2)
    assert r < -0.03


def test_constant_rate_carry_and_a_gap_stays_missing() -> None:
    assert np.allclose(carry_returns(monthly([6.0] * 4)), 0.005)
    levels = monthly([100.0, 101.0, 102.0, 103.0]).drop(pd.Timestamp("2015-03-31"))
    returns = price_returns(levels)
    assert list(returns.index.strftime("%Y-%m")) == ["2015-02"]  # Mar and Apr need March


def test_usd_asset_in_vnd_compounds_both_moves() -> None:
    flat_usd = monthly([0.0, 0.0], "2020-02-29")
    fx = monthly([25000.0, 25250.0, 25250.0], "2020-01-31")
    assert to_vnd(flat_usd, fx).tolist() == pytest.approx([0.01, 0.0])


def test_equal_weight_needs_enough_funds() -> None:
    a = monthly([0.01, 0.02, np.nan])
    b = monthly([0.03, np.nan, np.nan])
    assert equal_weight([a, b], 2).tolist() == pytest.approx([0.02])
    assert equal_weight([a, b], 1).tolist() == pytest.approx([0.02, 0.02])


def test_cash_splice_shifts_the_proxy_by_the_overlap_spread() -> None:
    proxy = monthly([4.0, 4.0, 4.0, 4.5])
    savings = monthly([5.0, 5.4], "2015-03-31")  # overlap Mar-Apr: spreads 1.0 and 0.9
    rate, spread, overlap = splice_cash(savings, proxy, min_overlap=2)
    assert (spread, overlap) == (pytest.approx(0.95), 2)
    assert rate.tolist() == pytest.approx([4.95, 4.95, 5.0, 5.4])
    rate, spread, _ = splice_cash(savings, proxy, min_overlap=12)  # too little overlap
    assert spread == 0.0 and rate.tolist() == pytest.approx([4.0, 4.0, 5.0, 5.4])


def test_build_returns_coverage_and_dividend_yield() -> None:
    n = 130
    inputs = Inputs(
        {
            "vn30_close": monthly([1000.0] * n),
            "hnx_par_10y": monthly([4.0] * n),
            "interbank_3m": monthly([6.0] * n),
        }
    )
    frame, coverage = build_returns(inputs, SeriesConfig(dp_eq_large=0.03))
    assert np.allclose(frame["eq_large"].dropna(), math.log1p(0.03 / 12))
    assert np.allclose(frame["gov_bond"].dropna(), math.log1p(0.04 / 12))
    assert np.allclose(frame["cash_vnd"].dropna(), math.log1p(0.06 / 12))  # no savings: spread 0
    by_class = {c.asset_class: c for c in coverage}
    assert (by_class["eq_large"].first, by_class["eq_large"].months) == ("2015-02", n - 1)
    assert by_class["eq_large"].grade == "A" and by_class["eq_large"].missing == 0
    assert by_class["real_estate"].months == 0
    assert "no series" in by_class["real_estate"].notes[0]
    assert by_class["gold"].months == 0  # no inputs: no return, no crash


def test_short_history_is_flagged() -> None:
    _, coverage = build_returns(Inputs({"vn30_close": monthly([1.0] * 50)}))
    eq = next(c for c in coverage if c.asset_class == "eq_large")
    assert "under 10 years (49 months)" in eq.notes
    assert "price only (D/P not set)" in eq.notes
