"""`python -m pipeline market monthly`: the VNCMA job the Mac runs once a month.

vnstock is tied to the Mac where it was registered, so this runs there (launchd,
scripts/install-vncma-launchd.sh), not in the Docker scheduler. Steps:

1. Ingest every active market series (Neon + S3, from .env).
2. Compute a draft run. If nothing changed since the latest run (same inputs, config
   and code), the latest run is reused, so a second run on the same day adds nothing.
3. Tell the owner (Telegram, or printed): the draft to review, ingest failures,
   failed sanity checks, and deadlines that are close.

It never approves anything: a release still needs a named reviewer in the review app.
"""

import datetime as dt
import html
from collections.abc import Sequence
from dataclasses import dataclass, field

# Dates by which something in the market pipeline must be changed (DECISIONS 2026-11-06).
DEADLINES: tuple[tuple[dt.date, str], ...] = (
    (
        dt.date(2027, 7, 16),
        "HNX intermediate certificate (pipeline/market/certs) expires: fetch the new one",
    ),
    (
        dt.date(2027, 10, 27),
        "vnstock-quant 0.5.0 release expires: upgrade it (pe_bu_* depend on it)",
    ),
)
WARN_DAYS = 75


@dataclass
class MonthlyReport:
    groups: int = 0
    new: int = 0
    revised: int = 0
    failed: list[str] = field(default_factory=list)
    run_id: int | None = None
    run_is_new: bool = False
    as_of: str | None = None
    headline: dict[str, float] = field(default_factory=dict)
    failed_checks: list[str] = field(default_factory=list)
    compute_error: str | None = None
    fund_run_id: int | None = None
    fund_run_is_new: bool = False
    fund_as_of: str | None = None
    fund_flagged: list[str] = field(default_factory=list)
    fund_error: str | None = None
    deadlines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and self.compute_error is None and self.fund_error is None


def due_deadlines(
    today: dt.date, deadlines: Sequence[tuple[dt.date, str]] = DEADLINES
) -> list[str]:
    out = []
    for when, what in deadlines:
        days = (when - today).days
        if days <= WARN_DAYS:
            state = f"{-days} days overdue" if days < 0 else f"in {days} days"
            out.append(f"{when.isoformat()} ({state}): {what}")
    return out


def message(report: MonthlyReport, review_url: str) -> str:
    """Telegram HTML."""
    e = html.escape
    lines = ["<b>VNCMA monthly</b>"]
    lines.append(
        f"Ingest: {report.groups} groups, {report.new} new, {report.revised} revised, "
        f"{len(report.failed)} failed"
    )
    lines += [f"  ✗ {e(f)}" for f in report.failed[:10]]
    if report.compute_error:
        lines.append(f"Compute failed: {e(report.compute_error)}")
    elif report.run_id is not None:
        state = "new draft" if report.run_is_new else "no change since"
        lines.append(f"Run {report.run_id} ({state}), data to {report.as_of}")
        lines.append("  " + ", ".join(f"{k} {v:.2f}" for k, v in report.headline.items()))
        lines += [f"  ⚠ {e(c)}" for c in report.failed_checks]
        if report.run_is_new:
            lines.append(f"Review and approve: {e(review_url)}/vncma/runs/{report.run_id}")
    if report.fund_error:
        lines.append(f"Fund stats failed: {e(report.fund_error)}")
    elif report.fund_run_id is not None:
        state = "new draft" if report.fund_run_is_new else "no change since"
        lines.append(f"Fund stats run {report.fund_run_id} ({state}), data to {report.fund_as_of}")
        if report.fund_flagged:
            lines.append(f"  ⚠ data flagged: {e(', '.join(report.fund_flagged))}")
        if report.fund_run_is_new:
            lines.append(f"Review and approve: {e(review_url)}/funds/runs/{report.fund_run_id}")
    lines += [f"⏰ {e(d)}" for d in report.deadlines]
    return "\n".join(lines)
