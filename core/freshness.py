"""Is an institution's data still being checked? A computed flag for the API and site.

A monitored source (active, confirmed, with a URL and an adapter) is *stale* when:

- it has failed `max_consecutive_failures` times in a row, or
- it has never been fetched successfully, or
- its last success is older than `max_age_cadence_multiple` x its cadence.

An institution is "unverified" if any of its monitored sources is stale,
"no_sources" if it has none, otherwise "verified". Nothing is stored: compute it
when needed, so it is never out of date itself.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Institution, Source

State = Literal["verified", "unverified", "no_sources"]


@dataclass(frozen=True)
class StalenessPolicy:
    max_consecutive_failures: int = 2
    max_age_cadence_multiple: Decimal = Decimal(2)


@dataclass
class SourceStatus:
    source_id: int
    kind: str
    variant: str
    reasons: list[str]

    @property
    def stale(self) -> bool:
        return bool(self.reasons)


@dataclass
class InstitutionFreshness:
    institution_id: int
    short_name: str
    state: State
    sources: list[SourceStatus] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.state == "verified"

    @property
    def stale_sources(self) -> list[SourceStatus]:
        return [s for s in self.sources if s.stale]


def source_staleness(source: Source, now: dt.datetime, policy: StalenessPolicy) -> list[str]:
    """Reasons the source is stale; empty if it is fresh."""
    reasons = []
    if source.consecutive_failures >= policy.max_consecutive_failures:
        reasons.append(f"{source.consecutive_failures} failed fetches in a row")
    if source.last_success_at is None:
        reasons.append("never fetched successfully")
    else:
        max_age = dt.timedelta(hours=float(source.cadence_hours * policy.max_age_cadence_multiple))
        age = now - source.last_success_at
        if age > max_age:
            hours = int(age.total_seconds() // 3600)
            reasons.append(
                f"last success {hours} h ago (limit {policy.max_age_cadence_multiple} x "
                f"{source.cadence_hours} h)"
            )
    return reasons


def institution_freshness(
    session: Session,
    now: dt.datetime | None = None,
    policy: StalenessPolicy | None = None,
) -> dict[int, InstitutionFreshness]:
    now = now or dt.datetime.now(dt.UTC)
    policy = policy or StalenessPolicy()
    monitored = session.scalars(
        select(Source).where(
            Source.active.is_(True),
            Source.needs_check.is_(False),
            Source.url.is_not(None),
            Source.adapter_name.is_not(None),
            Source.institution_id.is_not(None),
        )
    ).all()
    by_institution: dict[int, list[Source]] = {}
    for source in monitored:
        assert source.institution_id is not None
        by_institution.setdefault(source.institution_id, []).append(source)

    result: dict[int, InstitutionFreshness] = {}
    for inst in session.scalars(select(Institution).order_by(Institution.short_name)):
        statuses = [
            SourceStatus(s.id, s.kind.value, s.variant, source_staleness(s, now, policy))
            for s in by_institution.get(inst.id, [])
        ]
        if not statuses:
            state: State = "no_sources"
        elif any(s.stale for s in statuses):
            state = "unverified"
        else:
            state = "verified"
        result[inst.id] = InstitutionFreshness(inst.id, inst.short_name, state, statuses)
    return result
