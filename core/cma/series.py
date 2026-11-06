"""Monthly total-return series per asset class (docs/vncma/spec.md §4.1, VNCMA Prompt 5).

Inputs are the current monthly observations (`market_observation`, highest revision)
and approved savings rates. Output: an aligned frame of monthly **log** returns in VND
(one column per asset class) and a coverage table. Floats are used only here, inside
the numeric computation (CLAUDE.md, VNCMA).

Rules, per class (a month's return needs the value of that month and of the month
before; a gap gives a missing return, never a filled one):

- eq_large     VN30 price return + (D/P)/12. D/P is a config value; None = price only.
- eq_midsmall  mean of the VNMID and VNSML price returns + (D/P)/12.
- gov_bond     R_t = y_{t-1}/12 - D*dy + 0.5*C*dy^2 on the HNX 10-year par yield, with D and C
               the modified duration and convexity of a 10-year annual-coupon par bond at y_{t-1}.
- corp_bond    equal-weight mean of the monthly NAV returns of the bond funds that have one
               that month (at least `corp_min_funds`).
- cash_vnd     R_t = rate_{t-1}/12, rate = approved 12-month savings rate (mean over the big
               banks of each bank's median 12M rate at the month end); before that, the
               interbank 3M rate plus the mean savings-minus-interbank spread over the months
               where both exist (the splice).
- usd          USD/VND central rate change, plus the Fed rate as the USD deposit rate.
- gold         World Bank gold (USD/oz, monthly average) in VND at the month-end central rate.
- eq_global    S&P Composite (Shiller, monthly average) price return + (D/P)/12, in VND.
- gold_sjc     reference only: SJC gold bar mid price (VND, month end).
"""

import datetime as dt
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import VersionStatus
from core.models import Institution, MarketObservation, MarketSeries, SavingsRate

# A pandas Series of floats indexed by month-end Timestamps (pandas has no type stubs here).
type MonthlySeries = Any

BIG_BANKS = (
    "AGRIBANK",
    "VIETCOMBANK",
    "VIETINBANK",
    "BIDV",
    "TECHCOMBANK",
    "MB",
    "ACB",
    "VPBANK",
    "SACOMBANK",
    "HDBANK",
)
CORP_BOND_FUNDS = (
    "fund_nav_dcbf",
    "fund_nav_vff",
    "fund_nav_dcip",
    "fund_nav_vndbf",
    "fund_nav_vcbf_fif",
    "fund_nav_pvbf",
    "fund_nav_dfix",
    "fund_nav_vlbf",
    "fund_nav_maff",
    "fund_nav_bvbf",
    "fund_nav_lhbf",
    "fund_nav_hdbond",
)
# Spec §3 grades; a class with less than TEN_YEARS of returns is flagged in the coverage table.
GRADES = {
    "cash_vnd": "B",
    "gov_bond": "B",
    "corp_bond": "C",
    "eq_large": "A",
    "eq_midsmall": "B",
    "gold": "B",
    "usd": "A",
    "eq_global": "A",
    "real_estate": "C",
    "gold_sjc": "B",
}
TEN_YEARS = 120


@dataclass(frozen=True)
class SeriesConfig:
    dp_eq_large: float | None = None  # dividend yield, decimal per year; None = price only
    dp_eq_midsmall: float | None = None
    gov_bond_years: int = 10
    corp_min_funds: int = 2
    cash_proxy: str = "interbank_3m"
    # The savings-minus-proxy spread is used only with at least this many overlapping months;
    # one month (Oct 2026, interbank unusually high) gave -1.68 pp, which is not credible.
    cash_min_overlap: int = 12
    big_banks: tuple[str, ...] = BIG_BANKS


@dataclass
class Coverage:
    asset_class: str
    inputs: list[str]
    first: str | None = None
    last: str | None = None
    months: int = 0
    missing: int = 0  # months without a return between first and last
    grade: str = ""
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- loading


def month_index(first: pd.Timestamp, last: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(first, last, freq="ME")


def load_observations(session: Session, codes: Iterable[str]) -> dict[str, MonthlySeries]:
    """code -> current (highest revision) value per period end, as floats."""
    latest = (
        select(
            MarketObservation.series_id,
            MarketObservation.period_end,
            func.max(MarketObservation.revision).label("revision"),
        )
        .group_by(MarketObservation.series_id, MarketObservation.period_end)
        .subquery()
    )
    rows = session.execute(
        select(MarketSeries.code, MarketObservation.period_end, MarketObservation.value)
        .join(MarketSeries, MarketSeries.id == MarketObservation.series_id)
        .join(
            latest,
            (MarketObservation.series_id == latest.c.series_id)
            & (MarketObservation.period_end == latest.c.period_end)
            & (MarketObservation.revision == latest.c.revision),
        )
        .where(MarketSeries.code.in_(list(codes)))
    ).all()
    out: dict[str, dict[pd.Timestamp, float]] = {}
    for code, end, value in rows:
        out.setdefault(code, {})[pd.Timestamp(end)] = float(value)
    return {code: pd.Series(v).sort_index() for code, v in out.items()}


def load_savings_12m(
    session: Session, banks: Sequence[str], month_ends: Iterable[pd.Timestamp]
) -> MonthlySeries:
    """Mean over `banks` of each bank's median approved 12-month rate (not CDs) valid at
    the end of each month, in percent per year. Months with no bank are left out."""
    rows = session.execute(
        select(
            Institution.short_name,
            SavingsRate.rate_pct,
            SavingsRate.valid_from,
            SavingsRate.valid_to,
        )
        .join(Institution, Institution.id == SavingsRate.institution_id)
        .where(
            Institution.short_name.in_(list(banks)),
            SavingsRate.term_months == 12,
            SavingsRate.term_days == 0,
            SavingsRate.is_cd.is_(False),
            SavingsRate.status.in_([VersionStatus.APPROVED, VersionStatus.SUPERSEDED]),
            SavingsRate.valid_from.is_not(None),
        )
    ).all()
    values: dict[pd.Timestamp, float] = {}
    for end in month_ends:
        cutoff = dt.datetime.combine(end.date(), dt.time.max, tzinfo=dt.UTC)
        by_bank: dict[str, list[float]] = {}
        for bank, rate, start, stop in rows:
            if start is not None and start <= cutoff and (stop is None or stop > cutoff):
                by_bank.setdefault(bank, []).append(float(rate))
        if by_bank:
            values[end] = float(np.mean([np.median(v) for v in by_bank.values()]))
    return pd.Series(values, dtype=float).sort_index()


# --------------------------------------------------------------------------- building blocks


def _monthly(series: MonthlySeries) -> MonthlySeries:
    """On a full month-end index, so a missing month stays missing (no filling)."""
    if series.empty:
        return series
    return series.reindex(month_index(series.index.min(), series.index.max()))


def price_returns(levels: MonthlySeries) -> MonthlySeries:
    """Simple returns from consecutive month-end levels; NaN across a gap."""
    full = _monthly(levels)
    return (full / full.shift(1) - 1).dropna()


def par_bond_risk(yield_: float, years: int) -> tuple[float, float]:
    """(modified duration, convexity) of an annual-coupon par bond at `yield_` (decimal)."""
    v = 1.0 / (1.0 + yield_)
    flows = [(t, yield_ + (1.0 if t == years else 0.0)) for t in range(1, years + 1)]
    price = sum(cf * v**t for t, cf in flows)
    macaulay = sum(t * cf * v**t for t, cf in flows) / price
    convexity = sum(t * (t + 1) * cf * v ** (t + 2) for t, cf in flows) / price
    return macaulay * v, convexity


def bond_returns(yields_pct: MonthlySeries, years: int) -> MonthlySeries:
    """R_t = y_{t-1}/12 - D*dy + 0.5*C*dy^2 (spec §4.1), yields in percent per year."""
    y = _monthly(yields_pct) / 100.0
    out = {}
    for t in range(1, len(y)):
        y0, y1 = y.iloc[t - 1], y.iloc[t]
        if math.isnan(y0) or math.isnan(y1):
            continue
        duration, convexity = par_bond_risk(y0, years)
        dy = y1 - y0
        out[y.index[t]] = y0 / 12 - duration * dy + 0.5 * convexity * dy**2
    return pd.Series(out, dtype=float)


def carry_returns(rate_pct: MonthlySeries) -> MonthlySeries:
    """R_t = rate_{t-1}/12: a deposit earns the rate known at the start of the month."""
    full = _monthly(rate_pct) / 100.0
    return (full.shift(1) / 12).dropna()


def to_vnd(returns_usd: MonthlySeries, usdvnd: MonthlySeries) -> MonthlySeries:
    fx = price_returns(usdvnd)
    both = pd.concat([returns_usd, fx], axis=1, join="inner").dropna()
    return (1 + both.iloc[:, 0]) * (1 + both.iloc[:, 1]) - 1


def equal_weight(returns: Sequence[MonthlySeries], min_count: int) -> MonthlySeries:
    if not returns:
        return pd.Series(dtype=float)
    frame = pd.concat(list(returns), axis=1)
    mean = frame.mean(axis=1, skipna=True)
    return mean[frame.notna().sum(axis=1) >= min_count]


def splice_cash(
    savings_pct: MonthlySeries, proxy_pct: MonthlySeries, min_overlap: int = 1
) -> tuple[MonthlySeries, float, int]:
    """(rate, spread, overlap months): savings where they exist; before that the proxy plus
    the mean savings-minus-proxy spread over the overlapping months, or no spread when
    fewer than `min_overlap` months overlap."""
    overlap = pd.concat([savings_pct, proxy_pct], axis=1, join="inner").dropna()
    enough = len(overlap) >= max(min_overlap, 1)
    spread = float((overlap.iloc[:, 0] - overlap.iloc[:, 1]).mean()) if enough else 0.0
    rate = (proxy_pct + spread).copy()
    rate.loc[savings_pct.index] = savings_pct
    return rate.sort_index(), spread, len(overlap)


# --------------------------------------------------------------------------- classes


@dataclass
class Inputs:
    observations: Mapping[str, MonthlySeries]
    savings_12m: MonthlySeries = field(default_factory=lambda: pd.Series(dtype=float))

    def get(self, code: str) -> MonthlySeries:
        return self.observations.get(code, pd.Series(dtype=float))


def build_returns(
    inputs: Inputs, config: SeriesConfig | None = None
) -> tuple[pd.DataFrame, list[Coverage]]:
    """(monthly log returns by asset class, coverage)."""
    config = config or SeriesConfig()
    simple: dict[str, MonthlySeries] = {}
    coverage: dict[str, Coverage] = {}

    def add(name: str, series: MonthlySeries, used: list[str], *notes: str) -> None:
        simple[name] = series.dropna()
        coverage[name] = Coverage(name, used, grade=GRADES.get(name, ""), notes=list(notes))

    fx = inputs.get("usdvnd_central")

    # Equities
    vn30 = price_returns(inputs.get("vn30_close"))
    note = "price only (D/P not set)" if config.dp_eq_large is None else ""
    add("eq_large", vn30 + (config.dp_eq_large or 0) / 12, ["vn30_close"], note)
    mid = equal_weight(
        [price_returns(inputs.get("vnmid_close")), price_returns(inputs.get("vnsml_close"))], 2
    )
    note = "price only (D/P not set)" if config.dp_eq_midsmall is None else ""
    add(
        "eq_midsmall", mid + (config.dp_eq_midsmall or 0) / 12, ["vnmid_close", "vnsml_close"], note
    )

    # Bonds
    add(
        "gov_bond",
        bond_returns(inputs.get("hnx_par_10y"), config.gov_bond_years),
        ["hnx_par_10y"],
        f"{config.gov_bond_years}-year par bond from HNX par yields",
    )
    funds = [c for c in CORP_BOND_FUNDS if not inputs.get(c).empty]
    add(
        "corp_bond",
        equal_weight([price_returns(inputs.get(c)) for c in funds], config.corp_min_funds),
        funds,
        f"equal weight, at least {config.corp_min_funds} funds a month; NAVs are smoothed "
        "(Geltner de-smoothing in Prompt 6)",
    )

    # Cash
    proxy = inputs.get(config.cash_proxy)
    rate, spread, overlap = splice_cash(inputs.savings_12m, proxy, config.cash_min_overlap)
    splice = (
        f"before our savings data: {config.cash_proxy} + {spread:.2f} pp "
        f"(spread from {overlap} overlapping months)"
        if overlap >= config.cash_min_overlap
        else f"before our savings data: {config.cash_proxy}, no spread "
        f"({overlap} of {config.cash_min_overlap} overlapping months needed)"
    )
    add(
        "cash_vnd", carry_returns(rate), ["savings_rate 12M (big banks)", config.cash_proxy], splice
    )

    # USD and foreign assets in VND
    fed = _monthly(inputs.get("fed_rate")) / 100.0
    usd = pd.concat([price_returns(fx), fed.shift(1) / 12], axis=1, join="inner").dropna()
    add("usd", (1 + usd.iloc[:, 0]) * (1 + usd.iloc[:, 1]) - 1, ["usdvnd_central", "fed_rate"])
    add(
        "gold",
        to_vnd(price_returns(inputs.get("wb_gold_usd_oz")), fx),
        ["wb_gold_usd_oz", "usdvnd_central"],
        "World Bank monthly average prices (smoothed); USD/VND from 2020 only",
    )
    price = _monthly(inputs.get("sp500_price"))
    dp = (_monthly(inputs.get("sp500_dividend")).reindex(price.index) / price).ffill(limit=6)
    spx = (price / price.shift(1) - 1 + dp.shift(1) / 12).dropna()
    add(
        "eq_global",
        to_vnd(spx, fx),
        ["sp500_price", "sp500_dividend", "usdvnd_central"],
        "Shiller monthly averages; D/P carried up to 6 months; USD/VND from 2020 only",
    )
    sjc = (
        _monthly(inputs.get("sjc_buy_close_vnd_luong"))
        + _monthly(inputs.get("sjc_sell_close_vnd_luong"))
    ) / 2
    add(
        "gold_sjc",
        (sjc / sjc.shift(1) - 1).dropna(),
        ["sjc_buy_close_vnd_luong", "sjc_sell_close_vnd_luong"],
        "reference only (domestic gold bar, mid price)",
    )
    coverage["real_estate"] = Coverage(
        "real_estate", [], grade="C", notes=["no series: a range from config (spec §3)"]
    )

    frame = pd.DataFrame({k: np.log1p(v) for k, v in simple.items() if not v.empty})
    if not frame.empty:
        frame = frame.reindex(month_index(frame.index.min(), frame.index.max()))
    for name, cov in coverage.items():
        series = frame[name].dropna() if name in frame else pd.Series(dtype=float)
        if series.empty:
            continue
        cov.first, cov.last = (
            series.index.min().strftime("%Y-%m"),
            series.index.max().strftime("%Y-%m"),
        )
        cov.months = len(series)
        cov.missing = len(month_index(series.index.min(), series.index.max())) - len(series)
        if cov.months < TEN_YEARS:
            cov.notes.append(f"under 10 years ({cov.months} months)")
        cov.notes = [n for n in cov.notes if n]
    return frame, list(coverage.values())


def needed_codes(config: SeriesConfig | None = None) -> list[str]:
    config = config or SeriesConfig()
    return sorted(
        {
            "vn30_close",
            "vnmid_close",
            "vnsml_close",
            "hnx_par_10y",
            config.cash_proxy,
            "usdvnd_central",
            "fed_rate",
            "wb_gold_usd_oz",
            "sp500_price",
            "sp500_dividend",
            "sjc_buy_close_vnd_luong",
            "sjc_sell_close_vnd_luong",
            *CORP_BOND_FUNDS,
        }
    )


def coverage_table(coverage: Sequence[Coverage]) -> list[dict[str, Any]]:
    return [
        {
            "class": c.asset_class,
            "first": c.first or "",
            "last": c.last or "",
            "months": c.months,
            "missing": c.missing,
            "grade": c.grade,
            "inputs": ", ".join(c.inputs),
            "notes": "; ".join(c.notes),
        }
        for c in coverage
    ]
