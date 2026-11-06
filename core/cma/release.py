"""Approving a VNCMA release (Prompt 8): a named reviewer turns one run into an
immutable `cma_release` (principle 4). Nothing is published before this.

Version names: "<year>.<n>", the year after the data's as-of year (the assumptions are
for the years ahead), n counting that year's releases. The draft of the next release
is shown as "<version>-draft".
"""

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.cma.report import payload, payload_sha256
from core.cma.stats import is_valid_correlation
from core.models import CmaRelease, CmaReleaseValue, CmaRun

VERSION = re.compile(r"\d{4}\.\d{1,3}")


class ReleaseError(ValueError):
    pass


def next_version(session: Session, run: CmaRun) -> str:
    year = run.as_of.year + 1
    count = session.scalar(
        select(func.count()).select_from(CmaRelease).where(CmaRelease.version.like(f"{year}.%"))
    )
    return f"{year}.{(count or 0) + 1}"


def latest_release(session: Session) -> CmaRelease | None:
    return session.scalar(
        select(CmaRelease).order_by(CmaRelease.approved_at.desc(), CmaRelease.id.desc())
    )


def release_of(session: Session, run_id: int) -> CmaRelease | None:
    return session.scalar(select(CmaRelease).where(CmaRelease.run_id == run_id))


def _dec(x: str | None) -> Decimal | None:
    return None if x is None else Decimal(x)


def approve(
    session: Session,
    run_id: int,
    version: str,
    reviewer: str,
    note: str = "",
    now: dt.datetime | None = None,
) -> CmaRelease:
    """Create the release. The caller commits."""
    reviewer, version = reviewer.strip(), version.strip()
    if not reviewer:
        raise ReleaseError("a named reviewer is required")
    if not VERSION.fullmatch(version):
        raise ReleaseError(f"version {version!r} must look like 2027.1")
    run = session.get(CmaRun, run_id)
    if run is None:
        raise ReleaseError(f"no run {run_id}")
    if release_of(session, run_id) is not None:
        raise ReleaseError(f"run {run_id} is already released")
    if session.scalar(select(CmaRelease).where(CmaRelease.version == version)) is not None:
        raise ReleaseError(f"version {version} already exists")
    matrix = np.array(run.output["correlation"]["matrix"], dtype=float)
    if not is_valid_correlation(matrix):
        raise ReleaseError("the run's correlation matrix is not valid: re-run compute")
    when = now or dt.datetime.now(dt.UTC)
    doc = payload(run, version, status="released", approved_by=reviewer, approved_at=when)
    release = CmaRelease(
        version=version,
        run_id=run.id,
        methodology_version=run.methodology_version,
        approved_by=reviewer,
        approved_at=when,
        note=note.strip() or None,
        payload=doc,
        payload_sha256=payload_sha256(doc),
    )
    session.add(release)
    session.flush()
    for c in doc["classes"]:
        band = c["band_80"] or [None, None]
        session.add(
            CmaReleaseValue(
                release_id=release.id,
                asset_class=c["id"],
                expected_return=Decimal(c["expected_return"]),
                model_return=Decimal(c["model_return"]),
                adjustment_pp=Decimal(c["adjustment_pp"]),
                arithmetic_return=_dec(c["arithmetic_return"]),
                volatility=_dec(c["volatility"]),
                band_low=_dec(band[0]),
                band_high=_dec(band[1]),
                grade=c["grade"],
            )
        )
    return release


def previous_payload(session: Session, before: CmaRelease | None = None) -> dict[str, Any] | None:
    """The payload of the latest release (before `before`, if given)."""
    query = select(CmaRelease).order_by(CmaRelease.approved_at.desc(), CmaRelease.id.desc())
    if before is not None:
        query = query.where(CmaRelease.id < before.id)
    release = session.scalar(query)
    return None if release is None else release.payload
