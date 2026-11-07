"""Review pages for the fund-group statistics (phase A)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import FundStatsRelease, FundStatsRun

GROUP_VI = {
    "equity_fund": "Quỹ cổ phiếu",
    "bond_fund": "Quỹ trái phiếu",
    "balanced_fund": "Quỹ cân bằng",
    "etf": "ETF và quỹ niêm yết",
}
BENCH_VI = {"eq_large": "VN30 (gồm cổ tức)", "cash_vnd": "Tiền gửi 12 tháng", "balanced": "50/50"}


def runs(session: Session) -> list[dict[str, Any]]:
    approved = {r.run_id: r for r in session.scalars(select(FundStatsRelease))}
    out = []
    for run in session.scalars(select(FundStatsRun).order_by(FundStatsRun.id.desc()).limit(30)):
        out.append({"run": run, "release": approved.get(run.id)})
    return out


def run_view(session: Session, run_id: int) -> dict[str, Any] | None:
    run = session.get(FundStatsRun, run_id)
    if run is None:
        return None
    release = session.scalar(select(FundStatsRelease).where(FundStatsRelease.run_id == run_id))
    return {
        "run": run,
        "release": release,
        "doc": run.payload,
        "groups_vi": GROUP_VI,
        "bench_vi": BENCH_VI,
    }
