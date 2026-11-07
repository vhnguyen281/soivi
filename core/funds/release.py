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
    """What a release publishes: groups, benchmarks and the derived per-fund figures
    (returns, volatility, drawdown). Raw NAV series are never published (vnstock licence);
    per-fund NAVs come from vnstock and are not checked with each manager (DECISIONS 2026-11-07)."""
    return payload


def create_run(session: Session, created_by: str, *, reuse_same: bool = False) -> FundStatsRun:
    """Store a draft run. With reuse_same, the latest run is returned instead when its inputs
    (NAV observations and the universe file) and code version are unchanged."""
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
        json.dumps({"series": manifest, "universe": universe}, sort_keys=True, default=str).encode()
    ).hexdigest()
    version = code_version()
    if reuse_same:
        latest = session.scalar(select(FundStatsRun).order_by(FundStatsRun.id.desc()).limit(1))
        if latest and latest.inputs_sha256 == inputs_sha and latest.code_version == version:
            return latest
    run = FundStatsRun(
        created_by=created_by.strip(),
        as_of=as_of.date(),
        code_version=version,
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
