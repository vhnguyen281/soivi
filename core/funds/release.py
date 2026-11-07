"""Fund-group statistics: store a run, approve it for publication (principle 4)."""

import hashlib
import json
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.cma.run import code_version, input_manifest, load_inputs, to_json
from core.cma.series import Inputs, SeriesConfig, build_returns, load_observations
from core.funds.stats import compute
from core.funds.universe import load_universe
from core.models import FundStatsRelease, FundStatsRun

# The as_of month needs a value for at least this share of the funds.
MIN_COVERAGE = 0.8


class FundStatsError(Exception):
    pass


def benchmarks(session: Session) -> dict[str, pd.Series]:
    """VNCMA's monthly log returns for VN30 (with dividend yield) and 12-month deposits."""
    loaded = load_inputs(session)
    obs = loaded["obs"]
    dp = obs.get("dp_vn30")
    cfg = SeriesConfig(
        dp_eq_large=float(dp.dropna().iloc[-1]) / 100
        if dp is not None and len(dp.dropna())
        else None
    )
    returns, _ = build_returns(Inputs(obs, loaded["savings"]), cfg)
    return {k: returns[k].dropna() for k in ("eq_large", "cash_vnd") if k in returns}


def pick_as_of(levels: dict[str, pd.Series], bench: dict[str, pd.Series]) -> pd.Timestamp:
    """The latest month end that the benchmarks and at least MIN_COVERAGE of the funds have."""
    ends = sorted({e for s in levels.values() for e in s.index}, reverse=True)
    limit = min((s.index.max() for s in bench.values()), default=None)
    for end in ends:
        if limit is not None and end > limit:
            continue
        if sum(end in s.index for s in levels.values()) >= MIN_COVERAGE * len(levels):
            return end
    raise FundStatsError(
        "no month end with enough fund NAVs: run `python -m pipeline market ingest`"
    )


def public(payload: dict[str, Any]) -> dict[str, Any]:
    """Groups and benchmarks only. Per-fund rows wait for phase B (NAV confirmed by the manager)."""
    return {k: v for k, v in payload.items() if k != "funds"}


def create_run(session: Session, created_by: str) -> FundStatsRun:
    if not created_by.strip():
        raise FundStatsError("a name is required (--by)")
    universe = load_universe()
    if not universe:
        raise FundStatsError(
            "data/funds/universe.yaml is empty: run `python -m pipeline market fund-series`"
        )
    codes = [f["code"] for f in universe]
    levels = {k: v for k, v in load_observations(session, codes).items() if not v.empty}
    if len(levels) < MIN_COVERAGE * len(codes):
        raise FundStatsError(f"only {len(levels)} of {len(codes)} fund series have data")
    bench = benchmarks(session)
    as_of = pick_as_of(levels, bench)
    payload = to_json(compute(universe, levels, bench, as_of))
    manifest = input_manifest(session, sorted(levels))
    inputs_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, default=str).encode()
    ).hexdigest()
    run = FundStatsRun(
        created_by=created_by.strip(),
        as_of=as_of.date(),
        code_version=code_version(),
        inputs_sha256=inputs_sha,
        inputs=to_json(manifest),
        payload=payload,
    )
    session.add(run)
    session.flush()
    return run


def approve(session: Session, run_id: int, reviewer: str) -> FundStatsRelease:
    if not reviewer.strip():
        raise FundStatsError("the reviewer's name is required")
    run = session.get(FundStatsRun, run_id)
    if run is None:
        raise FundStatsError(f"no fund statistics run {run_id}")
    if session.scalar(select(FundStatsRelease).where(FundStatsRelease.run_id == run_id)):
        raise FundStatsError(f"run {run_id} is already approved")
    body = public(run.payload)
    release = FundStatsRelease(
        run_id=run.id,
        approved_by=reviewer.strip(),
        payload=body,
        payload_sha256=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
    )
    session.add(release)
    session.flush()
    return release


def latest_release(session: Session) -> FundStatsRelease | None:
    return session.scalar(
        select(FundStatsRelease)
        .order_by(FundStatsRelease.approved_at.desc(), FundStatsRelease.id.desc())
        .limit(1)
    )
