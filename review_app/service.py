"""Review logic, independent of HTTP: what the queue shows and what the buttons do.

Every decision goes through core/versioning (approve_version / reject_version), so
the versioning rules and DB guards apply, and is written to the review_action
audit log in the same transaction.
"""

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import ReviewActionKind, ReviewTaskKind, ReviewTaskStatus, VersionStatus
from core.models import (
    VERSIONED_MODELS,
    ReviewAction,
    ReviewTask,
    Snapshot,
    Source,
    Versioned,
)
from core.versioning import VersioningError, approve_version, reject_version, retire_version

MODELS: dict[str, type[Versioned]] = {m.__tablename__: m for m in VERSIONED_MODELS}


class ReviewError(Exception):
    """A review action that can't be done (wrong state, unknown row, missing note)."""


# --------------------------------------------------------------------------- queue


@dataclass
class QueueRow:
    task_id: int
    created_at: dt.datetime
    institution: str
    source: str
    new: int
    changed: int
    removed: int
    pending: int
    warnings: int


def open_tasks(session: Session) -> list[QueueRow]:
    """Open version-review tasks, oldest first."""
    tasks = session.scalars(
        select(ReviewTask)
        .where(
            ReviewTask.status == ReviewTaskStatus.OPEN,
            ReviewTask.kind == ReviewTaskKind.VERSION_REVIEW,
        )
        .order_by(ReviewTask.created_at, ReviewTask.id)
    ).all()
    pending = _pending_counts(session, [t.id for t in tasks])
    rows = []
    for task in tasks:
        payload = task.payload_json or {}
        summary = payload.get("summary", {})
        source = session.get(Source, task.source_id) if task.source_id else None
        rows.append(
            QueueRow(
                task_id=task.id,
                created_at=task.created_at,
                institution=payload.get("institution") or "-",
                source=_source_label(source),
                new=summary.get("new", 0),
                changed=summary.get("changed", 0),
                removed=summary.get("removed", 0),
                pending=pending.get(task.id, 0),
                warnings=len(payload.get("warnings", [])),
            )
        )
    return rows


def _pending_counts(session: Session, task_ids: list[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    if not task_ids:
        return counts
    for model in MODELS.values():
        for task_id, n in session.execute(
            select(model.review_task_id, func.count())
            .where(model.review_task_id.in_(task_ids), model.status == VersionStatus.PENDING)
            .group_by(model.review_task_id)
        ):
            if task_id is not None:
                counts[task_id] = counts.get(task_id, 0) + n
    return counts


def _source_label(source: Source | None) -> str:
    if source is None:
        return "-"
    return "/".join(x for x in (source.kind.value, source.variant) if x)


# --------------------------------------------------------------------------- task page


@dataclass
class FieldView:
    name: str
    old: Any
    new: Any
    changed: bool
    # LLM-extracted values: where the value was read ({"page", "quote", "value"}).
    evidence: dict[str, Any] | None = None


@dataclass
class ItemView:
    index: int
    change: str  # new | changed | removed
    table: str
    version_id: int | None
    status: str  # pending | approved | rejected | superseded | live (removed items)
    label: str
    fields: list[FieldView]
    effective_from: str | None
    source_page: int | None
    warnings: list[str] = field(default_factory=list)
    # Evidence for the row itself (e.g. which reward a card_reward row is).
    row_evidence: dict[str, Any] | None = None
    # The version is live: it can be taken down ("Gỡ") without a successor.
    retirable: bool = False

    @property
    def actionable(self) -> bool:
        return self.change != "removed" and self.status == VersionStatus.PENDING.value


@dataclass
class TaskView:
    task: ReviewTask
    institution: str
    source: str
    snapshot: Snapshot | None
    items: list[ItemView]
    warnings: list[dict[str, Any]]
    pending: int
    # News items that triggered or corroborate this re-check (context, never values).
    news: list[dict[str, Any]] = field(default_factory=list)


def task_view(session: Session, task_id: int) -> TaskView:
    task = _task(session, task_id)
    payload = task.payload_json or {}
    warnings: list[dict[str, Any]] = payload.get("warnings", [])
    by_key: dict[str, list[str]] = {}
    for w in warnings:
        by_key.setdefault(_wkey(w["table"], w["key"]), []).append(w["message"])

    items = []
    for i, raw in enumerate(payload.get("items", [])):
        model = MODELS.get(raw["table"])
        version = session.get(model, raw["version_id"]) if model and raw["version_id"] else None
        live = (
            version is not None
            and version.status is VersionStatus.APPROVED
            and version.valid_to is None
        )
        if raw["change"] == "removed":
            status = "live" if live else "retired"
        else:
            status = version.status.value if version is not None else "missing"
        old, new = raw.get("old") or {}, raw.get("new") or {}
        evidence: dict[str, Any] = raw.get("evidence") or {}
        names = _field_order(list(new or old))
        if raw["change"] == "new":
            # Nothing to compare: hide fields the bank doesn't state (None / False).
            names = [n for n in names if new.get(n) not in (None, False)]
        items.append(
            ItemView(
                index=i,
                change=raw["change"],
                table=raw["table"],
                version_id=raw["version_id"],
                status=status,
                label=raw.get("label") or describe_key(raw["table"], raw["key"]),
                fields=[
                    FieldView(
                        n, old.get(n), new.get(n), n in raw.get("fields", []), evidence.get(n)
                    )
                    for n in names
                ],
                row_evidence=evidence.get("reward"),
                retirable=live,
                effective_from=raw.get("effective_from"),
                source_page=raw.get("source_page"),
                warnings=by_key.get(_wkey(raw["table"], raw["key"]), []),
            )
        )
    source = session.get(Source, task.source_id) if task.source_id else None
    snapshot = session.get(Snapshot, task.snapshot_id) if task.snapshot_id else None
    return TaskView(
        task=task,
        institution=payload.get("institution") or "-",
        source=_source_label(source),
        snapshot=snapshot,
        items=items,
        warnings=warnings,
        pending=_pending_counts(session, [task.id]).get(task.id, 0),
        news=payload.get("news", []),
    )


def item_view(session: Session, task_id: int, table: str, version_id: int) -> ItemView:
    for item in task_view(session, task_id).items:
        if item.table == table and item.version_id == version_id:
            return item
    raise ReviewError(f"{table} {version_id} is not part of task {task_id}")


def _field_order(names: list[str]) -> list[str]:
    """Rates first: they are what a reviewer checks against the bank's page."""
    return sorted(names, key=lambda n: (not n.endswith("_pct"), names.index(n)))


def describe_key(table: str, key: dict[str, Any]) -> str:
    """A short human label for a series key, without database ids."""
    if table == "savings_rate":
        if key.get("term_days"):
            term = f"{key['term_days']} ngày"
        elif key.get("term_months"):
            term = f"{key['term_months']} tháng"
        else:
            term = "Không kỳ hạn"
        amount = key.get("min_amount_vnd") or 0
        parts = [
            key.get("product_name"),
            key.get("channel"),
            term,
            f"từ {amount:,} đ".replace(",", ".") if amount else None,
            key.get("interest_payment"),
            f"vùng {key['region']}" if key.get("region") else None,
        ]
        return " · ".join(str(p) for p in parts if p)
    return " · ".join(f"{k}={v}" for k, v in key.items() if not k.endswith("_id"))


def _wkey(table: str, key: dict[str, Any]) -> str:
    return table + json.dumps(key, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------- actions


@dataclass
class ActionResult:
    decided: int
    skipped: int
    task_status: str


def approve_all(
    session: Session, task_id: int, reviewer: str, now: dt.datetime | None = None
) -> ActionResult:
    return _decide_all(session, task_id, reviewer, approve=True, note=None, now=now)


def reject_all(
    session: Session, task_id: int, reviewer: str, now: dt.datetime | None = None
) -> ActionResult:
    return _decide_all(session, task_id, reviewer, approve=False, note=None, now=now)


def needs_fix(
    session: Session, task_id: int, reviewer: str, note: str, now: dt.datetime | None = None
) -> ActionResult:
    """Flag the task for a developer. Its pending values are rejected so nothing wrong
    can go live; a corrected run proposes them again."""
    if not note.strip():
        raise ReviewError("'Cần sửa' needs a note saying what is wrong")
    return _decide_all(session, task_id, reviewer, approve=False, note=note.strip(), now=now)


def decide_version(
    session: Session,
    task_id: int,
    table: str,
    version_id: int,
    reviewer: str,
    *,
    approve: bool,
    now: dt.datetime | None = None,
) -> ActionResult:
    now = _now(now)
    task = _open_task(session, task_id)
    model = MODELS.get(table)
    if model is None:
        raise ReviewError(f"unknown table {table!r}")
    version = session.get(model, version_id)
    if version is None or version.review_task_id != task.id:
        raise ReviewError(f"{table} {version_id} is not part of task {task_id}")
    try:
        if approve:
            approve_version(session, model, version_id, reviewer=reviewer, now=now)
        else:
            reject_version(session, model, version_id, reviewer=reviewer, now=now)
    except VersioningError as exc:
        raise ReviewError(str(exc)) from exc
    _log(
        session,
        task,
        ReviewActionKind.APPROVE if approve else ReviewActionKind.REJECT,
        reviewer,
        [version_id],
        table,
        now=now,
    )
    _close_if_done(session, task, reviewer, now)
    return ActionResult(1, 0, task.status.value)


def _decide_all(
    session: Session,
    task_id: int,
    reviewer: str,
    *,
    approve: bool,
    note: str | None,
    now: dt.datetime | None,
) -> ActionResult:
    now = _now(now)
    task = _open_task(session, task_id)
    decided: list[int] = []
    skipped = 0
    tables = set()
    for model in MODELS.values():
        for version in session.scalars(
            select(model).where(model.review_task_id == task.id).order_by(model.id)
        ):
            if version.status != VersionStatus.PENDING:
                skipped += 1  # superseded by a newer snapshot, or decided row by row
                continue
            if approve:
                approve_version(session, model, version.id, reviewer=reviewer, now=now)
            else:
                reject_version(session, model, version.id, reviewer=reviewer, now=now)
            decided.append(version.id)
            tables.add(model.__tablename__)

    if note is not None:
        kind, status = ReviewActionKind.NEEDS_FIX, ReviewTaskStatus.NEEDS_FIX
    elif approve:
        kind, status = ReviewActionKind.APPROVE_ALL, ReviewTaskStatus.APPROVED
    else:
        kind, status = ReviewActionKind.REJECT_ALL, ReviewTaskStatus.REJECTED
    _log(session, task, kind, reviewer, decided, ",".join(sorted(tables)) or None, note, now)
    task.status, task.reviewer, task.decided_at, task.note = status, reviewer, now, note
    session.flush()
    return ActionResult(len(decided), skipped, status.value)


def _close_if_done(session: Session, task: ReviewTask, reviewer: str, now: dt.datetime) -> None:
    """When no pending row is left, the task is approved if anything was approved."""
    if _pending_counts(session, [task.id]).get(task.id, 0):
        return
    approved = any(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.review_task_id == task.id, model.status == VersionStatus.APPROVED)
        )
        for model in MODELS.values()
    )
    task.status = ReviewTaskStatus.APPROVED if approved else ReviewTaskStatus.REJECTED
    task.reviewer, task.decided_at = reviewer, now
    session.flush()


def _log(
    session: Session,
    task: ReviewTask,
    kind: ReviewActionKind,
    reviewer: str,
    version_ids: list[int],
    table: str | None,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> None:
    session.add(
        ReviewAction(
            review_task_id=task.id,
            action=kind,
            version_table=table,
            version_ids=version_ids,
            reviewer=reviewer,
            note=note,
            created_at=_now(now),
        )
    )
    session.flush()


def retire(
    session: Session,
    task_id: int,
    table: str,
    version_id: int,
    reviewer: str,
    note: str,
    now: dt.datetime | None = None,
) -> ActionResult:
    """Take a live value down without a successor: the bank no longer states it,
    or it no longer meets the reading rules. The row stays in history; the audit
    log keeps who did it and why."""
    if not note.strip():
        raise ReviewError("'Gỡ' needs a note saying why the value comes down")
    now = _now(now)
    task = _task(session, task_id)
    model = MODELS.get(table)
    if model is None:
        raise ReviewError(f"unknown table {table!r}")
    if not any(
        i.get("table") == table and i.get("version_id") == version_id
        for i in (task.payload_json or {}).get("items", [])
    ):
        raise ReviewError(f"{table} {version_id} is not part of task {task_id}")
    try:
        retire_version(session, model, version_id, now=now)
    except VersioningError as exc:
        raise ReviewError(str(exc)) from exc
    _log(session, task, ReviewActionKind.RETIRE, reviewer, [version_id], table, note.strip(), now)
    return ActionResult(decided=1, skipped=0, task_status=task.status.value)


def audit_log(session: Session, limit: int = 200) -> list[tuple[ReviewAction, str]]:
    """Newest actions first, with the institution they concern."""
    rows = session.execute(
        select(ReviewAction, ReviewTask.payload_json)
        .join(ReviewTask, ReviewTask.id == ReviewAction.review_task_id)
        .order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc())
        .limit(limit)
    ).all()
    return [(action, (payload or {}).get("institution") or "-") for action, payload in rows]


def _task(session: Session, task_id: int) -> ReviewTask:
    task = session.get(ReviewTask, task_id)
    if task is None or task.kind != ReviewTaskKind.VERSION_REVIEW:
        raise ReviewError(f"no review task {task_id}")
    return task


def _open_task(session: Session, task_id: int) -> ReviewTask:
    task = _task(session, task_id)
    if task.status != ReviewTaskStatus.OPEN:
        raise ReviewError(f"task {task_id} is already {task.status.value}")
    return task


def _now(now: dt.datetime | None) -> dt.datetime:
    return now or dt.datetime.now(dt.UTC)
