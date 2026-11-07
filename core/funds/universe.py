"""The fund universe (data/funds/universe.yaml), from `python -m pipeline market fund-series`."""

from pathlib import Path
from typing import Any

import yaml

GROUPS = ("equity_fund", "bond_fund", "balanced_fund", "etf")
UNIVERSE = Path("data/funds/universe.yaml")


def load_universe(path: Path = UNIVERSE) -> list[dict[str, Any]]:
    doc = yaml.safe_load(path.read_text("utf-8")) if path.exists() else None
    funds = (doc or {}).get("funds") or []
    for f in funds:
        if f.get("group") not in GROUPS or not f.get("code"):
            raise ValueError(f"{path}: bad fund entry {f!r}")
    return funds
