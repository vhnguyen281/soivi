"""Macro block and building blocks (VNCMA Prompt 7): known answers on constant inputs."""

import copy
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from core.cma.blocks import BlockError, class_returns, compute, derive_macro
from core.cma.config import ConfigError, parse_config
from core.cma.series import par_bond_risk
from core.cma.stats import StatsConfig, compute_stats

AS_OF = pd.Timestamp("2026-10-31")
DOC: dict[str, Any] = yaml.safe_load(Path("data/cma/config.yaml").read_text("utf-8"))


def monthly(value: float, months: int = 150) -> pd.Series:
    return pd.Series(value, index=pd.date_range(end=AS_OF, periods=months, freq="ME"))


def observations() -> dict[str, pd.Series]:
    yearly = pd.Series(6.0, index=pd.date_range(end="2025-12-31", periods=11, freq="YE"))
    pe = monthly(15.0, 107)
    pe.iloc[-1] = 12.0  # today cheaper than the median
    daily = pd.Series([2.5], index=[pd.Timestamp("2026-11-06")])
    quarterly = pd.Series(
        [14.0] * 30 + [10.0], index=pd.date_range(end="2026-06-30", periods=31, freq="QE")
    )
    fx = pd.Series(
        [23000 * math.exp(0.016 * i / 12) for i in range(82)],
        index=pd.date_range(end=AS_OF, periods=82, freq="ME"),
    )
    return {
        "cpi_total_yoy": monthly(3.0),
        "gdp_growth_yoy": yearly,
        "interbank_3m": monthly(4.5),
        "hnx_par_1y": monthly(2.5),
        "hnx_par_10y": monthly(4.0),
        "usdvnd_central": fx,
        "usdvnd_market": fx * 1.02,
        "pe_vn30": pe,
        "dp_vn30": daily,
        "pe_bu_vnmid": quarterly,
        "dp_vnmid": daily,
        "pe_bu_vnsml": quarterly,
        "dp_vnsml": daily,
        "wb_gold_usd_oz": monthly(4000.0),
        "sjc_buy_close_vnd_luong": monthly(4000.0) * fx.reindex(monthly(0).index) * 1.02 * 1.2056,
        "sjc_sell_close_vnd_luong": monthly(4000.0) * fx.reindex(monthly(0).index) * 1.02 * 1.2056,
    }


def test_macro_derivations() -> None:
    cfg = parse_config(DOC)
    macro = derive_macro(observations(), cfg, AS_OF)
    assert macro["pi"].value == pytest.approx(0.5 * 4.5 + 0.5 * 3.0)
    assert macro["g"].value == pytest.approx(6.0)
    assert macro["r_star"].value == pytest.approx(1.5)
    assert macro["r_star_gov"].value == pytest.approx(-0.5)
    assert macro["tp"].value == pytest.approx(1.5)
    assert macro["d"].value == pytest.approx(3.75 - 2.3)
    assert "trend 1.60%/yr" in macro["d"].derivation


def test_class_formulas() -> None:
    cfg = parse_config(DOC)
    obs = observations()
    r = class_returns(obs, derive_macro(obs, cfg, AS_OF), cfg, AS_OF)
    assert r["cash_vnd"].model == pytest.approx(3.75 + 1.5)
    duration, _ = par_bond_risk(0.04, 10)
    y_eq = 3.75 - 0.5 + 1.5
    assert r["gov_bond"].model == pytest.approx(4.0 + duration * (4.0 - y_eq) / 10)
    assert r["corp_bond"].model == pytest.approx(r["gov_bond"].model + 2.0 - 1.0)
    target = 0.5 * 12.0 + 0.5 * 15.0
    gk = 2.5 + 3.75 + 6.0 * 0.6 - 1.0 + 100 * math.log(target / 12.0) / 10
    assert r["eq_large"].model == pytest.approx(gk)
    mid = 2.5 + 3.75 + 3.6 - 1.0 + 100 * math.log(12.0 / 10.0) / 10
    assert r["eq_midsmall"].model == pytest.approx(mid)
    assert r["gold"].model == pytest.approx(2.3 + 0.5 + 1.45)
    assert r["usd"].model == pytest.approx(0.0 + 1.45)
    assert r["eq_global"].model == pytest.approx((7.5 + 4.9) / 2 + 1.45)
    re = r["real_estate"]
    assert (re.low, re.high) == (pytest.approx(3 - 1.5 + 6.75 * 0.5), pytest.approx(4 - 1 + 6.75))
    assert "D/P 2.50" in r["eq_large"].formula and "median 15.00" in r["eq_large"].formula
    assert r["gold"].info["sjc_premium_now"] == pytest.approx(0.0, abs=0.1)


def test_scenarios_move_the_right_way() -> None:
    cfg = parse_config(DOC)
    obs = observations()
    macro = derive_macro(obs, cfg, AS_OF)
    adverse = class_returns(obs, macro, cfg, AS_OF, cfg.scenarios["adverse"])
    base = class_returns(obs, macro, cfg, AS_OF)
    assert adverse["eq_large"].model < base["eq_large"].model
    assert adverse["usd"].model == pytest.approx(base["usd"].model + 1.0)  # VND weaker
    assert adverse["cash_vnd"].model == pytest.approx(base["cash_vnd"].model)


def run_output(doc: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(0)
    classes = StatsConfig().classes
    returns = pd.DataFrame(
        rng.normal(0.005, 0.03, size=(150, len(classes))),
        columns=classes,
        index=pd.date_range(end=AS_OF, periods=150, freq="ME"),
    )
    stats = compute_stats(returns)
    return compute(observations(), stats, returns, parse_config(doc), AS_OF, savings_12m=5.8)


def test_compute_output_bands_arithmetic_and_adjustment() -> None:
    doc = copy.deepcopy(DOC)
    doc["adjustments"] = [
        {"asset_class": "gold", "delta_pp": -0.5, "reason": "test", "author": "QA"}
    ]
    out = run_output(doc)
    gold = out["classes"]["gold"]
    assert gold["final"] == pytest.approx(gold["model"] - 0.5)
    assert gold["arithmetic"] == pytest.approx(gold["final"] + 100 * gold["vol"] ** 2 / 2)
    half = 100 * 1.2816 * gold["vol"] / math.sqrt(10)
    assert (gold["band_low"], gold["band_high"]) == (
        pytest.approx(gold["final"] - half),
        pytest.approx(gold["final"] + half),
    )
    assert gold["scenarios"]["base"] == gold["final"]
    re = out["classes"]["real_estate"]
    assert re["vol"] is None and re["range"]["low"] < re["final"] < re["range"]["high"]
    assert out["classes"]["cash_vnd"]["info"]["savings_12m_now"] == 5.8
    assert any(c.startswith("ok: eq_large") for c in out["checks"])
    assert len(out["correlation"]["matrix"]) == 8


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {
                "adjustments": [
                    {"asset_class": "gold", "delta_pp": 1.5, "reason": "x", "author": "y"}
                ]
            },
            "within",
        ),
        (
            {
                "adjustments": [
                    {"asset_class": "gold", "delta_pp": 0.5, "reason": " ", "author": "y"}
                ]
            },
            "reason",
        ),
        ({"overrides": {"pi": {"value": 4.0, "author": "y"}}}, "reason"),
        ({"overrides": {"beta": {"value": 1.0, "reason": "x", "author": "y"}}}, "not a macro"),
        ({"global_cmas": DOC["global_cmas"][:1]}, "at least 2"),
    ],
)
def test_bad_config_refuses_to_run(change: dict[str, Any], message: str) -> None:
    doc = {**copy.deepcopy(DOC), **change}
    with pytest.raises(ConfigError, match=message):
        parse_config(doc)


def test_override_replaces_the_model_value_and_d_follows_pi() -> None:
    doc = copy.deepcopy(DOC)
    doc["overrides"] = {"pi": {"value": 5.0, "reason": "SBV guidance", "author": "QA"}}
    macro = derive_macro(observations(), parse_config(doc), AS_OF)
    assert macro["pi"].value == 5.0 and macro["pi"].overridden["model"] == pytest.approx(3.75)  # type: ignore[index]
    assert macro["d"].value == pytest.approx(5.0 - 2.3)


def test_missing_input_stops_the_run() -> None:
    obs = observations()
    del obs["dp_vn30"]
    cfg = parse_config(DOC)
    with pytest.raises(BlockError, match="dp_vn30"):
        class_returns(obs, derive_macro(obs, cfg, AS_OF), cfg, AS_OF)


def test_config_hash_is_stable() -> None:
    assert parse_config(copy.deepcopy(DOC)).sha256 == parse_config(copy.deepcopy(DOC)).sha256
