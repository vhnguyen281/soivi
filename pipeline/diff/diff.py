"""Compare parsed records with the current approved versions and propose changes.

For one snapshot:

- identical to the approved value -> nothing new (propose_version just records
  that the value was seen again);
- new or changed -> a pending version plus change_event rows (propose_version);
- approved series from this source that are missing from the snapshot -> listed
  as "removed" (nothing is written to the series; retiring is a follow-up);
- every new, changed or removed item, plus rule warnings, goes into ONE
  review_task for the snapshot.

Warnings never reject anything. Everything runs in a savepoint: a failure leaves
no partial versions behind.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import CardType, ExtractionMethod, ReviewTaskKind, ReviewTaskStatus, SourceKind
from core.models import (
    CardInterest,
    CardPerk,
    CardProduct,
    CardReward,
    CardTerms,
    Institution,
    ReviewTask,
    SavingsRate,
    Snapshot,
    Source,
    Versioned,
)
from core.versioning import current_select, get_current, key_columns, propose_version, value_columns
from pipeline.records import (
    CardInterestRecord,
    CardPerkRecord,
    CardRecord,
    CardRewardRecord,
    CardTermsRecord,
    Record,
    SavingsRateRecord,
)
from pipeline.validate.rules import (
    Rules,
    RuleWarning,
    _jsonable,
    check_change,
    check_effective_from,
    check_ranges,
    check_removed,
    default_rules,
)

MODELS_BY_KIND: dict[SourceKind, tuple[type[Versioned], ...]] = {
    SourceKind.SAVINGS_RATE_PAGE: (SavingsRate,),
    SourceKind.CARD_TARIFF_PDF: (CardTerms, CardReward, CardPerk),
    SourceKind.CARD_PRODUCT_PAGE: (CardTerms, CardReward, CardPerk, CardInterest),
}


class DiffError(Exception):
    """The parsed records can't be diffed (e.g. two records for the same series)."""


@dataclass
class DiffResult:
    new: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    already_pending: int = 0
    review_task_id: int | None = None
    warnings: list[RuleWarning] = field(default_factory=list)

    def __str__(self) -> str:
        task = f", review task {self.review_task_id}" if self.review_task_id else ""
        return (
            f"{self.new} new, {self.changed} changed, {self.removed} removed, "
            f"{self.unchanged} unchanged, {len(self.warnings)} warnings{task}"
        )


def diff_snapshot(
    session: Session,
    source: Source,
    snapshot: Snapshot,
    records: list[Record],
    extraction_method: ExtractionMethod,
    *,
    rules: Rules | None = None,
    now: dt.datetime | None = None,
    notes: list[RuleWarning] | None = None,
) -> DiffResult:
    """Propose the records as new versions and open ONE review task for the snapshot.

    `notes` are the adapter's own warnings (e.g. LLM values dropped because their
    quote was not found in the document); they are shown with the rule warnings.
    """
    rules = rules or default_rules()
    now = now or dt.datetime.now(dt.UTC)
    if source.institution_id is None:
        raise DiffError("source has no institution")

    with session.begin_nested():
        existing = session.scalars(
            select(ReviewTask)
            .where(
                ReviewTask.snapshot_id == snapshot.id,
                ReviewTask.kind == ReviewTaskKind.VERSION_REVIEW,
            )
            .order_by(ReviewTask.id.desc())
        ).first()
        if existing is not None and existing.status is ReviewTaskStatus.OPEN:
            # Re-parsing a snapshot whose task is still open changes nothing.
            # Once it is decided, an explicit re-parse (a corrected or extended parser,
            # or a task sent back as "needs fix") may propose again: values already
            # approved come out unchanged, so the new task holds only what is new.
            return _result_from_task(existing)

        task = ReviewTask(
            source_id=source.id,
            snapshot_id=snapshot.id,
            kind=ReviewTaskKind.VERSION_REVIEW,
            status=ReviewTaskStatus.OPEN,
            payload_json={},
        )
        session.add(task)
        session.flush()

        result = DiffResult()
        items: list[dict[str, Any]] = []
        seen: dict[type[Versioned], set[tuple[Any, ...]]] = {}
        for record in records:
            model = type(record).table
            data = _to_data(session, source.institution_id, record, result)
            key = {c: data[c] for c in key_columns(model)}
            key_tuple = tuple(key.values())
            if key_tuple in seen.setdefault(model, set()):
                raise DiffError(
                    f"two parsed records for the same {model.__tablename__} series: {key}"
                )
            seen[model].add(key_tuple)

            values = {c: data[c] for c in value_columns(model)}
            current = get_current(session, model, **key)
            old = {c: getattr(current, c) for c in value_columns(model)} if current else None

            outcome = propose_version(
                session,
                model,
                data,
                snapshot_id=snapshot.id,
                extraction_method=extraction_method,
                effective_from=record.effective_from,
                evidence=record.evidence,
                review_task_id=task.id,
                now=now,
            )
            if outcome.outcome == "unchanged":
                result.unchanged += 1
                continue
            if outcome.outcome == "already_pending":
                result.already_pending += 1  # already in an earlier snapshot's review task
                continue

            change = "new" if old is None else "changed"
            if change == "new":
                result.new += 1
            else:
                result.changed += 1
            warnings = check_ranges(rules, model.__tablename__, key, values)
            if old is not None:
                warnings += check_change(rules, model.__tablename__, key, old, values)
            warnings += check_effective_from(
                rules, model.__tablename__, key, record.effective_from, now.date()
            )
            result.warnings += warnings
            items.append(
                {
                    "change": change,
                    "table": model.__tablename__,
                    "version_id": outcome.version.id,
                    "key": key,
                    "old": old,
                    "new": values,
                    "fields": sorted(f for f in values if old is None or old[f] != values[f]),
                    "effective_from": record.effective_from,
                    "source_page": record.source_page,
                    "evidence": record.evidence,
                    "label": _label(record),
                }
            )

        for model in MODELS_BY_KIND.get(source.kind, ()):
            for current in _approved_from_source(session, model, source):
                key = {c: getattr(current, c) for c in key_columns(model)}
                if tuple(key.values()) in seen.get(model, set()):
                    continue
                result.removed += 1
                result.warnings += check_removed(rules, model.__tablename__, key)
                items.append(
                    {
                        "change": "removed",
                        "table": model.__tablename__,
                        "version_id": current.id,
                        "key": key,
                        "old": {c: getattr(current, c) for c in value_columns(model)},
                        "new": None,
                        "fields": [],
                        "effective_from": None,
                        "source_page": None,
                        "evidence": current.source_evidence,
                    }
                )

        result.warnings += notes or []
        if not items:
            session.delete(task)  # nothing for a human to review
            session.flush()
            return result

        inst = session.get(Institution, source.institution_id)
        task.payload_json = _jsonable(
            {
                "institution": inst.short_name if inst else None,
                "source_id": source.id,
                "snapshot_id": snapshot.id,
                "snapshot_url": snapshot.url,
                "summary": {
                    "new": result.new,
                    "changed": result.changed,
                    "removed": result.removed,
                    "unchanged": result.unchanged,
                    "already_pending": result.already_pending,
                },
                "items": items,
                "warnings": [w.as_json() for w in result.warnings],
            }
        )
        session.flush()
        result.review_task_id = task.id
        return result


def _to_data(
    session: Session, institution_id: int, record: Record, result: DiffResult
) -> dict[str, Any]:
    """Record -> the column dict propose_version expects (ids filled in)."""
    skip = set(record.identity_fields) | set(record.provenance_fields)
    data = {k: v for k, v in record.model_dump().items() if k not in skip}
    if isinstance(record, SavingsRateRecord):
        data["institution_id"] = institution_id
    elif isinstance(record, CardRecord):
        data["card_product_id"] = _card_product(session, institution_id, record, result)
    else:
        raise DiffError(f"don't know how to store {type(record).__name__}")
    return data


def _label(record: Record) -> str | None:
    """A readable name for card rows, whose key is only a card_product_id."""
    if not isinstance(record, CardRecord):
        return None
    parts = [record.card_name]
    if isinstance(record, CardRewardRecord):
        parts.append(f"{record.category.value}/{record.reward_type.value}")
    elif isinstance(record, CardPerkRecord):
        parts.append("đặc quyền")
    elif isinstance(record, CardInterestRecord):
        parts.append("lãi suất")
    else:
        parts.append("phí & điều khoản")
    return " · ".join(parts)


def _card_product(
    session: Session, institution_id: int, record: CardRecord, result: DiffResult
) -> int:
    product = session.scalars(
        select(CardProduct).where(
            CardProduct.institution_id == institution_id,
            CardProduct.name == record.card_name,
            CardProduct.network == record.network,
        )
    ).first()
    if product is None:
        terms = record if isinstance(record, CardTermsRecord) else None
        product = CardProduct(
            institution_id=institution_id,
            name=record.card_name,
            network=record.network,
            card_type=terms.card_type if terms else CardType.CREDIT,
            tier=terms.tier if terms else None,
        )
        session.add(product)
        session.flush()
        result.warnings.append(
            RuleWarning(
                "new_card_product",
                "card_product",
                {"card_product_id": product.id},
                f"new card '{record.card_name}' ({record.network.value}) was added; check the name",
            )
        )
    return product.id


def _approved_from_source(
    session: Session, model: type[Versioned], source: Source
) -> list[Versioned]:
    stmt = (
        current_select(model)
        .join(Snapshot, Snapshot.id == model.snapshot_id)
        .where(Snapshot.source_id == source.id)
    )
    return list(session.scalars(stmt))


def _result_from_task(task: ReviewTask) -> DiffResult:
    summary = (task.payload_json or {}).get("summary", {})
    return DiffResult(
        new=summary.get("new", 0),
        changed=summary.get("changed", 0),
        removed=summary.get("removed", 0),
        unchanged=summary.get("unchanged", 0),
        already_pending=summary.get("already_pending", 0),
        review_task_id=task.id,
    )
