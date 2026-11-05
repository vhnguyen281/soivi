"""GET /institutions"""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from api.common import send, verification
from api.deps import DB, Cache
from api.schemas import InstitutionOut, InstitutionsOut, Provenance
from core.models import Institution, Source

router = APIRouter(tags=["institutions"])


@router.get("/institutions", response_model=InstitutionsOut, summary="Banks and finance companies")
def institutions(request: Request, session: DB, cache: Cache) -> Response:
    """Every institution we list, with its verification state.

    Institution facts come from the curated seed list (sources in
    data/seeds/README.md); `checked_at` is the last successful read of any of its
    monitored sources."""

    def build() -> InstitutionsOut:
        states = verification(session)
        last = dict(
            session.execute(
                select(Source.institution_id, func.max(Source.last_success_at)).group_by(
                    Source.institution_id
                )
            ).all()
        )
        rows = session.scalars(
            select(Institution).where(Institution.active.is_(True)).order_by(Institution.short_name)
        )
        return InstitutionsOut(
            institutions=[
                InstitutionOut(
                    id=i.id,
                    short_name=i.short_name,
                    legal_name_vi=i.legal_name_vi,
                    type=i.type.value,
                    website=i.website,
                    deposit_insurance=i.deposit_insurance,
                    verification=states.get(i.id, "no_sources"),
                    unverified=states.get(i.id) == "unverified",
                    provenance=Provenance(
                        source_url=i.website, checked_at=last.get(i.id), effective_from=None
                    ),
                )
                for i in rows
            ]
        )

    return send(request, cache, build)
