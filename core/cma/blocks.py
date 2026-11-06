"""Macro block, building-block expected returns and scenarios (docs/vncma/spec.md §1-3, Prompt 7).

All rates are percent per year; floats only inside this computation (CLAUDE.md, VNCMA).
Every value carries a `derivation` string with the numbers it was built from, so the
report can show how each number traces to its inputs. H = horizon (10 years).

Macro (spec §2; owner's decisions, DECISIONS 2026-11-06 "Building blocks"):
  pi          w * official target + (1 - w) * trailing CPI y/y average
  g           trailing average of real GDP growth (yearly)
  r_star      trailing average of (interbank 3M - CPI)          -> cash
  r_star_gov  trailing average of (HNX 1Y par yield - CPI)       -> government bonds
  tp          average of (HNX 10Y - 1Y par yield), all history
  d           pi - pi_us, cross-checked with the trend of the SBV central rate

Classes (geometric, VND nominal):
  cash_vnd     pi + r_star
  gov_bond     y0 + D * (y0 - y_eq) / H,  y_eq = pi + r_star_gov + tp, D = modified duration
               of a 10-year par bond at y0
  corp_bond    E_gov + spread - expected default loss
  eq_large     Grinold-Kroner: D/P + pi + g * haircut - dilution + 100 * ln(PE_target / PE_0) / H,
               PE_target = w * PE_0 + (1 - w) * median(P/E history)
  eq_midsmall  mean of Grinold-Kroner for VNMID and VNSML (bottom-up P/E of members)
  gold         pi_us + theta + d
  usd          i_usd + d
  eq_global    mean of published global CMAs (USD) + d
  real_estate  rent - cost + (pi + real income growth) * k, as a range (low/high); model = midpoint

Output per class: model, adjustment, final, arithmetic = final + sigma^2 / 2, expected and
historical volatility, scenarios (adverse / base / favourable), 80% band
final +- 1.28 sigma / sqrt(H).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from core.cma.config import CLASSES, CmaConfig, Scenario
from core.cma.series import GRADES, par_bond_risk
from core.cma.stats import Stats

OZ_PER_LUONG = 37.5 / 31.1034768  # 1 lượng = 37.5 g
BAND_Z = 1.2816  # 80% two-sided normal band
NEEDED_CODES = (
    "cpi_total_yoy",
    "gdp_growth_yoy",
    "interbank_3m",
    "hnx_par_1y",
    "hnx_par_10y",
    "usdvnd_central",
    "usdvnd_market",
    "pe_vn30",
    "dp_vn30",
    "pe_bu_vnmid",
    "dp_vnmid",
    "pe_bu_vnsml",
    "dp_vnsml",
    "pe_now_vn30",
    "pe_now_vnmid",
    "pe_now_vnsml",
    "wb_gold_usd_oz",
    "sjc_buy_close_vnd_luong",
    "sjc_sell_close_vnd_luong",
)
EQUITY_INPUTS = {
    "eq_large": [("VN30", "dp_vn30", "pe_vn30")],
    "eq_midsmall": [("VNMID", "dp_vnmid", "pe_bu_vnmid"), ("VNSML", "dp_vnsml", "pe_bu_vnsml")],
}

type Series = Any  # pandas Series indexed by period-end Timestamps


class BlockError(ValueError):
    """An input the model needs is missing: the run stops, it never publishes a partial result."""


@dataclass(frozen=True)
class Value:
    value: float
    derivation: str
    inputs: tuple[str, ...] = ()
    overridden: dict[str, Any] | None = None  # {"model": x, "reason": ..., "author": ...}


@dataclass
class ClassResult:
    model: float
    formula: str
    inputs: list[str]
    low: float | None = None  # real estate range
    high: float | None = None
    info: dict[str, float] = field(default_factory=dict)


def _f(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}"


def _need(obs: Mapping[str, Series], code: str, as_of: pd.Timestamp) -> Series:
    s = obs.get(code)
    if s is None or s.empty:
        raise BlockError(f"no observations for {code}")
    s = s[s.index <= as_of].dropna()
    if s.empty:
        raise BlockError(f"no observations for {code} on or before {as_of:%Y-%m-%d}")
    return s


def _latest(obs: Mapping[str, Series], code: str) -> tuple[float, pd.Timestamp]:
    """The latest value whatever its date (spot series read on the run day)."""
    s = obs.get(code)
    if s is None or s.dropna().empty:
        raise BlockError(f"no observations for {code}")
    s = s.dropna()
    return float(s.iloc[-1]), s.index[-1]


def _window(s: Series, as_of: pd.Timestamp, months: int) -> Series:
    return s[s.index > as_of - pd.DateOffset(months=months)]


def _span(s: Series) -> str:
    return f"{s.index.min():%Y-%m}..{s.index.max():%Y-%m}, n={len(s)}"


# --------------------------------------------------------------------------- macro


def derive_macro(
    obs: Mapping[str, Series], cfg: CmaConfig, as_of: pd.Timestamp
) -> dict[str, Value]:
    months = cfg.window_months
    cpi = _need(obs, "cpi_total_yoy", as_of)
    cpi_w = _window(cpi, as_of, months)
    w, target = cfg.p("pi_target_weight"), cfg.p("pi_target")
    pi = w * target + (1 - w) * float(cpi_w.mean())

    gdp = _need(obs, "gdp_growth_yoy", as_of)
    gdp_w = gdp.iloc[-(months // 12) :]

    def spread(a: str, b: Series, label: str) -> tuple[float, str]:
        x = (_need(obs, a, as_of) - b).dropna()
        x = _window(x, as_of, months)
        if len(x) < months // 2:
            raise BlockError(f"{label}: only {len(x)} months of {a} and CPI")
        return float(x.mean()), _span(x)

    r_star, r_span = spread("interbank_3m", cpi, "r_star")
    r_gov, g_span = spread("hnx_par_1y", cpi, "r_star_gov")
    term = (_need(obs, "hnx_par_10y", as_of) - _need(obs, "hnx_par_1y", as_of)).dropna()
    pi_us = cfg.p("pi_us")

    fx = _need(obs, "usdvnd_central", as_of)
    years = (fx.index[-1] - fx.index[0]).days / 365.25
    trend = 100 * math.log(float(fx.iloc[-1]) / float(fx.iloc[0])) / years

    out = {
        "pi": Value(
            pi,
            f"{w:g} x target {_f(target)} + {1 - w:g} x CPI y/y average {_f(float(cpi_w.mean()))} "
            f"({_span(cpi_w)})",
            ("cpi_total_yoy", "param:pi_target"),
        ),
        "pi_us": Value(pi_us, "config", ("param:pi_us",)),
        "g": Value(
            float(gdp_w.mean()), f"real GDP growth average ({_span(gdp_w)})", ("gdp_growth_yoy",)
        ),
        "r_star": Value(
            r_star, f"mean(interbank 3M - CPI) ({r_span})", ("interbank_3m", "cpi_total_yoy")
        ),
        "r_star_gov": Value(
            r_gov, f"mean(HNX 1Y par - CPI) ({g_span})", ("hnx_par_1y", "cpi_total_yoy")
        ),
        "tp": Value(
            float(term.mean()),
            f"mean(HNX 10Y - 1Y par) ({_span(term)})",
            ("hnx_par_10y", "hnx_par_1y"),
        ),
    }
    d = out["pi"].value - pi_us
    out["d"] = Value(
        d,
        f"pi {_f(out['pi'].value)} - pi_us {_f(pi_us)}; cross-check: SBV central rate trend "
        f"{_f(trend)}%/yr ({_span(fx)})",
        ("param:pi_us", "usdvnd_central"),
    )
    for name, o in cfg.overrides.items():
        model = out[name]
        out[name] = Value(
            o.value,
            f"override (model {_f(model.value)}): {o.reason}",
            model.inputs,
            {"model": model.value, "reason": o.reason, "author": o.author},
        )
    if "pi" in cfg.overrides and "d" not in cfg.overrides:  # d follows an overridden pi
        out["d"] = replace(out["d"], value=out["pi"].value - pi_us)
    return out


# --------------------------------------------------------------------------- classes


def _grinold_kroner(
    obs: Mapping[str, Series],
    macro: Mapping[str, float],
    cfg: CmaConfig,
    as_of: pd.Timestamp,
    label: str,
    dp_code: str,
    pe_code: str,
    percentile: float | None,
) -> tuple[float, str, dict[str, float]]:
    dp, _ = _latest(obs, dp_code)
    pe = _need(obs, pe_code, as_of)
    pe0 = float(pe.iloc[-1])
    anchor = float(pe.median()) if percentile is None else float(np.percentile(pe, percentile))
    w = cfg.p("pe_current_weight")
    target = w * pe0 + (1 - w) * anchor
    h = cfg.horizon_years
    growth = macro["g"] * cfg.p("g_eps_haircut")
    valuation = 100 * math.log(target / pe0) / h
    e = dp + macro["pi"] + growth - cfg.p("dilution") + valuation
    stat = "median" if percentile is None else f"p{percentile:g}"
    formula = (
        f"{label}: D/P {_f(dp)} + pi {_f(macro['pi'])} + g {_f(macro['g'])} "
        f"x {cfg.p('g_eps_haircut'):g} - dS {_f(cfg.p('dilution'))} "
        f"+ ln(PE_target {_f(target)} / PE_0 {_f(pe0)}) / {h} = {_f(e)} "
        f"[PE_target = {w:g} x {_f(pe0)} + {1 - w:g} x {stat} {_f(anchor)} ({_span(pe)})]"
    )
    return e, formula, {f"{label}_dp": dp, f"{label}_pe0": pe0, f"{label}_pe_target": target}


def class_returns(
    obs: Mapping[str, Series],
    macro_values: Mapping[str, Value],
    cfg: CmaConfig,
    as_of: pd.Timestamp,
    scenario: Scenario | None = None,
) -> dict[str, ClassResult]:
    s = scenario or Scenario()
    m = {k: v.value for k, v in macro_values.items()}
    m["g"] += s.g
    m["d"] += s.d
    h = cfg.horizon_years
    out: dict[str, ClassResult] = {}

    cash = m["pi"] + m["r_star"]
    out["cash_vnd"] = ClassResult(
        cash,
        f"pi {_f(m['pi'])} + r_star {_f(m['r_star'])} = {_f(cash)}",
        ["macro:pi", "macro:r_star"],
    )

    y0 = float(_need(obs, "hnx_par_10y", as_of).iloc[-1])
    duration, _ = par_bond_risk(y0 / 100, 10)
    y_eq = m["pi"] + m["r_star_gov"] + m["tp"]
    gov = y0 + duration * (y0 - y_eq) / h
    out["gov_bond"] = ClassResult(
        gov,
        f"y0 {_f(y0)} + D {_f(duration)} x (y0 - y_eq {_f(y_eq)}) / {h} = {_f(gov)} "
        f"[y_eq = pi {_f(m['pi'])} + r_star_gov {_f(m['r_star_gov'])} + tp {_f(m['tp'])}]",
        ["hnx_par_10y", "macro:pi", "macro:r_star_gov", "macro:tp"],
        info={"y0": y0, "y_eq": y_eq, "duration": duration},
    )

    corp = gov + cfg.p("corp_spread") - cfg.p("corp_loss")
    out["corp_bond"] = ClassResult(
        corp,
        f"E_gov {_f(gov)} + spread {_f(cfg.p('corp_spread'))} "
        f"- loss {_f(cfg.p('corp_loss'))} = {_f(corp)}",
        ["class:gov_bond", "param:corp_spread", "param:corp_loss"],
    )

    for cls, parts in EQUITY_INPUTS.items():
        values, formulas, info, inputs = [], [], {}, []
        for label, dp_code, pe_code in parts:
            e, formula, extra = _grinold_kroner(
                obs, m, cfg, as_of, label, dp_code, pe_code, s.pe_target_percentile
            )
            values.append(e)
            formulas.append(formula)
            info.update(extra)
            inputs += [dp_code, pe_code]
        e = sum(values) / len(values)
        text = "; ".join(formulas) + ("" if len(values) == 1 else f"; mean = {_f(e)}")
        out[cls] = ClassResult(e, text, [*inputs, "macro:pi", "macro:g"], info=info)

    gold = m["pi_us"] + cfg.p("gold_theta") + m["d"]
    out["gold"] = ClassResult(
        gold,
        f"pi_us {_f(m['pi_us'])} + theta {_f(cfg.p('gold_theta'))} + d {_f(m['d'])} = {_f(gold)}",
        ["macro:pi_us", "param:gold_theta", "macro:d"],
        info=sjc_premium(obs, as_of),
    )

    usd = cfg.p("i_usd") + m["d"]
    out["usd"] = ClassResult(
        usd, f"i_usd {_f(cfg.p('i_usd'))} + d {_f(m['d'])} = {_f(usd)}", ["param:i_usd", "macro:d"]
    )

    cma = sum(c.value for c in cfg.global_cmas) / len(cfg.global_cmas)
    names = ", ".join(f"{c.name} {_f(c.value)}" for c in cfg.global_cmas)
    out["eq_global"] = ClassResult(
        cma + m["d"],
        f"mean({names}) {_f(cma)} USD + d {_f(m['d'])} = {_f(cma + m['d'])}",
        ["config:global_cmas", "macro:d"],
    )

    nominal = m["pi"] + cfg.p("re_income_growth_real")
    low = cfg.p("re_rent_yield_low") - cfg.p("re_cost_high") + nominal * cfg.p("re_k_low")
    high = cfg.p("re_rent_yield_high") - cfg.p("re_cost_low") + nominal * cfg.p("re_k_high")
    out["real_estate"] = ClassResult(
        (low + high) / 2,
        f"rent - cost + (pi {_f(m['pi'])} + income {_f(cfg.p('re_income_growth_real'))}) x k: "
        f"low {_f(low)}, high {_f(high)}, midpoint {_f((low + high) / 2)}",
        ["macro:pi", "param:re_*"],
        low=low,
        high=high,
    )
    return out


def sjc_premium(obs: Mapping[str, Series], as_of: pd.Timestamp) -> dict[str, float]:
    """SJC bar premium over world gold (reported only; not in the gold class)."""
    try:
        world = (
            _need(obs, "wb_gold_usd_oz", as_of) * _need(obs, "usdvnd_market", as_of) * OZ_PER_LUONG
        )
        mid = (
            _need(obs, "sjc_buy_close_vnd_luong", as_of)
            + _need(obs, "sjc_sell_close_vnd_luong", as_of)
        ) / 2
    except BlockError:
        return {}
    p = (mid / world - 1).dropna()
    if p.empty:
        return {}
    return {
        "sjc_premium_now": 100 * float(p.iloc[-1]),
        "sjc_premium_median": 100 * float(p.median()),
    }


# --------------------------------------------------------------------------- one run


def historical_returns(returns: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Annualised geometric return of each class over its own history (for comparison)."""
    out = {}
    for c in returns.columns:
        s = returns[c].dropna()
        if len(s):
            out[c] = {
                "return": 100 * (math.exp(12 * float(s.mean())) - 1),
                "first": f"{s.index.min():%Y-%m}",
                "last": f"{s.index.max():%Y-%m}",
                "months": len(s),
            }
    return out


def compute(
    obs: Mapping[str, Series],
    stats: Stats,
    returns: pd.DataFrame,
    cfg: CmaConfig,
    as_of: pd.Timestamp,
    savings_12m: float | None = None,
) -> dict[str, Any]:
    """The full model output of one run (JSON-ready)."""
    macro = derive_macro(obs, cfg, as_of)
    base = class_returns(obs, macro, cfg, as_of)
    scen = {name: class_returns(obs, macro, cfg, as_of, s) for name, s in cfg.scenarios.items()}
    adjust = {a.asset_class: a for a in cfg.adjustments}
    h = cfg.horizon_years
    history = historical_returns(returns)
    classes: dict[str, Any] = {}
    for cls in CLASSES:
        r = base[cls]
        a = adjust.get(cls)
        delta = a.delta_pp if a else 0.0
        final = r.model + delta
        vol = stats.vol.get(cls)
        row: dict[str, Any] = {
            "model": r.model,
            "adjustment": delta,
            "adjustment_reason": a.reason if a else None,
            "final": final,
            "formula": r.formula,
            "inputs": r.inputs,
            "grade": GRADES.get(cls, ""),
            "vol": vol,
            "vol_hist": stats.vol_raw.get(cls),
            "arithmetic": None if vol is None else final + 100 * vol**2 / 2,
            "band_low": None if vol is None else final - 100 * BAND_Z * vol / math.sqrt(h),
            "band_high": None if vol is None else final + 100 * BAND_Z * vol / math.sqrt(h),
            "scenarios": {
                "adverse": scen["adverse"][cls].model + delta,
                "base": final,
                "favourable": scen["favourable"][cls].model + delta,
            },
            "history": history.get(cls),
            "info": r.info,
        }
        if r.low is not None:
            row["range"] = {"low": r.low + delta, "high": (r.high or r.low) + delta}
        classes[cls] = row
    if savings_12m is not None:
        classes["cash_vnd"]["info"]["savings_12m_now"] = savings_12m
    corr = stats.corr
    return {
        "as_of": f"{as_of:%Y-%m-%d}",
        "methodology_version": cfg.methodology_version,
        "horizon_years": h,
        "macro": {
            k: {
                "value": v.value,
                "derivation": v.derivation,
                "inputs": list(v.inputs),
                "override": v.overridden,
            }
            for k, v in macro.items()
        },
        "classes": classes,
        "correlation": {
            "classes": list(corr.columns),
            "matrix": [[float(x) for x in row] for row in corr.to_numpy()],
            "shrinkage": stats.shrinkage,
            "common_months": stats.common_months,
            "repaired": stats.repaired,
        },
        "params": {
            k: {"value": p.value, "source": p.source, "note": p.note} for k, p in cfg.params.items()
        },
        "global_cmas": [vars(c) for c in cfg.global_cmas],
        "scenarios": {k: vars(s) for k, s in cfg.scenarios.items()},
        "notes": list(stats.notes),
        "checks": checks(classes),
    }


def checks(classes: Mapping[str, Any]) -> list[str]:
    """Common-sense orderings (spec Prompt 9); a failure is reported, not hidden."""
    f = {k: v["final"] for k, v in classes.items()}
    out = []
    for a, b in (("eq_large", "gov_bond"), ("gov_bond", "cash_vnd"), ("eq_large", "cash_vnd")):
        ok = f[a] > f[b]
        out.append(f"{'ok' if ok else 'FAIL'}: {a} {f[a]:.2f} > {b} {f[b]:.2f}")
    vg, ve = classes["gold"]["vol"], classes["eq_large"]["vol"]
    if vg is not None and ve is not None:
        out.append(f"{'ok' if vg < ve else 'FAIL'}: gold vol {vg:.1%} < eq_large vol {ve:.1%}")
    return out
