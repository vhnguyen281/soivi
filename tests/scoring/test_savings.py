"""Savings formulas. Expected values were computed separately with exact fractions."""

from decimal import Decimal

import pytest

from core.enums import Channel, InterestPayment
from core.scoring.savings import (
    SavingsOffer,
    SavingsQuery,
    ScoringError,
    cash_interest,
    equivalent_interest,
    excluded_by_amount,
    flags,
    rank_savings,
    vnd,
)

P = 100_000_000
END, MONTHLY, QUARTERLY, UPFRONT = (
    InterestPayment.END,
    InterestPayment.MONTHLY,
    InterestPayment.QUARTERLY,
    InterestPayment.UPFRONT,
)


def offer(**kw: object) -> SavingsOffer:
    values: dict[str, object] = {
        "version_id": 1,
        "institution": "VIDU",
        "institution_name": "Ngân hàng TMCP Ví Dụ",
        "product_name": "Tiết kiệm thường",
        "channel": Channel.COUNTER,
        "term_months": 12,
        "min_amount_vnd": 0,
        "interest_payment": END,
        "rate_pct": Decimal("6.00"),
        "deposit_insurance": True,
    }
    values.update(kw)
    return SavingsOffer(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- formulas


@pytest.mark.parametrize(
    ("rate", "months", "payment", "expected"),
    [
        ("6.00", 12, END, 6_000_000),  # P r t
        ("5.50", 6, END, 2_750_000),
        ("5.80", 12, MONTHLY, 5_956_695),  # P[(1 + r/12)^12 - 1]
        ("5.90", 12, QUARTERLY, 6_031_826),  # P[(1 + r/4)^4 - 1]
        ("5.90", 7, QUARTERLY, 3_478_034),  # 2 quarters + 1 leftover month
        ("5.50", 12, UPFRONT, 5_802_500),  # P r t (1 + r t)
        ("5.50", 6, UPFRONT, 2_825_625),
    ],
)
def test_equivalent_interest(
    rate: str, months: int, payment: InterestPayment, expected: int
) -> None:
    assert vnd(equivalent_interest(P, Decimal(rate), months, payment)) == expected


def test_cash_interest_is_the_same_whatever_the_schedule() -> None:
    assert vnd(cash_interest(P, Decimal("5.80"), 12)) == 5_800_000
    assert vnd(cash_interest(P, Decimal("5.80"), 3)) == 1_450_000


def test_earlier_payment_is_worth_more_at_the_same_rate() -> None:
    rate = Decimal("6.00")
    end = equivalent_interest(P, rate, 12, END)
    for payment in (MONTHLY, QUARTERLY, UPFRONT):
        assert equivalent_interest(P, rate, 12, payment) > end
    # one-month term: every schedule pays once, at the same time as END
    assert equivalent_interest(P, rate, 1, MONTHLY) == equivalent_interest(P, rate, 1, END)


def test_rounding_is_half_up_to_whole_dong() -> None:
    assert vnd(Decimal("1.5")) == 2 and vnd(Decimal("2.4999")) == 2
    assert vnd(cash_interest(1_000, Decimal("5.55"), 1)) == 5  # 4.625 -> 5


# --------------------------------------------------------------------------- ranking


def test_ranked_by_value_at_maturity_not_by_quoted_rate() -> None:
    offers = [
        offer(version_id=1, institution="A", rate_pct=Decimal("5.95"), interest_payment=END),
        offer(version_id=2, institution="B", rate_pct=Decimal("5.80"), interest_payment=MONTHLY),
        offer(version_id=3, institution="C", rate_pct=Decimal("5.50"), interest_payment=UPFRONT),
    ]
    results = rank_savings(offers, SavingsQuery(P, 12))
    assert [(r.rank, r.offer.institution, r.equivalent_interest_vnd) for r in results] == [
        (1, "B", 5_956_695),  # lower quoted rate, but paid monthly
        (2, "A", 5_950_000),
        (3, "C", 5_802_500),
    ]
    assert results[0].cash_interest_vnd == 5_800_000
    assert results[0].equivalent_rate_pct == Decimal("5.957")


def test_ties_are_broken_by_rate_then_name() -> None:
    offers = [offer(version_id=1, institution="Z"), offer(version_id=2, institution="A")]
    assert [r.offer.institution for r in rank_savings(offers, SavingsQuery(P, 12))] == ["A", "Z"]


def test_minimum_amount_excludes_and_picks_the_right_tier() -> None:
    offers = [
        offer(version_id=1, min_amount_vnd=0, rate_pct=Decimal("5.50")),
        offer(version_id=2, min_amount_vnd=1_000_000_000, rate_pct=Decimal("5.70")),
        offer(version_id=3, min_amount_vnd=3_000_000_000, rate_pct=Decimal("5.90")),
    ]
    [small] = rank_savings(offers, SavingsQuery(500_000_000, 12))
    assert small.offer.version_id == 1  # one product, listed once, at its own tier
    [mid] = rank_savings(offers, SavingsQuery(2_000_000_000, 12))
    assert mid.offer.version_id == 2
    assert excluded_by_amount(offers, SavingsQuery(2_000_000_000, 12)) == 1
    assert excluded_by_amount(offers, SavingsQuery(500_000_000, 12)) == 2


def test_only_the_requested_term() -> None:
    offers = [offer(version_id=1, term_months=6), offer(version_id=2, term_months=12)]
    assert [r.offer.version_id for r in rank_savings(offers, SavingsQuery(P, 12))] == [2]


@pytest.mark.parametrize(
    ("preference", "channels"),
    [
        ("any", {"counter", "online", "app"}),
        ("counter", {"counter"}),
        ("online", {"online"}),
        ("app", {"app"}),
        ("digital", {"online", "app"}),
    ],
)
def test_channel_preference(preference: str, channels: set[str]) -> None:
    offers = [
        offer(version_id=i, channel=c, product_name=c.value) for i, c in enumerate(Channel, 1)
    ]
    found = {r.offer.channel.value for r in rank_savings(offers, SavingsQuery(P, 12, preference))}
    assert found == channels


def test_region() -> None:
    offers = [
        offer(version_id=1, region=""),
        offer(version_id=2, region="north", product_name="B"),
        offer(version_id=3, region="central_south", product_name="C"),
    ]
    assert len(rank_savings(offers, SavingsQuery(P, 12))) == 3
    north = rank_savings(offers, SavingsQuery(P, 12, region="north"))
    assert sorted(r.offer.version_id for r in north) == [1, 2]
    assert [r.flags["regional"] for r in north if r.offer.version_id == 2] == [True]


@pytest.mark.parametrize(
    ("kw", "error"),
    [
        ({"amount_vnd": 0, "term_months": 12}, "amount"),
        ({"amount_vnd": P, "term_months": 0}, "term"),
        ({"amount_vnd": P, "term_months": 12, "channel": "atm"}, "channel"),
    ],
)
def test_bad_queries(kw: dict[str, object], error: str) -> None:
    with pytest.raises(ScoringError, match=error):
        SavingsQuery(**kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- flags


def test_flags_from_the_banks_own_conditions() -> None:
    plain = flags(offer())
    assert plain == {
        "new_customer_only": False,
        "app_only": False,
        "early_withdrawal_penalty": True,
        "early_withdrawal_terms_stated": False,
        "rate_is_maximum": False,
        "certificate_of_deposit": False,
        "deposit_insurance": True,
        "regional": False,
        "unverified": False,
    }
    rich = flags(
        offer(
            conditions_text="Mức lãi suất tối đa; chỉ áp dụng cho khách hàng mới gửi trên "
            "ứng dụng; rút trước hạn hưởng lãi không kỳ hạn",
            is_cd=True,
            deposit_insurance=None,
            verified=False,
        )
    )
    assert rich["new_customer_only"] and rich["app_only"] and rich["rate_is_maximum"]
    assert rich["early_withdrawal_terms_stated"] and rich["certificate_of_deposit"]
    assert rich["deposit_insurance"] is None and rich["unverified"]
    assert flags(offer(channel=Channel.APP))["app_only"]
    # "áp dụng" (applies) is not "app"
    assert not flags(offer(conditions_text="Áp dụng cho kỳ hạn 6 tháng"))["app_only"]
