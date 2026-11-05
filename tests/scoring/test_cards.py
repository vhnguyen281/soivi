"""Card formula V = Σ min(r·S, cap) + P - F(1 - w) - f_FX·S_foreign - i·B, by hand.

Worked example (card X, profile Q), all per year:

    rewards  dining 10% of 6.000.000 = 600.000, capped at 500.000/month
             "all" 0.5% of (grocery 4M + other 2M + online 1M + foreign 2M) = 45.000
             (500.000 + 45.000) x 12                                  = 6.540.000
    perks    min(6 wanted, 4 given) x 400.000 + insurance 500.000     = 2.100.000
    fee      12 x 15.000.000 = 180M < 200M waiver: paid               = 1.000.000
    FX       2.5% x 12 x 2.000.000                                    =   600.000
    interest 30% x 10.000.000                                         = 3.000.000
    V        6.540.000 + 2.100.000 - 1.000.000 - 600.000 - 3.000.000  = 4.040.000
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from core.enums import RewardCategory as C
from core.enums import RewardType as T
from core.scoring.cards import (
    PERSONAS,
    CardOffer,
    CardScore,
    NotRanked,
    Reward,
    SpendingProfile,
    perks_value,
    rank_cards,
    rewards_value,
    score_card,
)
from core.scoring.savings import ScoringError

X = CardOffer(
    card_product_id=1,
    institution="VIDU",
    name="Ví Dụ Visa Platinum",
    network="visa",
    annual_fee_vnd=1_000_000,
    fee_waiver_spend_vnd=200_000_000,
    fx_fee_pct=Decimal("2.5"),
    interest_rate_pct=Decimal("30"),
    rewards=(
        Reward(C.DINING, T.CASHBACK, Decimal("10"), 500_000),
        Reward(C.ALL, T.CASHBACK, Decimal("0.5")),
        Reward(C.ONLINE, T.POINTS, None),
    ),
    lounge_visits_per_year=4,
    travel_insurance=True,
)
Q = SpendingProfile(
    monthly_spend_vnd={
        C.DINING: 6_000_000,
        C.GROCERY: 4_000_000,
        C.OTHER: 2_000_000,
        C.ONLINE: 1_000_000,
    },
    foreign_monthly_vnd=2_000_000,
    revolving_balance_vnd=10_000_000,
    lounge_visits_wanted=6,
    lounge_visit_value_vnd=400_000,
    travel_insurance_value_vnd=500_000,
)


def scored(offer: CardOffer, profile: SpendingProfile) -> CardScore:
    result = score_card(offer, profile)
    assert isinstance(result, CardScore), result
    return result


def test_worked_example() -> None:
    s = scored(X, Q)
    assert (s.rewards_vnd, s.perks_vnd, s.annual_fee_vnd) == (6_540_000, 2_100_000, 1_000_000)
    assert (s.fx_cost_vnd, s.interest_cost_vnd) == (600_000, 3_000_000)
    assert s.annual_value_vnd == 4_040_000 and not s.fee_waived
    assert s.flags["points_not_valued"]  # the online points reward counts 0


def test_cap_is_monthly() -> None:
    card = replace(X, rewards=(Reward(C.DINING, T.CASHBACK, Decimal("10"), 500_000),))
    under = SpendingProfile(monthly_spend_vnd={C.DINING: 4_000_000})
    over = SpendingProfile(monthly_spend_vnd={C.DINING: 9_000_000})
    assert rewards_value(card, under) == Decimal(400_000 * 12)
    assert rewards_value(card, over) == Decimal(500_000 * 12)


def test_specific_reward_beats_all_and_all_cap_is_shared() -> None:
    card = replace(
        X,
        rewards=(
            Reward(C.GROCERY, T.CASHBACK, Decimal("5")),
            Reward(C.ALL, T.CASHBACK, Decimal("1"), 50_000),
        ),
    )
    profile = SpendingProfile(
        monthly_spend_vnd={C.GROCERY: 1_000_000, C.OTHER: 3_000_000, C.FUEL: 3_000_000}
    )
    # grocery 5% = 50.000; the rest 6M at 1% = 60.000, capped at 50.000 together
    assert rewards_value(card, profile) == Decimal((50_000 + 50_000) * 12)


def test_foreign_spend_earns_overseas_rewards() -> None:
    card = replace(X, rewards=(Reward(C.OVERSEAS, T.CASHBACK, Decimal("2")),))
    profile = SpendingProfile(foreign_monthly_vnd=5_000_000)
    assert rewards_value(card, profile) == Decimal(100_000 * 12)


def test_no_cashback_no_rewards() -> None:
    card = replace(X, rewards=(Reward(C.ALL, T.MILES, None),))
    assert rewards_value(card, Q) == 0


@pytest.mark.parametrize(
    ("given", "unlimited", "value"),
    [
        (4, False, 4 * 400_000 + 500_000),
        (10, False, 6 * 400_000 + 500_000),
        (None, True, 6 * 400_000 + 500_000),
        (None, False, 500_000),
    ],
)
def test_perks(given: int | None, unlimited: bool, value: int) -> None:
    card = replace(X, lounge_visits_per_year=given, lounge_unlimited=unlimited)
    assert perks_value(card, Q) == value
    assert perks_value(replace(card, travel_insurance=False), Q) == value - 500_000


def test_fee_waived_from_exactly_the_threshold() -> None:
    profile = SpendingProfile(monthly_spend_vnd={C.OTHER: 200_000_000 // 12 + 1})
    assert scored(X, profile).fee_waived
    below = SpendingProfile(monthly_spend_vnd={C.OTHER: 200_000_000 // 12 - 1})
    s = scored(X, below)
    assert not s.fee_waived and s.annual_fee_vnd == 1_000_000
    exact = scored(
        replace(X, fee_waiver_spend_vnd=120_000_000),
        SpendingProfile(monthly_spend_vnd={C.OTHER: 10_000_000}),
    )
    assert exact.fee_waived and exact.annual_fee_vnd == 0
    no_rule = scored(replace(X, fee_waiver_spend_vnd=None), profile)
    assert not no_rule.fee_waived  # no waiver rule known: the fee is paid


def test_unknown_terms_are_never_guessed() -> None:
    def reasons(offer: CardOffer, profile: SpendingProfile) -> tuple[str, ...]:
        result = score_card(offer, profile)
        return result.reasons if isinstance(result, NotRanked) else ()

    pays_in_full = SpendingProfile(monthly_spend_vnd={C.OTHER: 1_000_000})
    assert reasons(replace(X, annual_fee_vnd=None), pays_in_full) == ("annual_fee_unknown",)
    # FX fee and interest rate only matter when the profile uses them
    assert reasons(replace(X, fx_fee_pct=None, interest_rate_pct=None), pays_in_full) == ()
    assert reasons(replace(X, fx_fee_pct=None), Q) == ("fx_fee_unknown",)
    assert reasons(replace(X, interest_rate_pct=None), Q) == ("interest_rate_unknown",)
    # no reward read yet is not "earns nothing": a spender's ranking needs it
    assert reasons(replace(X, rewards=()), pays_in_full) == ("rewards_unknown",)
    assert reasons(replace(X, rewards=()), SpendingProfile()) == ()  # no spend, no need
    points_only = (Reward(C.ALL, T.POINTS, None),)
    assert reasons(replace(X, rewards=points_only), pays_in_full) == ()  # known, flagged


def test_income_filter() -> None:
    modest = SpendingProfile(monthly_spend_vnd={C.OTHER: 1_000_000}, monthly_income_vnd=10_000_000)
    high = replace(X, min_monthly_income_vnd=20_000_000)
    result = score_card(high, modest)
    assert isinstance(result, NotRanked) and result.reasons == ("income_below_minimum",)
    assert scored(replace(X, min_monthly_income_vnd=10_000_000), modest)
    unknown = scored(X, modest)
    assert unknown.flags["income_requirement_unknown"]
    assert not scored(X, replace(modest, monthly_income_vnd=None)).flags[
        "income_requirement_unknown"
    ]


def test_ranking() -> None:
    cheap = replace(X, card_product_id=2, name="B", annual_fee_vnd=0)
    unknown = replace(X, card_product_id=3, name="C", annual_fee_vnd=None)
    ranked, skipped = rank_cards([X, unknown, cheap], Q)
    assert [(s.rank, s.offer.name) for s in ranked] == [(1, "B"), (2, "Ví Dụ Visa Platinum")]
    assert ranked[0].annual_value_vnd == 5_040_000
    assert [(n.offer.name, n.reasons) for n in skipped] == [("C", ("annual_fee_unknown",))]


def test_bad_profiles() -> None:
    with pytest.raises(ScoringError, match="all"):
        SpendingProfile(monthly_spend_vnd={C.ALL: 1})
    with pytest.raises(ScoringError, match="negative"):
        SpendingProfile(revolving_balance_vnd=-1)


def test_personas() -> None:
    assert list(PERSONAS) == ["everyday", "traveller", "first_card", "revolver"]
    everyday, traveller = PERSONAS["everyday"].profile, PERSONAS["traveller"].profile
    first, revolver = PERSONAS["first_card"].profile, PERSONAS["revolver"].profile
    assert everyday.revolving_balance_vnd == 0 and everyday.foreign_monthly_vnd == 0
    assert traveller.foreign_monthly_vnd > 0 and traveller.lounge_visits_wanted > 0
    assert first.monthly_income_vnd == 10_000_000
    assert revolver.revolving_balance_vnd > 0
    for p in PERSONAS.values():
        assert p.name_vi and p.name_en and p.profile.total_monthly_vnd > 0
    # the persona filters work through the formula
    picky = replace(X, min_monthly_income_vnd=30_000_000)
    assert isinstance(score_card(picky, first), NotRanked)
    assert isinstance(score_card(replace(X, interest_rate_pct=None), revolver), NotRanked)
