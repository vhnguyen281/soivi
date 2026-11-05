"""GET /savings/rates, /savings/rank, /savings/history"""

from dataclasses import asdict
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.common import provenance, ref, send, snapshots, verification
from api.deps import DB, Cache
from api.schemas import (
    HistoryOut,
    HistoryPoint,
    HistorySeries,
    SavingsRankItem,
    SavingsRankOut,
    SavingsRateOut,
    SavingsRatesOut,
)
from core.enums import Channel, VersionStatus
from core.models import Institution, SavingsRate
from core.scoring.data import savings_offers
from core.scoring.savings import (
    CHANNEL_PREFERENCES,
    SavingsQuery,
    excluded_by_amount,
    rank_savings,
)
from core.versioning import current_select

router = APIRouter(prefix="/savings", tags=["savings"])

Amount = Annotated[int, Query(gt=0, le=1_000_000_000_000, description="VND")]
Term = Annotated[int, Query(ge=1, le=600, description="Term in months")]


def _rate_out(
    session: Session, rates: list[SavingsRate], states: dict[int, str]
) -> list[SavingsRateOut]:
    snaps = snapshots(session, rates)
    insts = {
        i.id: i
        for i in session.scalars(
            select(Institution).where(Institution.id.in_({r.institution_id for r in rates}))
        )
    }
    return [
        SavingsRateOut(
            id=r.id,
            institution=ref(insts[r.institution_id]),
            product_name=r.product_name,
            channel=r.channel.value,
            region=r.region,
            term_months=r.term_months,
            term_days=r.term_days,
            min_amount_vnd=r.min_amount_vnd,
            interest_payment=r.interest_payment.value,
            rate_pct=r.rate_pct,
            conditions_text=r.conditions_text,
            is_cd=r.is_cd,
            unverified=states.get(r.institution_id) == "unverified",
            provenance=provenance(r, snaps.get(r.snapshot_id)),
        )
        for r in rates
    ]


@router.get("/rates", response_model=SavingsRatesOut, summary="Current approved rates")
def rates(
    request: Request,
    session: DB,
    cache: Cache,
    term: Annotated[int | None, Query(ge=0, le=600, description="Months (0 = demand)")] = None,
    channel: Annotated[Channel | None, Query()] = None,
    amount: Annotated[int | None, Query(gt=0, description="Only rates this amount gets")] = None,
    institution: Annotated[str | None, Query(description="short_name, e.g. VIETCOMBANK")] = None,
) -> Response:
    """Every live, human-approved rate. Pending values never appear here."""

    def build() -> SavingsRatesOut:
        stmt = current_select(SavingsRate).join(
            Institution, Institution.id == SavingsRate.institution_id
        )
        if term is not None:
            stmt = stmt.where(SavingsRate.term_months == term)
            if term:
                stmt = stmt.where(SavingsRate.term_days == 0)
        if channel is not None:
            stmt = stmt.where(SavingsRate.channel == channel)
        if amount is not None:
            stmt = stmt.where(SavingsRate.min_amount_vnd <= amount)
        if institution:
            stmt = stmt.where(Institution.short_name == institution.upper())
        stmt = stmt.order_by(
            Institution.short_name,
            SavingsRate.term_months,
            SavingsRate.term_days,
            SavingsRate.product_name,
            SavingsRate.channel,
            SavingsRate.min_amount_vnd,
            SavingsRate.id,
        )
        found = list(session.scalars(stmt))
        return SavingsRatesOut(rates=_rate_out(session, found, verification(session)))

    return send(request, cache, build)


@router.get("/rank", response_model=SavingsRankOut, summary="Rank by VND earned at maturity")
def rank(
    request: Request,
    session: DB,
    cache: Cache,
    amount: Amount,
    term: Term,
    channel: Annotated[str, Query(description=f"One of {sorted(CHANNEL_PREFERENCES)}")] = "any",
    region: Annotated[str | None, Query(description="e.g. north; default: all")] = None,
) -> Response:
    """Formula: docs/methodology.md §1. Early interest is valued at maturity."""
    query = SavingsQuery(amount, term, channel, region)  # raises ScoringError -> 422

    def build() -> SavingsRankOut:
        offers = savings_offers(session, term)
        results = rank_savings(offers, query)
        by_id = {
            r.id: r
            for r in session.scalars(
                select(SavingsRate).where(SavingsRate.id.in_([x.offer.version_id for x in results]))
            )
        }
        out = {
            o.id: o
            for o in _rate_out(
                session, [by_id[x.offer.version_id] for x in results], verification(session)
            )
        }
        return SavingsRankOut(
            query=asdict(query),
            results=[
                SavingsRankItem(
                    rank=x.rank,
                    rate=out[x.offer.version_id],
                    equivalent_interest_vnd=x.equivalent_interest_vnd,
                    cash_interest_vnd=x.cash_interest_vnd,
                    equivalent_rate_pct=x.equivalent_rate_pct,
                    maturity_value_vnd=amount + x.equivalent_interest_vnd,
                    flags=x.flags,
                )
                for x in results
            ],
            excluded_min_amount=excluded_by_amount(offers, query),
        )

    return send(request, cache, build)


@router.get("/history", response_model=HistoryOut, summary="A bank's rates over time")
def history(
    request: Request,
    session: DB,
    cache: Cache,
    institution: Annotated[str, Query(description="short_name, e.g. VIETCOMBANK")],
    term: Annotated[int | None, Query(ge=0, le=600, description="Months")] = None,
) -> Response:
    """Every value that was ever approved, oldest first, one series per product /
    channel / region / tier / payment schedule. A point is live while valid_to is
    null; rejected and pending values are never shown."""
    inst = session.scalars(
        select(Institution).where(Institution.short_name == institution.upper())
    ).first()
    if inst is None:
        raise HTTPException(404, f"no institution {institution!r}; see /institutions")

    def build() -> HistoryOut:
        stmt = select(SavingsRate).where(
            SavingsRate.institution_id == inst.id,
            SavingsRate.status == VersionStatus.APPROVED,
        )
        if term is not None:
            stmt = stmt.where(SavingsRate.term_months == term)
        found = list(session.scalars(stmt.order_by(SavingsRate.valid_from, SavingsRate.id)))
        snaps = snapshots(session, found)
        series: dict[tuple[object, ...], HistorySeries] = {}
        for r in found:
            key = (
                r.product_name,
                r.channel.value,
                r.region,
                r.term_months,
                r.term_days,
                r.min_amount_vnd,
                r.interest_payment.value,
            )
            if key not in series:
                series[key] = HistorySeries(
                    product_name=r.product_name,
                    channel=r.channel.value,
                    region=r.region,
                    term_months=r.term_months,
                    term_days=r.term_days,
                    min_amount_vnd=r.min_amount_vnd,
                    interest_payment=r.interest_payment.value,
                    points=[],
                )
            series[key].points.append(
                HistoryPoint(
                    version_id=r.id,
                    rate_pct=Decimal(r.rate_pct),
                    valid_from=r.valid_from,
                    valid_to=r.valid_to,
                    provenance=provenance(r, snaps.get(r.snapshot_id)),
                )
            )
        ordered = sorted(
            series.values(),
            key=lambda s: (s.term_months, s.term_days, s.product_name, s.channel, s.min_amount_vnd),
        )
        return HistoryOut(institution=ref(inst), series=ordered)

    return send(request, cache, build)
