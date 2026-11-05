"""Credit cards: annual net value for a spending profile.

    V = Σ_c min(r_c * S_c, cap_c) + P - F * (1 - w) - f_FX * S_foreign - i * B

with every term counted over one year (docs/methodology.md §2):

    rewards   each cashback reward earns r * (the monthly spend it applies to),
              capped at its monthly cap, * 12. A category with no reward of its
              own falls back to the card's "all" reward, if it has one.
    P         perks the user values: lounge visits (up to what the card gives)
              * the user's value per visit, plus travel insurance if included.
    F, w      annual fee; w = 1 when 12 * total monthly spend reaches the
              card's waiver spend, else 0.
    f_FX      foreign-currency fee * 12 * monthly foreign spend.
    i * B     yearly interest rate * the balance carried all year.

Nothing is guessed: if a term the profile needs is unknown for a card (annual
fee always; rewards when there is any spend; FX fee when there is foreign spend;
interest rate when a balance is carried), the card is listed as not ranked, with
the reason. Points and
miles have no agreed VND value yet, so they count 0 and are flagged.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from core.enums import RewardCategory, RewardType
from core.scoring.savings import HUNDRED, TWELVE, ScoringError, vnd

SPEND_CATEGORIES = tuple(c for c in RewardCategory if c is not RewardCategory.ALL)


@dataclass(frozen=True)
class Reward:
    category: RewardCategory
    reward_type: RewardType
    rate_pct: Decimal | None
    monthly_cap_vnd: int | None = None
    conditions_text: str | None = None


@dataclass(frozen=True)
class CardOffer:
    """One card's approved current terms, rewards and perks."""

    card_product_id: int
    institution: str
    name: str
    network: str
    annual_fee_vnd: int | None
    fee_waiver_spend_vnd: int | None = None
    fx_fee_pct: Decimal | None = None
    interest_rate_pct: Decimal | None = None
    min_monthly_income_vnd: int | None = None
    rewards: tuple[Reward, ...] = ()
    lounge_visits_per_year: int | None = None
    lounge_unlimited: bool = False
    travel_insurance: bool = False
    other_perks_text: str | None = None
    verified: bool = True


@dataclass(frozen=True)
class SpendingProfile:
    """Monthly spend per category (VND), plus what drives fees and perks."""

    monthly_spend_vnd: dict[RewardCategory, int] = field(default_factory=dict)
    foreign_monthly_vnd: int = 0  # paid in foreign currency; earns 'overseas' rewards
    revolving_balance_vnd: int = 0  # carried all year (not paid off)
    lounge_visits_wanted: int = 0  # per year
    lounge_visit_value_vnd: int = 0
    travel_insurance_value_vnd: int = 0  # per year, 0 = not wanted
    monthly_income_vnd: int | None = None  # filters cards by their minimum income

    def __post_init__(self) -> None:
        if RewardCategory.ALL in self.monthly_spend_vnd:
            raise ScoringError("spend goes in a category; 'all' is a reward, not a category")
        amounts = [
            *self.monthly_spend_vnd.values(),
            self.foreign_monthly_vnd,
            self.revolving_balance_vnd,
            self.lounge_visits_wanted,
            self.lounge_visit_value_vnd,
            self.travel_insurance_value_vnd,
        ]
        if any(a < 0 for a in amounts) or (self.monthly_income_vnd or 0) < 0:
            raise ScoringError("amounts can't be negative")

    @property
    def total_monthly_vnd(self) -> int:
        return sum(self.monthly_spend_vnd.values()) + self.foreign_monthly_vnd


@dataclass(frozen=True)
class CardScore:
    offer: CardOffer
    annual_value_vnd: int  # V
    rewards_vnd: int
    perks_vnd: int
    annual_fee_vnd: int  # F * (1 - w), as a cost
    fee_waived: bool
    fx_cost_vnd: int
    interest_cost_vnd: int
    flags: dict[str, bool] = field(default_factory=dict)
    rank: int = 0


@dataclass(frozen=True)
class NotRanked:
    offer: CardOffer
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Persona:
    key: str
    name_vi: str
    name_en: str
    profile: SpendingProfile


def _spend_by_reward(offer: CardOffer, profile: SpendingProfile) -> dict[int, Decimal]:
    """Monthly spend assigned to each cashback reward (index into offer.rewards)."""
    cashback = {
        r.category: i
        for i, r in enumerate(offer.rewards)
        if r.reward_type is RewardType.CASHBACK and r.rate_pct is not None
    }
    spend = dict(profile.monthly_spend_vnd)
    spend[RewardCategory.OVERSEAS] = spend.get(RewardCategory.OVERSEAS, 0) + (
        profile.foreign_monthly_vnd
    )
    assigned: dict[int, Decimal] = {}
    for category, amount in spend.items():
        index = cashback.get(category, cashback.get(RewardCategory.ALL))
        if index is not None and amount:
            assigned[index] = assigned.get(index, Decimal(0)) + Decimal(amount)
    return assigned


def rewards_value(offer: CardOffer, profile: SpendingProfile) -> Decimal:
    """Σ_c min(r_c * S_c, cap_c), per month, * 12."""
    monthly = Decimal(0)
    for index, spend in _spend_by_reward(offer, profile).items():
        reward = offer.rewards[index]
        assert reward.rate_pct is not None
        earned = reward.rate_pct / HUNDRED * spend
        if reward.monthly_cap_vnd is not None:
            earned = min(earned, Decimal(reward.monthly_cap_vnd))
        monthly += earned
    return monthly * TWELVE


def perks_value(offer: CardOffer, profile: SpendingProfile) -> Decimal:
    visits = profile.lounge_visits_wanted
    if not offer.lounge_unlimited:
        visits = min(visits, offer.lounge_visits_per_year or 0)
    insurance = profile.travel_insurance_value_vnd if offer.travel_insurance else 0
    return Decimal(visits * profile.lounge_visit_value_vnd + insurance)


def _missing(offer: CardOffer, profile: SpendingProfile) -> list[str]:
    reasons = []
    if offer.annual_fee_vnd is None:
        reasons.append("annual_fee_unknown")
    if profile.total_monthly_vnd and not offer.rewards:
        # No reward read yet is not the same as "earns nothing": don't rank it as zero.
        reasons.append("rewards_unknown")
    if profile.foreign_monthly_vnd and offer.fx_fee_pct is None:
        reasons.append("fx_fee_unknown")
    if profile.revolving_balance_vnd and offer.interest_rate_pct is None:
        reasons.append("interest_rate_unknown")
    if (
        profile.monthly_income_vnd is not None
        and offer.min_monthly_income_vnd is not None
        and offer.min_monthly_income_vnd > profile.monthly_income_vnd
    ):
        reasons.append("income_below_minimum")
    return reasons


def score_card(offer: CardOffer, profile: SpendingProfile) -> CardScore | NotRanked:
    reasons = _missing(offer, profile)
    if reasons:
        return NotRanked(offer, tuple(reasons))
    assert offer.annual_fee_vnd is not None
    rewards = rewards_value(offer, profile)
    perks = perks_value(offer, profile)
    yearly_spend = TWELVE * profile.total_monthly_vnd
    waived = offer.fee_waiver_spend_vnd is not None and yearly_spend >= offer.fee_waiver_spend_vnd
    fee = Decimal(0) if waived else Decimal(offer.annual_fee_vnd)
    fx = (offer.fx_fee_pct or Decimal(0)) / HUNDRED * TWELVE * profile.foreign_monthly_vnd
    interest = (offer.interest_rate_pct or Decimal(0)) / HUNDRED * profile.revolving_balance_vnd
    value = rewards + perks - fee - fx - interest
    return CardScore(
        offer=offer,
        annual_value_vnd=vnd(value),
        rewards_vnd=vnd(rewards),
        perks_vnd=vnd(perks),
        annual_fee_vnd=vnd(fee),
        fee_waived=waived,
        fx_cost_vnd=vnd(fx),
        interest_cost_vnd=vnd(interest),
        flags={
            "points_not_valued": any(
                r.reward_type is not RewardType.CASHBACK for r in offer.rewards
            ),
            "income_requirement_unknown": profile.monthly_income_vnd is not None
            and offer.min_monthly_income_vnd is None,
            "unverified": not offer.verified,
        },
    )


def rank_cards(
    offers: Sequence[CardOffer], profile: SpendingProfile
) -> tuple[list[CardScore], list[NotRanked]]:
    scored: list[CardScore] = []
    skipped: list[NotRanked] = []
    for offer in offers:
        result = score_card(offer, profile)
        if isinstance(result, CardScore):
            scored.append(result)
        else:
            skipped.append(result)
    scored.sort(key=lambda s: (-s.annual_value_vnd, s.offer.institution, s.offer.name))
    ranked = [replace(s, rank=i) for i, s in enumerate(scored, 1)]
    skipped.sort(key=lambda n: (n.offer.institution, n.offer.name))
    return ranked, skipped


# --------------------------------------------------------------------------- personas

C = RewardCategory
PERSONAS: dict[str, Persona] = {
    p.key: p
    for p in (
        Persona(
            "everyday",
            "Chi tiêu hằng ngày, trả hết dư nợ mỗi tháng",
            "Everyday spender who pays in full",
            SpendingProfile(
                monthly_spend_vnd={
                    C.GROCERY: 4_000_000,
                    C.DINING: 2_000_000,
                    C.ONLINE: 2_000_000,
                    C.FUEL: 1_000_000,
                    C.OTHER: 3_000_000,
                },
            ),
        ),
        Persona(
            "traveller",
            "Hay đi du lịch, công tác nước ngoài",
            "Frequent traveller",
            SpendingProfile(
                monthly_spend_vnd={
                    C.TRAVEL: 5_000_000,
                    C.DINING: 4_000_000,
                    C.ONLINE: 2_000_000,
                    C.OTHER: 3_000_000,
                },
                foreign_monthly_vnd=8_000_000,
                lounge_visits_wanted=6,
                lounge_visit_value_vnd=500_000,
                travel_insurance_value_vnd=1_000_000,
            ),
        ),
        Persona(
            "first_card",
            "Thẻ đầu tiên, thu nhập khiêm tốn",
            "First card on a modest income",
            SpendingProfile(
                monthly_spend_vnd={
                    C.GROCERY: 2_000_000,
                    C.ONLINE: 1_000_000,
                    C.FUEL: 500_000,
                    C.OTHER: 1_500_000,
                },
                monthly_income_vnd=10_000_000,
            ),
        ),
        Persona(
            "revolver",
            "Thường không trả hết dư nợ",
            "Carries a balance",
            SpendingProfile(
                monthly_spend_vnd={
                    C.GROCERY: 3_000_000,
                    C.DINING: 1_500_000,
                    C.ONLINE: 1_500_000,
                    C.OTHER: 2_000_000,
                },
                revolving_balance_vnd=20_000_000,
            ),
        ),
    )
}
