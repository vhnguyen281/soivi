"""Validation rules for proposed values (configured in rules.yaml).

Rules never reject anything: they return RuleWarnings that the diff attaches to the
snapshot's review task, for a human to look at.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from core.freshness import StalenessPolicy

RULES_FILE = Path(__file__).with_name("rules.yaml")


class Range(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: Decimal
    max: Decimal

    @model_validator(mode="after")
    def _ordered(self) -> "Range":
        if self.min > self.max:
            raise ValueError(f"min {self.min} > max {self.max}")
        return self


class Staleness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_consecutive_failures: int = Field(ge=1)
    max_age_cadence_multiple: Decimal = Field(gt=0)


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    ranges: dict[str, Range]
    max_change_pct_points: Decimal = Field(ge=0)
    flag_removed_series: bool
    max_effective_from_days_ahead: int = Field(ge=0)
    staleness: Staleness

    @model_validator(mode="after")
    def _known_fields(self) -> "Rules":
        from pipeline.records import RECORD_TYPES

        known = {f"{r.table.__tablename__}.{f}" for r in RECORD_TYPES for f in r.model_fields}
        unknown = sorted(set(self.ranges) - known)
        if unknown:
            raise ValueError(f"ranges for unknown fields: {unknown}")
        return self


def load_rules(path: Path = RULES_FILE) -> Rules:
    return Rules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def default_rules() -> Rules:
    return load_rules()


def staleness_policy(rules: Rules | None = None) -> "StalenessPolicy":
    from core.freshness import StalenessPolicy

    s = (rules or default_rules()).staleness
    return StalenessPolicy(s.max_consecutive_failures, s.max_age_cadence_multiple)


# --------------------------------------------------------------------------- warnings


@dataclass(frozen=True)
class RuleWarning:
    rule: str  # "range" | "large_change" | "removed_series" | "future_effective_from" | ...
    table: str
    key: dict[str, Any]
    message: str
    field: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "table": self.table,
            "key": _jsonable(self.key),
            "field": self.field,
            "message": self.message,
        }


def check_ranges(
    rules: Rules, table: str, key: dict[str, Any], values: dict[str, Any]
) -> list[RuleWarning]:
    warnings = []
    for name, bounds in rules.ranges.items():
        rule_table, field = name.split(".", 1)
        value = values.get(field)
        if rule_table != table or value is None:
            continue
        if not bounds.min <= Decimal(value) <= bounds.max:
            warnings.append(
                RuleWarning(
                    "range",
                    table,
                    key,
                    f"{field} = {value} is outside {bounds.min}–{bounds.max}",
                    field,
                )
            )
    return warnings


def check_change(
    rules: Rules, table: str, key: dict[str, Any], old: dict[str, Any], new: dict[str, Any]
) -> list[RuleWarning]:
    warnings = []
    for field, value in new.items():
        before = old.get(field)
        if not field.endswith("_pct") or value is None or before is None:
            continue
        delta = Decimal(value) - Decimal(before)
        if abs(delta) > rules.max_change_pct_points:
            warnings.append(
                RuleWarning(
                    "large_change",
                    table,
                    key,
                    f"{field} changes by {delta:+} points ({before} → {value}); "
                    f"limit {rules.max_change_pct_points}",
                    field,
                )
            )
    return warnings


def check_effective_from(
    rules: Rules, table: str, key: dict[str, Any], effective: dt.date | None, today: dt.date
) -> list[RuleWarning]:
    if effective is None:
        return []
    ahead = (effective - today).days
    if ahead > rules.max_effective_from_days_ahead:
        return [
            RuleWarning(
                "future_effective_from",
                table,
                key,
                f"effective_from {effective} is {ahead} days ahead "
                f"(limit {rules.max_effective_from_days_ahead})",
                "effective_from",
            )
        ]
    return []


def check_removed(rules: Rules, table: str, key: dict[str, Any]) -> list[RuleWarning]:
    if not rules.flag_removed_series:
        return []
    return [
        RuleWarning(
            "removed_series",
            table,
            key,
            "this series has an approved value but is missing from the new snapshot",
        )
    ]


def _jsonable(value: Any) -> Any:
    from enum import Enum

    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value
