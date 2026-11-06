"""VNCMA model configuration: data/cma/config.yaml (docs/vncma/spec.md §2-3, Prompt 7).

Validated on load. A run refuses to start when an override or an adjustment has no
written reason, or an adjustment is larger than MAX_ADJUSTMENT_PP.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path("data/cma/config.yaml")
MAX_ADJUSTMENT_PP = 1.0
MACRO_VARS = ("pi", "pi_us", "g", "r_star", "r_star_gov", "d", "tp")
CLASSES = (
    "cash_vnd",
    "gov_bond",
    "corp_bond",
    "eq_large",
    "eq_midsmall",
    "gold",
    "usd",
    "eq_global",
    "real_estate",
)
REQUIRED_PARAMS = (
    "pi_target",
    "pi_target_weight",
    "pi_us",
    "g_eps_haircut",
    "dilution",
    "pe_current_weight",
    "gold_theta",
    "i_usd",
    "corp_spread",
    "corp_loss",
    "re_rent_yield_low",
    "re_rent_yield_high",
    "re_cost_low",
    "re_cost_high",
    "re_income_growth_real",
    "re_k_low",
    "re_k_high",
)


class ConfigError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Param:
    value: float
    source: str
    note: str


@dataclass(frozen=True)
class Override:
    value: float
    reason: str
    author: str


@dataclass(frozen=True)
class Adjustment:
    asset_class: str
    delta_pp: float
    reason: str
    author: str


@dataclass(frozen=True)
class GlobalCma:
    name: str
    value: float
    as_of: str
    source: str


@dataclass(frozen=True)
class Scenario:
    g: float = 0.0
    d: float = 0.0
    pe_target_percentile: float | None = None  # None: the median


@dataclass(frozen=True)
class CmaConfig:
    methodology_version: str
    horizon_years: int
    window_months: int
    params: dict[str, Param]
    global_cmas: list[GlobalCma]
    scenarios: dict[str, Scenario]
    overrides: dict[str, Override] = field(default_factory=dict)
    adjustments: list[Adjustment] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)  # the parsed file, stored with the run

    def p(self, name: str) -> float:
        return self.params[name].value

    @property
    def sha256(self) -> str:
        text = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def parse_config(doc: dict[str, Any]) -> CmaConfig:
    errors: list[str] = []
    params: dict[str, Param] = {}
    for name, entry in (doc.get("params") or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get("value"), int | float):
            errors.append(f"param {name}: needs a numeric value")
            continue
        if not _text(entry.get("source")):
            errors.append(f"param {name}: needs a source")
        params[name] = Param(
            float(entry["value"]), _text(entry.get("source")), _text(entry.get("note"))
        )
    for name in REQUIRED_PARAMS:
        if name not in params:
            errors.append(f"param {name} is missing")

    cmas = []
    for i, c in enumerate(doc.get("global_cmas") or [], 1):
        if not _text(c.get("source")).startswith("http") or not isinstance(
            c.get("value"), int | float
        ):
            errors.append(f"global_cmas #{i}: needs a numeric value and an http(s) source")
            continue
        cmas.append(
            GlobalCma(
                _text(c.get("name")), float(c["value"]), _text(c.get("as_of")), _text(c["source"])
            )
        )
    if len(cmas) < 2:
        errors.append("global_cmas: at least 2 published CMAs are needed (spec §3)")

    scenarios = {}
    for name in ("adverse", "favourable"):
        s = (doc.get("scenarios") or {}).get(name)
        if not isinstance(s, dict):
            errors.append(f"scenarios.{name} is missing")
            continue
        pct = s.get("pe_target_percentile")
        scenarios[name] = Scenario(
            float(s.get("g", 0)), float(s.get("d", 0)), None if pct is None else float(pct)
        )

    overrides = {}
    for name, o in (doc.get("overrides") or {}).items():
        if name not in MACRO_VARS:
            errors.append(f"override {name}: not a macro variable {MACRO_VARS}")
            continue
        if not isinstance(o, dict) or not isinstance(o.get("value"), int | float):
            errors.append(f"override {name}: needs a numeric value")
            continue
        if not _text(o.get("reason")) or not _text(o.get("author")):
            errors.append(f"override {name}: a written reason and an author are required")
            continue
        overrides[name] = Override(float(o["value"]), _text(o["reason"]), _text(o["author"]))

    adjustments = []
    seen: set[str] = set()
    for i, a in enumerate(doc.get("adjustments") or [], 1):
        where = f"adjustment #{i} ({a.get('asset_class', '?')})"
        cls, delta = a.get("asset_class"), a.get("delta_pp")
        if cls not in CLASSES:
            errors.append(f"{where}: unknown asset class")
        elif cls in seen:
            errors.append(f"{where}: one adjustment per class")
        seen.add(str(cls))
        if not isinstance(delta, int | float) or abs(delta) > MAX_ADJUSTMENT_PP:
            errors.append(f"{where}: delta_pp must be a number within +-{MAX_ADJUSTMENT_PP}")
            continue
        if not _text(a.get("reason")) or not _text(a.get("author")):
            errors.append(f"{where}: a written reason and an author are required")
            continue
        adjustments.append(
            Adjustment(str(cls), float(delta), _text(a["reason"]), _text(a["author"]))
        )

    for key in ("methodology_version", "horizon_years", "window_months"):
        if key not in doc:
            errors.append(f"{key} is missing")
    if errors:
        raise ConfigError(errors)
    return CmaConfig(
        methodology_version=str(doc["methodology_version"]),
        horizon_years=int(doc["horizon_years"]),
        window_months=int(doc["window_months"]),
        params=params,
        global_cmas=cmas,
        scenarios=scenarios,
        overrides=overrides,
        adjustments=adjustments,
        raw=doc,
    )


def load_config(path: Path = DEFAULT_PATH) -> CmaConfig:
    return parse_config(yaml.safe_load(path.read_text("utf-8")) or {})
