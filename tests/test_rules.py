"""Validation rules (pipeline/validate/rules.py + rules.yaml). Offline."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pipeline.validate.rules import (
    RULES_FILE,
    check_change,
    check_effective_from,
    check_ranges,
    check_removed,
    default_rules,
    load_rules,
    staleness_policy,
)

RULES = default_rules()
KEY = {"term_months": 12}


def test_default_file_loads_with_the_agreed_values() -> None:
    r = load_rules()
    assert (r.ranges["savings_rate.rate_pct"].min, r.ranges["savings_rate.rate_pct"].max) == (0, 12)
    assert r.ranges["card_terms.interest_rate_pct"].max == 50
    assert r.ranges["card_terms.fx_fee_pct"].max == 5
    assert r.ranges["card_terms.annual_fee_primary_vnd"].max == 20_000_000
    assert r.max_change_pct_points == Decimal("0.5")
    assert r.max_effective_from_days_ahead == 60
    assert staleness_policy(r).max_consecutive_failures == 2


def write(tmp_path: Path, change) -> Path:  # type: ignore[no-untyped-def]
    data = yaml.safe_load(RULES_FILE.read_text())
    change(data)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(max_change=1), "Extra inputs"),
        (
            lambda d: d["ranges"].update({"savings_rate.rate": {"min": 0, "max": 1}}),
            "unknown fields",
        ),
        (
            lambda d: d["ranges"].update({"savings_rate.rate_pct": {"min": 5, "max": 1}}),
            "min 5 > max 1",
        ),
        (lambda d: d.pop("staleness"), "staleness"),
    ],
    ids=["unknown key", "unknown field", "min > max", "missing section"],
)
def test_bad_config_fails_loudly(tmp_path: Path, change, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError, match=message):
        load_rules(write(tmp_path, change))


def test_config_is_used(tmp_path: Path) -> None:
    rules = load_rules(write(tmp_path, lambda d: d.update(max_change_pct_points=2)))
    old, new = {"rate_pct": Decimal("5")}, {"rate_pct": Decimal("6.5")}
    assert check_change(rules, "savings_rate", KEY, old, new) == []


# --------------------------------------------------------------------------- ranges


@pytest.mark.parametrize(
    ("table", "field", "value", "flagged"),
    [
        ("savings_rate", "rate_pct", Decimal("0"), False),
        ("savings_rate", "rate_pct", Decimal("12"), False),
        ("savings_rate", "rate_pct", Decimal("12.01"), True),
        ("savings_rate", "rate_pct", Decimal("59.0"), True),  # "5,90" read as "59,0"
        ("card_terms", "interest_rate_pct", Decimal("9.99"), True),
        ("card_terms", "interest_rate_pct", Decimal("10"), False),
        ("card_terms", "interest_rate_pct", Decimal("50"), False),
        ("card_terms", "interest_rate_pct", Decimal("50.5"), True),
        ("card_terms", "fx_fee_pct", Decimal("5"), False),
        ("card_terms", "fx_fee_pct", Decimal("5.01"), True),
        ("card_terms", "annual_fee_primary_vnd", 20_000_000, False),
        ("card_terms", "annual_fee_primary_vnd", 20_000_001, True),
        ("card_terms", "annual_fee_supp_vnd", 25_000_000, True),
        ("card_terms", "fx_fee_pct", None, False),  # not stated: nothing to check
    ],
)
def test_ranges(table: str, field: str, value: object, flagged: bool) -> None:
    warnings = check_ranges(RULES, table, KEY, {field: value})
    assert bool(warnings) == flagged
    if flagged:
        assert warnings[0].rule == "range" and warnings[0].field == field


def test_range_only_applies_to_its_table() -> None:
    assert check_ranges(RULES, "card_reward", KEY, {"rate_pct": Decimal("99")}) == []


# --------------------------------------------------------------------------- changes


@pytest.mark.parametrize(
    ("old", "new", "flagged"),
    [
        ("5.40", "5.90", False),  # exactly 0.5 points: not more than the limit
        ("5.40", "5.91", True),
        ("5.90", "5.39", True),  # falls count too
        ("5.40", "5.40", False),
    ],
)
def test_large_change(old: str, new: str, flagged: bool) -> None:
    warnings = check_change(
        RULES, "savings_rate", KEY, {"rate_pct": Decimal(old)}, {"rate_pct": Decimal(new)}
    )
    assert bool(warnings) == flagged


def test_large_change_only_for_percent_fields() -> None:
    old = {"min_amount_vnd": 0, "annual_fee_primary_vnd": 100_000, "fx_fee_pct": None}
    new = {"min_amount_vnd": 5, "annual_fee_primary_vnd": 900_000, "fx_fee_pct": Decimal("3")}
    assert check_change(RULES, "card_terms", KEY, old, new) == []


def test_large_change_message() -> None:
    [w] = check_change(
        RULES,
        "card_terms",
        KEY,
        {"interest_rate_pct": Decimal("28")},
        {"interest_rate_pct": Decimal("30")},
    )
    assert w.rule == "large_change" and "+2 points" in w.message


# --------------------------------------------------------------------------- dates, removals


@pytest.mark.parametrize(("days", "flagged"), [(-30, False), (0, False), (60, False), (61, True)])
def test_future_effective_from(days: int, flagged: bool) -> None:
    today = dt.date(2026, 10, 28)
    warnings = check_effective_from(
        RULES, "savings_rate", KEY, today + dt.timedelta(days=days), today
    )
    assert bool(warnings) == flagged


def test_no_effective_from_is_fine() -> None:
    assert check_effective_from(RULES, "savings_rate", KEY, None, dt.date(2026, 10, 28)) == []


def test_removed_series(tmp_path: Path) -> None:
    [w] = check_removed(RULES, "savings_rate", KEY)
    assert w.rule == "removed_series"
    off = load_rules(write(tmp_path, lambda d: d.update(flag_removed_series=False)))
    assert check_removed(off, "savings_rate", KEY) == []


def test_warnings_serialise() -> None:
    [w] = check_ranges(RULES, "savings_rate", {"channel": "online"}, {"rate_pct": Decimal("13")})
    assert w.as_json()["key"] == {"channel": "online"}
