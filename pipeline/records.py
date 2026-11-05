"""Typed records that adapters return from parse().

Each record mirrors one versioned table (core/models.py), with database ids
replaced by what a bank page actually shows:

- SavingsRateRecord: institution_id is filled in by the runner from the source.
- Card records: card_product_id is replaced by the card's identity on the page
  (card_name, network); matching it to a card_product row is the diff step's job.

Records are strict: unknown fields are rejected, money is int VND, rates are
Decimal (never float), and values are checked against the same limits as the DB.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from core.enums import (
    CardNetwork,
    CardType,
    Channel,
    InterestPayment,
    RewardCategory,
    RewardType,
)
from core.models import CardInterest, CardPerk, CardReward, CardTerms, SavingsRate, Versioned


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("use Decimal or a string like '5.90', not float")
    return value


Pct = Annotated[
    Decimal, BeforeValidator(_no_float), Field(ge=0, le=100, max_digits=6, decimal_places=3)
]
Vnd = Annotated[int, Field(ge=0, strict=True)]
Text = Annotated[str, Field(min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    # The versioned table this record proposes values for.
    table: ClassVar[type[Versioned]]
    # Fields that identify the record on the page but are not DB columns.
    identity_fields: ClassVar[tuple[str, ...]] = ()
    # Provenance passed to propose_version(), not compared as a value.
    provenance_fields: ClassVar[tuple[str, ...]] = ("effective_from", "source_page", "evidence")

    # Date the bank says the value applies from, if the page states it.
    effective_from: dt.date | None = None
    # PDF page the value was read from (1-based), so a reviewer can jump to it.
    source_page: Annotated[int, Field(ge=1, strict=True)] | None = None
    # Per-field source for LLM-extracted values: {field: {"page", "quote", "value"}}.
    # Stored with the version (source_evidence) and shown next to each value in review.
    evidence: dict[str, Any] | None = None


class SavingsRateRecord(Record):
    table = SavingsRate

    # '' = nationwide; else the bank's region code, e.g. 'north', 'central_south'.
    region: Annotated[str, Field(pattern=r"^[a-z_]*$", max_length=32)] = ""
    product_name: Text
    channel: Channel
    term_months: Annotated[int, Field(ge=0, strict=True)]  # 0 with term_days 0 = demand deposit
    term_days: Annotated[int, Field(ge=0, strict=True)] = 0  # weekly terms: 7, 14, 21
    min_amount_vnd: Vnd = 0
    interest_payment: InterestPayment
    rate_pct: Pct
    conditions_text: str | None = None
    is_cd: bool = False

    @model_validator(mode="after")
    def _one_term_unit(self) -> "SavingsRateRecord":
        if self.term_months and self.term_days:
            raise ValueError("a term is in months or in days, not both")
        return self


class CardRecord(Record):
    identity_fields: ClassVar[tuple[str, ...]] = ("card_name", "network")

    card_name: Text
    network: CardNetwork


class CardTermsRecord(CardRecord):
    table = CardTerms
    identity_fields = ("card_name", "network", "card_type", "tier")

    card_type: CardType = CardType.CREDIT
    tier: str | None = None
    annual_fee_primary_vnd: Vnd | None = None
    annual_fee_supp_vnd: Vnd | None = None
    fee_waiver_rule_text: str | None = None
    fee_waiver_spend_vnd: Vnd | None = None
    interest_rate_pct: Pct | None = None
    interest_free_days: Annotated[int, Field(ge=0, strict=True)] | None = None
    cash_advance_pct: Pct | None = None
    cash_advance_min_vnd: Vnd | None = None
    fx_fee_pct: Pct | None = None
    late_fee_pct: Pct | None = None
    late_fee_min_vnd: Vnd | None = None
    min_monthly_income_vnd: Vnd | None = None


class CardRewardRecord(CardRecord):
    table = CardReward

    category: RewardCategory
    reward_type: RewardType
    rate_pct: Pct | None = None
    points_per_spend: Annotated[Decimal, BeforeValidator(_no_float), Field(ge=0)] | None = None
    spend_unit_vnd: Annotated[int, Field(gt=0, strict=True)] | None = None
    monthly_cap_vnd: Vnd | None = None
    conditions_text: str | None = None

    @model_validator(mode="after")
    def _earn_rate_present(self) -> "CardRewardRecord":
        # Same rule as the ck_card_reward_earn_rate_present constraint.
        if self.reward_type is RewardType.CASHBACK and self.rate_pct is None:
            raise ValueError("cashback rewards need rate_pct")
        if self.reward_type is not RewardType.CASHBACK and (
            self.points_per_spend is None or self.spend_unit_vnd is None
        ):
            raise ValueError("points/miles rewards need points_per_spend and spend_unit_vnd")
        return self


class CardPerkRecord(CardRecord):
    table = CardPerk

    lounge_visits_per_year: Annotated[int, Field(ge=0, strict=True)] | None = None
    lounge_unlimited: bool = False
    travel_insurance: bool = False
    travel_insurance_cover_vnd: Vnd | None = None
    other_perks_text: str | None = None


class CardInterestRecord(CardRecord):
    """Yearly interest as a card's product page states it (card_interest)."""

    table = CardInterest

    interest_rate_pct: Pct
    interest_free_days: Annotated[int, Field(ge=0, strict=True)] | None = None


RECORD_TYPES: tuple[type[Record], ...] = (
    SavingsRateRecord,
    CardTermsRecord,
    CardRewardRecord,
    CardPerkRecord,
    CardInterestRecord,
)
