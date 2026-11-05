"""Load approved, current values into the scoring formulas.

Only approved versions that are still live (valid_to IS NULL) are used: pending,
rejected and superseded values never reach a ranking (CLAUDE.md principle 4).
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.freshness import StalenessPolicy, institution_freshness
from core.models import (
    CardInterest,
    CardPerk,
    CardProduct,
    CardReward,
    CardTerms,
    Institution,
    SavingsRate,
)
from core.scoring.cards import CardOffer, Reward
from core.scoring.savings import SavingsOffer
from core.versioning import current_select


def _verified(
    session: Session, now: dt.datetime | None, policy: StalenessPolicy | None
) -> set[int]:
    states = institution_freshness(session, now, policy)
    return {i for i, f in states.items() if f.state != "unverified"}


def savings_offers(
    session: Session,
    term_months: int,
    now: dt.datetime | None = None,
    policy: StalenessPolicy | None = None,
) -> list[SavingsOffer]:
    verified = _verified(session, now, policy)
    rows = session.execute(
        current_select(SavingsRate)
        .add_columns(Institution)
        .join(Institution, Institution.id == SavingsRate.institution_id)
        .where(SavingsRate.term_months == term_months, SavingsRate.term_days == 0)
    ).all()
    return [
        SavingsOffer(
            version_id=rate.id,
            institution=inst.short_name,
            institution_name=inst.legal_name_vi,
            product_name=rate.product_name,
            channel=rate.channel,
            term_months=rate.term_months,
            min_amount_vnd=rate.min_amount_vnd,
            interest_payment=rate.interest_payment,
            rate_pct=rate.rate_pct,
            region=rate.region,
            conditions_text=rate.conditions_text,
            is_cd=rate.is_cd,
            deposit_insurance=inst.deposit_insurance,
            verified=inst.id in verified,
        )
        for rate, inst in rows
    ]


def card_offers(
    session: Session,
    now: dt.datetime | None = None,
    policy: StalenessPolicy | None = None,
) -> list[CardOffer]:
    """Every active card with at least one approved value (terms, reward or perk)."""
    verified = _verified(session, now, policy)
    terms = {t.card_product_id: t for t in session.scalars(current_select(CardTerms))}
    perks = {p.card_product_id: p for p in session.scalars(current_select(CardPerk))}
    # The product page's yearly rate wins over the fee schedule's (docs/methodology.md §2).
    interest = {i.card_product_id: i for i in session.scalars(current_select(CardInterest))}
    rewards: dict[int, list[CardReward]] = {}
    for r in session.scalars(current_select(CardReward).order_by(CardReward.id)):
        rewards.setdefault(r.card_product_id, []).append(r)
    ids = set(terms) | set(perks) | set(rewards) | set(interest)
    if not ids:
        return []
    products = session.execute(
        select(CardProduct, Institution)
        .join(Institution, Institution.id == CardProduct.institution_id)
        .where(CardProduct.id.in_(ids), CardProduct.active.is_(True))
        .order_by(CardProduct.id)
    ).all()
    offers = []
    for product, inst in products:
        t, p, i = terms.get(product.id), perks.get(product.id), interest.get(product.id)
        offers.append(
            CardOffer(
                card_product_id=product.id,
                institution=inst.short_name,
                name=product.name,
                network=product.network.value,
                annual_fee_vnd=t.annual_fee_primary_vnd if t else None,
                fee_waiver_spend_vnd=t.fee_waiver_spend_vnd if t else None,
                fx_fee_pct=t.fx_fee_pct if t else None,
                interest_rate_pct=(
                    i.interest_rate_pct if i else (t.interest_rate_pct if t else None)
                ),
                min_monthly_income_vnd=t.min_monthly_income_vnd if t else None,
                rewards=tuple(
                    Reward(
                        r.category, r.reward_type, r.rate_pct, r.monthly_cap_vnd, r.conditions_text
                    )
                    for r in rewards.get(product.id, [])
                ),
                lounge_visits_per_year=p.lounge_visits_per_year if p else None,
                lounge_unlimited=p.lounge_unlimited if p else False,
                travel_insurance=p.travel_insurance if p else False,
                other_perks_text=p.other_perks_text if p else None,
                verified=inst.id in verified,
            )
        )
    return offers
