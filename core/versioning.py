"""Read and change versioned values (SavingsRate, CardTerms, CardReward, CardPerk, CardInterest).

Rules (CLAUDE.md principles 3 and 4):
- A row's values never change. A change is a new row.
- A new row starts as `pending` and goes live only when a human approves it.
- Proposing the values that are already live creates nothing ("unchanged passes").

Each helper runs in a savepoint, so it either applies fully or not at all. The
caller owns the outer transaction and commits it. The database backs these rules
with constraints and triggers (see the initial migration).
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from sqlalchemy import Select, inspect, select
from sqlalchemy.orm import Session

from core.enums import ExtractionMethod, VersionStatus
from core.models import LIFECYCLE_COLUMNS, PROVENANCE_COLUMNS, ChangeEvent, Versioned

SYSTEM_REVIEWER = "system"


class VersioningError(Exception):
    """A versioning rule was broken (bad input, or wrong state for the action)."""


@dataclass(frozen=True)
class ProposeResult[V: Versioned]:
    # unchanged:       values equal the live version; nothing new was written
    # already_pending: an identical proposal is already waiting for review
    # proposed:        a new pending version was created
    outcome: Literal["unchanged", "already_pending", "proposed"]
    version: V
    # A different pending proposal that this call replaced, if any.
    superseded: V | None = None


# --------------------------------------------------------------------------- columns


def key_columns(model: type[Versioned]) -> tuple[str, ...]:
    return model.__version_key__


def value_columns(model: type[Versioned]) -> tuple[str, ...]:
    """Columns compared to decide whether a value changed."""
    skip = PROVENANCE_COLUMNS | LIFECYCLE_COLUMNS | set(model.__version_key__)
    return tuple(c.key for c in inspect(model).columns if c.key not in skip)


# --------------------------------------------------------------------------- reads


def current_select[V: Versioned](model: type[V]) -> Select[V]:
    """SELECT of every live (approved, not yet replaced) version of `model`."""
    return select(model).where(
        model.status == VersionStatus.APPROVED,
        model.valid_to.is_(None),
    )


def get_current[V: Versioned](
    session: Session, model: type[V], *, lock: bool = False, **key: Any
) -> V | None:
    """The live approved version for one key, or None."""
    _check_key(model, key)
    stmt = current_select(model).where(*_key_filter(model, key))
    return _one_or_none(session, stmt, lock)


def get_pending[V: Versioned](
    session: Session, model: type[V], *, lock: bool = False, **key: Any
) -> V | None:
    """The version waiting for review for one key, or None."""
    _check_key(model, key)
    stmt = select(model).where(model.status == VersionStatus.PENDING, *_key_filter(model, key))
    return _one_or_none(session, stmt, lock)


# --------------------------------------------------------------------------- writes


def propose_version[V: Versioned](
    session: Session,
    model: type[V],
    data: Mapping[str, Any],
    *,
    snapshot_id: int,
    extraction_method: ExtractionMethod,
    effective_from: dt.date | None = None,
    evidence: Mapping[str, Any] | None = None,
    review_task_id: int | None = None,
    now: dt.datetime | None = None,
) -> ProposeResult[V]:
    """Offer newly extracted values for review.

    `data` must hold exactly the key and value columns of `model` (use None for a
    value the bank does not state). A missing or unknown field raises, so an
    adapter can never write a partial row.
    """
    _check_data(model, data)
    now = _now(now)
    key = {c: data[c] for c in key_columns(model)}
    values = {c: data[c] for c in value_columns(model)}

    with session.begin_nested():
        current = get_current(session, model, lock=True, **key)
        pending = get_pending(session, model, lock=True, **key)

        if current is not None and _same_values(current, values):
            current.last_seen_snapshot_id = snapshot_id
            current.last_seen_at = now
            # A waiting proposal is stale once the bank shows the live values again.
            if pending is not None:
                _supersede(pending, now)
            return ProposeResult("unchanged", current, pending)

        if pending is not None and _same_values(pending, values):
            return ProposeResult("already_pending", pending)

        if pending is not None:
            _supersede(pending, now)
            session.flush()  # free the one-pending-per-key slot before inserting

        version = model(
            **data,
            snapshot_id=snapshot_id,
            extraction_method=extraction_method,
            effective_from=effective_from,
            source_evidence=dict(evidence) if evidence else None,
            review_task_id=review_task_id,
            status=VersionStatus.PENDING,
            proposed_at=now,
        )
        session.add(version)
        session.flush()
        _record_changes(session, model, version, current, values, review_task_id, now)
        return ProposeResult("proposed", version, pending)


def approve_version[V: Versioned](
    session: Session,
    model: type[V],
    version_id: int,
    *,
    reviewer: str,
    now: dt.datetime | None = None,
) -> V:
    """Make a pending version live and close the one it replaces, in one step."""
    reviewer = _check_reviewer(reviewer)
    now = _now(now)
    with session.begin_nested():
        version = _get_pending_by_id(session, model, version_id)
        key = {c: getattr(version, c) for c in key_columns(model)}
        current = get_current(session, model, lock=True, **key)
        if current is not None:
            current.valid_to = now
            session.flush()  # free the one-current-per-key slot first
        version.status = VersionStatus.APPROVED
        version.valid_from = now
        version.reviewer = reviewer
        version.decided_at = now
        session.flush()
    return version


def reject_version[V: Versioned](
    session: Session,
    model: type[V],
    version_id: int,
    *,
    reviewer: str,
    now: dt.datetime | None = None,
) -> V:
    """Turn down a pending version. The live version stays as it is."""
    reviewer = _check_reviewer(reviewer)
    now = _now(now)
    with session.begin_nested():
        version = _get_pending_by_id(session, model, version_id)
        version.status = VersionStatus.REJECTED
        version.reviewer = reviewer
        version.decided_at = now
        session.flush()
    return version


def retire_version[V: Versioned](
    session: Session,
    model: type[V],
    version_id: int,
    *,
    now: dt.datetime | None = None,
) -> V:
    """Take a live approved version down without a successor (the bank no longer
    states it, or it no longer meets the rules). Only valid_to is set: the row and
    its approval stay in history, and the series has no current value."""
    now = _now(now)
    with session.begin_nested():
        version = session.get(model, version_id, with_for_update=True)
        if version is None:
            raise VersioningError(f"{model.__tablename__} {version_id} does not exist")
        if version.status is not VersionStatus.APPROVED or version.valid_to is not None:
            raise VersioningError(
                f"{model.__tablename__} {version_id} is not live (status {version.status.value})"
            )
        version.valid_to = now
        session.flush()
    return version


# --------------------------------------------------------------------------- internals


def _now(now: dt.datetime | None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        raise VersioningError("`now` must be timezone-aware")
    return now


def _check_key(model: type[Versioned], key: Mapping[str, Any]) -> None:
    expected = set(key_columns(model))
    if set(key) != expected:
        raise VersioningError(
            f"{model.__name__} key must be exactly {sorted(expected)}, got {sorted(key)}"
        )


def _check_data(model: type[Versioned], data: Mapping[str, Any]) -> None:
    expected = set(key_columns(model)) | set(value_columns(model))
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        raise VersioningError(
            f"{model.__name__}: missing fields {sorted(missing)}, unknown fields {sorted(unknown)}"
        )
    floats = sorted(k for k, v in data.items() if isinstance(v, float))
    if floats:
        raise VersioningError(f"{model.__name__}: use Decimal or int, not float, for {floats}")


def _check_reviewer(reviewer: str) -> str:
    name = reviewer.strip()
    if not name or name == SYSTEM_REVIEWER:
        raise VersioningError("approval and rejection need a named human reviewer")
    return name


def _key_filter(model: type[Versioned], key: Mapping[str, Any]) -> list[Any]:
    return [getattr(model, c) == v for c, v in key.items()]


def _one_or_none[V: Versioned](session: Session, stmt: Select[V], lock: bool) -> V | None:
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.scalars(stmt).one_or_none()


def _get_pending_by_id[V: Versioned](session: Session, model: type[V], version_id: int) -> V:
    stmt = select(model).where(model.id == version_id)
    version = _one_or_none(session, stmt, lock=True)
    if version is None:
        raise VersioningError(f"{model.__name__} {version_id} does not exist")
    if version.status != VersionStatus.PENDING:
        raise VersioningError(
            f"{model.__name__} {version_id} is {version.status.value}, not pending"
        )
    return version


def _same_values(row: Versioned, values: Mapping[str, Any]) -> bool:
    return all(getattr(row, c) == v for c, v in values.items())


def _supersede(version: Versioned, now: dt.datetime) -> None:
    version.status = VersionStatus.SUPERSEDED
    version.reviewer = SYSTEM_REVIEWER
    version.decided_at = now


def _record_changes(
    session: Session,
    model: type[Versioned],
    version: Versioned,
    current: Versioned | None,
    values: Mapping[str, Any],
    review_task_id: int | None,
    now: dt.datetime,
) -> None:
    """One change_event per field that differs from the live version."""
    for field, new in values.items():
        old = getattr(current, field) if current is not None else None
        if old == new:
            continue
        session.add(
            ChangeEvent(
                entity=model.__tablename__,
                entity_id=version.id,
                field=field,
                old_value=_to_json(old),
                new_value=_to_json(new),
                snapshot_id=version.snapshot_id,
                detected_at=now,
                review_task_id=review_task_id,
            )
        )
    session.flush()


def _to_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value
