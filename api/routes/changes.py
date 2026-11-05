"""GET /changes?since= : approved changes, newest first (the "rate moves" page)."""

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.common import provenance, ref, send, snapshots
from api.deps import DB, Cache
from api.schemas import ChangeOut, ChangesOut, FieldChange
from core.enums import VersionStatus
from core.models import (
    VERSIONED_MODELS,
    CardProduct,
    ChangeEvent,
    Institution,
    SavingsRate,
    Versioned,
)
from core.versioning import key_columns

router = APIRouter(tags=["changes"])


def _label(row: Versioned, card: CardProduct | None) -> str:
    if isinstance(row, SavingsRate):
        term = f"{row.term_days} ngày" if row.term_days else f"{row.term_months} tháng"
        if not row.term_days and not row.term_months:
            term = "không kỳ hạn"
        parts = [row.product_name, row.channel.value, term]
        if row.min_amount_vnd:
            parts.append(f"từ {row.min_amount_vnd:,} đ".replace(",", "."))
        if row.region:
            parts.append(row.region)
        return " · ".join(parts)
    name = card.name if card else "?"
    category = getattr(row, "category", None)
    return f"{name} · {category.value}" if category is not None else name


def _institution_id(session: Session, row: Versioned, cards: dict[int, CardProduct]) -> int:
    if isinstance(row, SavingsRate):
        return row.institution_id
    return cards[row.card_product_id].institution_id  # type: ignore[attr-defined]


def _scaled(model: type[Versioned], field: str, value: Any) -> Any:
    """Decimals as the column stores them ("6.20" -> "6.200"), so old and new match."""
    column = model.__table__.columns.get(field)
    scale = getattr(column.type, "scale", None) if column is not None else None
    if scale is None or value is None:
        return value
    try:
        return str(Decimal(str(value)).quantize(Decimal(1).scaleb(-scale)))
    except InvalidOperation:
        return value


def _replaced_one(session: Session, row: Versioned) -> bool:
    """Approval closes the live version at the same instant the new one opens."""
    model = type(row)
    key = {c: getattr(row, c) for c in key_columns(model)}
    return (
        session.scalar(
            select(model.id)
            .where(
                *(getattr(model, c) == v for c, v in key.items()),
                model.status == VersionStatus.APPROVED,
                model.valid_to == row.valid_from,
                model.id != row.id,
            )
            .limit(1)
        )
        is not None
    )


@router.get("/changes", response_model=ChangesOut, summary="Approved changes since a date")
def changes(
    request: Request,
    session: DB,
    cache: Cache,
    since: Annotated[dt.date | None, Query(description="YYYY-MM-DD; default: 30 days ago")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> Response:
    """Values a reviewer approved on or after `since` (UTC), with what changed:
    old -> new per field, compared with the value live when it was proposed.
    `kind` is "new" for a series seen for the first time."""
    start = since or (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=30))

    def build() -> ChangesOut:
        cutoff = dt.datetime.combine(start, dt.time(), tzinfo=dt.UTC)
        rows: list[Versioned] = []
        for model in VERSIONED_MODELS:
            rows += session.scalars(
                select(model).where(
                    model.status == VersionStatus.APPROVED, model.valid_from >= cutoff
                )
            )
        rows.sort(key=lambda r: (r.valid_from, r.id), reverse=True)
        rows = rows[:limit]
        events: dict[tuple[str, int], list[ChangeEvent]] = {}
        for table in {r.__tablename__ for r in rows}:
            ids = [r.id for r in rows if r.__tablename__ == table]
            for e in session.scalars(
                select(ChangeEvent)
                .where(ChangeEvent.entity == table, ChangeEvent.entity_id.in_(ids))
                .order_by(ChangeEvent.id)
            ):
                events.setdefault((table, e.entity_id), []).append(e)
        card_ids = {getattr(r, "card_product_id", None) for r in rows} - {None}
        cards = {
            c.id: c
            for c in session.scalars(select(CardProduct).where(CardProduct.id.in_(card_ids)))
        }
        insts = {i.id: i for i in session.scalars(select(Institution))}
        snaps = snapshots(session, rows)
        out = []
        for r in rows:
            found = events.get((r.__tablename__, r.id), [])
            kind = "changed" if _replaced_one(session, r) else "new"
            card = cards.get(getattr(r, "card_product_id", -1))
            assert r.valid_from is not None
            out.append(
                ChangeOut(
                    table=r.__tablename__,
                    version_id=r.id,
                    kind=kind,
                    institution=ref(insts[_institution_id(session, r, cards)]),
                    label=_label(r, card),
                    approved_at=r.valid_from,
                    changes=[
                        FieldChange(
                            field=e.field,
                            old=_scaled(type(r), e.field, e.old_value),
                            new=_scaled(type(r), e.field, e.new_value),
                        )
                        for e in found
                    ],
                    provenance=provenance(r, snaps.get(r.snapshot_id)),
                )
            )
        return ChangesOut(since=start, changes=out)

    return send(request, cache, build)
