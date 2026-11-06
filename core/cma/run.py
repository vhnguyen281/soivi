"""One VNCMA run: load inputs, compute, store an append-only `cma_run` (Prompt 7).

Traceability: `inputs` lists, for every series used, the current observations
(period_end, revision, value) with their SHA-256 and the snapshot ids they came from,
plus the approved savings rates behind the cash class. With the stored config and
code version, every number in `output` can be rebuilt from these inputs.
"""

import datetime as dt
import hashlib
import json
import math
import os
import subprocess
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.cma.blocks import NEEDED_CODES, compute
from core.cma.config import CmaConfig
from core.cma.series import (
    Inputs,
    SeriesConfig,
    build_returns,
    load_observations,
    load_savings_12m,
    month_index,
    needed_codes,
)
from core.cma.stats import compute_stats
from core.models import CmaAdjustment, CmaRun, MarketObservation, MarketSeries

ROOT = Path(__file__).resolve().parents[2]


def _sha(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def code_version() -> str:
    """The git commit, with "-dirty" when the tree has changes; env SOIVI_CODE_VERSION otherwise."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get("SOIVI_CODE_VERSION", "unknown")
    return f"{sha}-dirty" if dirty else sha


def input_manifest(session: Session, codes: Iterable[str]) -> dict[str, Any]:
    """code -> {first, last, count, sha256 of (period_end, revision, value), snapshot ids}."""
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
        select(
            MarketSeries.code,
            MarketObservation.period_end,
            MarketObservation.revision,
            MarketObservation.value,
            MarketObservation.snapshot_id,
        )
        .join(MarketSeries, MarketSeries.id == MarketObservation.series_id)
        .join(
            latest,
            (MarketObservation.series_id == latest.c.series_id)
            & (MarketObservation.period_end == latest.c.period_end)
            & (MarketObservation.revision == latest.c.revision),
        )
        .where(MarketSeries.code.in_(sorted(set(codes))))
        .order_by(MarketSeries.code, MarketObservation.period_end)
    )
    grouped: dict[str, list[tuple[str, int, str, int]]] = {}
    for code, end, revision, value, snapshot_id in rows:
        grouped.setdefault(code, []).append((end.isoformat(), revision, str(value), snapshot_id))
    return {
        code: {
            "first": values[0][0],
            "last": values[-1][0],
            "count": len(values),
            "sha256": _sha([v[:3] for v in values]),
            "snapshots": sorted({v[3] for v in values}),
        }
        for code, values in grouped.items()
    }


def load_inputs(session: Session, as_of: pd.Timestamp | None = None) -> dict[str, Any]:
    codes = sorted({*NEEDED_CODES, *needed_codes(SeriesConfig())})
    obs = load_observations(session, codes)
    ends = [s.index.max() for c, s in obs.items() if not s.empty and c in needed_codes()]
    starts = [s.index.min() for s in obs.values() if not s.empty]
    if not ends:
        raise ValueError("no market observations: run `python -m pipeline market ingest`")
    if as_of is None:  # the last month end that VN30 and the HNX curve both have
        as_of = min(obs["vn30_close"].index.max(), obs["hnx_par_10y"].index.max())
    months = month_index(min(starts), max(ends))
    savings = load_savings_12m(session, SeriesConfig().big_banks, months)
    return {"obs": obs, "savings": savings, "as_of": as_of, "codes": codes}


def run_model(loaded: dict[str, Any], cfg: CmaConfig) -> dict[str, Any]:
    """Returns, statistics and building blocks for loaded inputs (no database writes)."""
    obs, savings, as_of = loaded["obs"], loaded["savings"], loaded["as_of"]
    dp = {
        k: obs[k].dropna().iloc[-1] / 100 for k in ("dp_vn30", "dp_vnmid", "dp_vnsml") if k in obs
    }
    series_cfg = SeriesConfig(
        dp_eq_large=dp.get("dp_vn30"),
        dp_eq_midsmall=(dp["dp_vnmid"] + dp["dp_vnsml"]) / 2
        if {"dp_vnmid", "dp_vnsml"} <= set(dp)
        else None,
    )
    trimmed = {k: v[v.index <= as_of] for k, v in obs.items()}
    returns, coverage = build_returns(
        Inputs(trimmed, savings[savings.index <= as_of] if len(savings) else savings), series_cfg
    )
    stats = compute_stats(returns)
    saved = savings.dropna()
    output = compute(
        obs, stats, returns, cfg, as_of, savings_12m=float(saved.iloc[-1]) if len(saved) else None
    )
    output["coverage"] = [vars(c) for c in coverage]
    return output


def create_run(
    session: Session,
    cfg: CmaConfig,
    created_by: str,
    as_of: pd.Timestamp | None = None,
    *,
    reuse_same: bool = False,
) -> CmaRun:
    """Compute and store one run with its adjustments. The caller commits.

    `reuse_same`: if the latest run has the same inputs, config and code version, return
    it instead of storing a copy (the monthly job re-run on the same day adds nothing)."""
    loaded = load_inputs(session, as_of)
    output = run_model(loaded, cfg)
    inputs = {
        "series": input_manifest(session, loaded["codes"]),
        "savings_12m": {
            "banks": list(SeriesConfig().big_banks),
            "months": int(loaded["savings"].notna().sum()),
            "sha256": _sha(
                [
                    [f"{k:%Y-%m-%d}", round(float(v), 6)]
                    for k, v in loaded["savings"].dropna().items()
                ]
            ),
        },
    }
    inputs_sha256, version = _sha(inputs), code_version()
    if reuse_same:
        latest = session.scalar(select(CmaRun).order_by(CmaRun.id.desc()))
        if latest is not None and (
            latest.inputs_sha256,
            latest.config_sha256,
            latest.code_version,
        ) == (inputs_sha256, cfg.sha256, version):
            return latest
    run = CmaRun(
        created_by=created_by,
        as_of=loaded["as_of"].date() if hasattr(loaded["as_of"], "date") else loaded["as_of"],
        methodology_version=cfg.methodology_version,
        code_version=version,
        config_sha256=cfg.sha256,
        inputs_sha256=inputs_sha256,
        config=cfg.raw,
        inputs=inputs,
        output=to_json(output),
    )
    session.add(run)
    session.flush()
    for a in cfg.adjustments:
        session.add(
            CmaAdjustment(
                run_id=run.id,
                asset_class=a.asset_class,
                delta_pp=Decimal(str(a.delta_pp)),
                reason=a.reason,
                author=a.author,
            )
        )
    return run


def to_json(obj: Any) -> Any:
    """JSON-ready copy: dates as ISO text, numpy scalars as Python, NaN/inf as null."""

    def clean(x: Any) -> Any:
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, list | tuple):
            return [clean(v) for v in x]
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return x

    return clean(json.loads(json.dumps(obj, default=_json_default)))


def _json_default(obj: Any) -> Any:
    if isinstance(obj, dt.date | pd.Timestamp):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy scalars
        return obj.item()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")
