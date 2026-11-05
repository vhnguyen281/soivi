"""The fields the LLM may extract, what each means, and how its value is parsed.

Names match the columns of card_terms / card_reward / card_perk / card_interest, so a verified
fact maps straight onto a record field.
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["money", "pct", "int", "decimal", "bool", "text"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: Kind
    meaning: str  # shown to the model


TERMS = (
    FieldSpec("annual_fee_primary_vnd", "money", "annual fee (phí thường niên), primary card"),
    FieldSpec(
        "annual_fee_supp_vnd",
        "money",
        "annual fee of a supplementary card (thẻ phụ); only when the document states it, "
        "including 'áp dụng cho cả thẻ chính và thẻ phụ'",
    ),
    FieldSpec(
        "fee_waiver_spend_vnd",
        "money",
        "total spend in the previous year that waives the next year's annual fee",
    ),
    FieldSpec("fee_waiver_rule_text", "text", "the rule for waiving the annual fee, as written"),
    FieldSpec(
        "interest_rate_pct",
        "pct",
        "credit card interest rate, percent per year; only when the document says it is "
        "per year (năm)",
    ),
    FieldSpec("interest_free_days", "int", "maximum interest-free period, in days"),
    FieldSpec("cash_advance_pct", "pct", "cash advance / cash withdrawal fee, percent"),
    FieldSpec("cash_advance_min_vnd", "money", "minimum cash advance fee"),
    FieldSpec(
        "fx_fee_pct", "pct", "foreign-currency transaction fee (phí giao dịch ngoại tệ), percent"
    ),
    FieldSpec("late_fee_pct", "pct", "late payment fee (phí chậm thanh toán), percent"),
    FieldSpec("late_fee_min_vnd", "money", "minimum late payment fee"),
    FieldSpec("min_monthly_income_vnd", "money", "minimum monthly income to be eligible"),
)

PERKS = (
    FieldSpec("lounge_visits_per_year", "int", "free airport lounge visits per year"),
    FieldSpec(
        "lounge_unlimited",
        "bool",
        "'true' only if lounge access is stated to be unlimited (không giới hạn)",
    ),
    FieldSpec("travel_insurance", "bool", "'true' if travel insurance is included"),
    FieldSpec("travel_insurance_cover_vnd", "money", "maximum travel insurance cover"),
    FieldSpec("other_perks_text", "text", "other perks (lounge, golf, dining...), as written"),
)

REWARDS = (
    FieldSpec("rate_pct", "pct", "cashback rate, percent (cashback only)"),
    FieldSpec("points_per_spend", "decimal", "points or miles earned per spend unit"),
    FieldSpec("spend_unit_vnd", "money", "the spend unit for points_per_spend, e.g. 20.000 VND"),
    FieldSpec("monthly_cap_vnd", "money", "maximum reward per month"),
    FieldSpec("conditions_text", "text", "conditions of this reward, as written"),
)

# Product pages often state the card's interest; it goes to card_interest, never
# card_terms, so the fee schedule and the product page don't write the same row.
INTEREST = tuple(f for f in TERMS if f.name in ("interest_rate_pct", "interest_free_days"))
PRODUCT_CARD_FIELDS = (*PERKS, *INTEREST)

BY_NAME = {f.name: f for f in (*TERMS, *PERKS, *REWARDS)}
