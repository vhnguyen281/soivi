"""GET /cards, GET /cards/{id}, POST /cards/rank, GET /cards/personas"""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.common import provenance, ref, send, snapshots, verification
from api.deps import DB, Cache
from api.schemas import (
    CardDetail,
    CardImageRef,
    CardNotRanked,
    CardOut,
    CardRankItem,
    CardRankOut,
    CardsOut,
    CardSummary,
    PersonaOut,
    PersonasOut,
    Valued,
)
from core.card_images import approved_images
from core.enums import RewardCategory
from core.models import (
    CardInterest,
    CardPerk,
    CardProduct,
    CardReward,
    CardTerms,
    Institution,
    Versioned,
)
from core.scoring.cards import (
    PERSONAS,
    SPEND_CATEGORIES,
    CardScore,
    SpendingProfile,
    rank_cards,
)
from core.scoring.data import card_offers
from core.scoring.savings import ScoringError
from core.versioning import current_select, key_columns, value_columns

router = APIRouter(prefix="/cards", tags=["cards"])


class ProfileIn(BaseModel):
    """A spending profile: amounts in VND per month unless stated."""

    model_config = ConfigDict(extra="forbid")

    monthly_spend_vnd: dict[str, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict,
        description=f"Per category: {[c.value for c in SPEND_CATEGORIES]}",
        examples=[{"grocery": 4_000_000, "dining": 2_000_000}],
    )
    foreign_monthly_vnd: Annotated[int, Field(ge=0)] = 0
    revolving_balance_vnd: Annotated[int, Field(ge=0, description="Carried all year")] = 0
    lounge_visits_wanted: Annotated[int, Field(ge=0, description="Per year")] = 0
    lounge_visit_value_vnd: Annotated[int, Field(ge=0)] = 0
    travel_insurance_value_vnd: Annotated[int, Field(ge=0, description="Per year")] = 0
    monthly_income_vnd: Annotated[int, Field(ge=0)] | None = None

    def to_profile(self) -> SpendingProfile:
        allowed = {c.value for c in SPEND_CATEGORIES}
        unknown = sorted(set(self.monthly_spend_vnd) - allowed)
        if unknown:
            raise ScoringError(f"unknown spend categories {unknown}; use {sorted(allowed)}")
        data = self.model_dump()
        data["monthly_spend_vnd"] = {
            RewardCategory(k): v for k, v in self.monthly_spend_vnd.items()
        }
        return SpendingProfile(**data)


class RankIn(BaseModel):
    """Either a preset (`persona`) or your own `profile`."""

    model_config = ConfigDict(extra="forbid")

    persona: str | None = Field(default=None, description=f"One of {list(PERSONAS)}")
    profile: ProfileIn | None = None

    @model_validator(mode="after")
    def _one(self) -> "RankIn":
        if (self.persona is None) == (self.profile is None):
            raise ValueError("give exactly one of persona or profile")
        return self


# --------------------------------------------------------------------------- loading


class _Cards:
    """Current approved rows for some card products, loaded once per request."""

    def __init__(self, session: Session, ids: set[int] | None = None) -> None:
        def current(model: type[Versioned]) -> list[Any]:
            stmt = current_select(model)
            if ids is not None:
                stmt = stmt.where(model.card_product_id.in_(ids))  # type: ignore[attr-defined]
            return list(session.scalars(stmt.order_by(model.id)))

        self.terms = {t.card_product_id: t for t in current(CardTerms)}
        self.perks = {p.card_product_id: p for p in current(CardPerk)}
        self.interest = {i.card_product_id: i for i in current(CardInterest)}
        self.rewards: dict[int, list[CardReward]] = {}
        for r in current(CardReward):
            self.rewards.setdefault(r.card_product_id, []).append(r)
        self.snaps = snapshots(
            session,
            [
                *self.terms.values(),
                *self.perks.values(),
                *self.interest.values(),
                *(r for v in self.rewards.values() for r in v),
            ],
        )
        known = set(self.terms) | set(self.perks) | set(self.rewards) | set(self.interest)
        rows = session.execute(
            select(CardProduct, Institution)
            .join(Institution, Institution.id == CardProduct.institution_id)
            .where(CardProduct.id.in_(known), CardProduct.active.is_(True))
            .order_by(Institution.short_name, CardProduct.name)
        ).all()
        self.products = {p.id: (p, i) for p, i in rows}
        self.states = verification(session)
        self.images = approved_images(session)

    def valued(self, version: Versioned | None) -> Valued | None:
        if version is None:
            return None
        model = type(version)
        names = [c for c in key_columns(model) if c != "card_product_id"]
        values = {c: getattr(version, c) for c in (*names, *value_columns(model))}
        return Valued(
            version_id=version.id,
            values=values,
            provenance=provenance(version, self.snaps.get(version.snapshot_id)),
        )

    def _image(self, product_id: int) -> CardImageRef | None:
        img = self.images.get(product_id)
        if img is None:
            return None
        return CardImageRef(
            url=f"/cards/{product_id}/image",
            source_url=img.page_url,
            sha256=img.sha256,
            width=img.width,
            height=img.height,
        )

    def summary(self, product_id: int) -> CardSummary:
        product, inst = self.products[product_id]
        return CardSummary(
            id=product.id,
            institution=ref(inst),
            name=product.name,
            network=product.network.value,
            card_type=product.card_type.value,
            tier=product.tier,
            unverified=self.states.get(inst.id) == "unverified",
            terms=self.valued(self.terms.get(product.id)),
            rewards_count=len(self.rewards.get(product.id, [])),
            image=self._image(product.id),
        )

    def used(self, product_id: int) -> list[Versioned]:
        rows: list[Versioned] = [*self.rewards.get(product_id, [])]
        for row in (
            self.interest.get(product_id),
            self.perks.get(product_id),
            self.terms.get(product_id),
        ):
            if row is not None:
                rows.insert(0, row)
        return rows


# --------------------------------------------------------------------------- routes


@router.get("", response_model=CardsOut, summary="Cards with approved values")
def cards(request: Request, session: DB, cache: Cache) -> Response:
    def build() -> CardsOut:
        loaded = _Cards(session)
        return CardsOut(cards=[loaded.summary(i) for i in loaded.products])

    return send(request, cache, build)


@router.get("/personas", response_model=PersonasOut, summary="Preset spending profiles")
def personas(request: Request, cache: Cache) -> Response:
    def build() -> PersonasOut:
        return PersonasOut(
            personas=[
                PersonaOut(
                    key=p.key, name_vi=p.name_vi, name_en=p.name_en, profile=asdict(p.profile)
                )
                for p in PERSONAS.values()
            ]
        )

    return send(request, cache, build)


@router.get("/{card_id}/image", summary="The card's approved picture (from the bank's card page)")
def card_image(card_id: int, request: Request, session: DB) -> Response:
    from pipeline.fetch.storage import MinioStore

    image = approved_images(session).get(card_id)
    if image is None:
        raise HTTPException(404, f"no approved picture for card {card_id}")
    etag = f'"{image.sha256[:32]}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    store = getattr(request.app.state, "image_store", None)
    if store is None:
        store = request.app.state.image_store = MinioStore()
    return Response(store.get(image.storage_key), media_type=image.content_type, headers=headers)


@router.get("/{card_id}", response_model=CardOut, summary="One card: terms, rewards, perks")
def card(request: Request, card_id: int, session: DB, cache: Cache) -> Response:
    loaded = _Cards(session, {card_id})
    if card_id not in loaded.products:
        raise HTTPException(404, f"no card {card_id} with approved values")

    def build() -> CardOut:
        summary = loaded.summary(card_id)
        return CardOut(
            card=CardDetail(
                **summary.model_dump(),
                rewards=[v for r in loaded.rewards.get(card_id, []) if (v := loaded.valued(r))],
                perks=loaded.valued(loaded.perks.get(card_id)),
                interest=loaded.valued(loaded.interest.get(card_id)),
            )
        )

    return send(request, cache, build)


@router.post("/rank", response_model=CardRankOut, summary="Rank cards for a spending profile")
async def rank(request: Request, body: RankIn, session: DB, cache: Cache) -> Response:
    """Annual net value V (docs/methodology.md §2). Cards missing a value the
    profile needs are listed under not_ranked with the reason."""
    if body.persona is not None:
        if body.persona not in PERSONAS:
            raise HTTPException(404, f"unknown persona {body.persona!r}; see /cards/personas")
        profile = PERSONAS[body.persona].profile
    else:
        assert body.profile is not None
        profile = body.profile.to_profile()

    def build() -> CardRankOut:
        loaded = _Cards(session)
        ranked, skipped = rank_cards(card_offers(session), profile)

        def item(score: CardScore) -> CardRankItem:
            pid = score.offer.card_product_id
            return CardRankItem(
                rank=score.rank,
                card=loaded.summary(pid),
                annual_value_vnd=score.annual_value_vnd,
                breakdown={
                    "rewards_vnd": score.rewards_vnd,
                    "perks_vnd": score.perks_vnd,
                    "annual_fee_vnd": score.annual_fee_vnd,
                    "fee_waived": score.fee_waived,
                    "fx_cost_vnd": score.fx_cost_vnd,
                    "interest_cost_vnd": score.interest_cost_vnd,
                },
                flags=score.flags,
                provenance=[
                    provenance(v, loaded.snaps.get(v.snapshot_id)) for v in loaded.used(pid)
                ],
            )

        return CardRankOut(
            persona=body.persona,
            profile=asdict(profile),
            results=[item(s) for s in ranked],
            not_ranked=[
                CardNotRanked(card=loaded.summary(n.offer.card_product_id), reasons=list(n.reasons))
                for n in skipped
            ],
        )

    return send(request, cache, build, key_extra=await request.body())
