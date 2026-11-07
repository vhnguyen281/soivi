"""Response models. They define the JSON and the OpenAPI docs (/docs, /openapi.json).

Money is integer VND. Rates are decimals serialised as strings ("5.900"), never
floats. Every value carries its provenance, and every response its methodology
version.
"""

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.scoring import METHODOLOGY_VERSION


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Envelope(Model):
    methodology_version: str = Field(
        default=METHODOLOGY_VERSION, description="Version of docs/methodology.md in force"
    )


class Provenance(Model):
    """Where a value comes from (CLAUDE.md principle 2)."""

    source_url: str | None = Field(description="The bank's own page or document")
    checked_at: dt.datetime | None = Field(
        description="Last time we read the source and found this value"
    )
    effective_from: dt.date | None = Field(description="Date the bank says the value applies")
    approved_at: dt.datetime | None = None
    extraction_method: str | None = None
    snapshot_sha256: str | None = Field(default=None, description="Hash of the stored copy")
    methodology_version: str = METHODOLOGY_VERSION
    evidence: dict[str, Any] | None = Field(
        default=None, description="For LLM-read values: page and exact quote per field"
    )


class Error(Envelope):
    error: Any
    details: list[dict[str, Any]] | None = None


# --------------------------------------------------------------------------- institutions


class InstitutionOut(Model):
    id: int
    short_name: str
    legal_name_vi: str
    type: str
    website: str | None
    deposit_insurance: bool
    verification: str = Field(description="verified | unverified | no_sources")
    unverified: bool
    provenance: Provenance


class InstitutionsOut(Envelope):
    institutions: list[InstitutionOut]


# --------------------------------------------------------------------------- savings


class InstitutionRef(Model):
    short_name: str
    legal_name_vi: str


class SavingsRateOut(Model):
    id: int = Field(description="Version id of this rate")
    institution: InstitutionRef
    product_name: str
    channel: str
    region: str
    term_months: int
    term_days: int
    min_amount_vnd: int
    interest_payment: str
    rate_pct: Decimal
    conditions_text: str | None
    is_cd: bool
    unverified: bool
    provenance: Provenance


class SavingsRatesOut(Envelope):
    rates: list[SavingsRateOut]


class SavingsRankItem(Model):
    rank: int
    rate: SavingsRateOut
    equivalent_interest_vnd: int = Field(description="Ranking basis: value at maturity")
    cash_interest_vnd: int = Field(description="Interest the bank pays in total")
    equivalent_rate_pct: Decimal
    maturity_value_vnd: int
    flags: dict[str, bool | None]


class SavingsRankOut(Envelope):
    query: dict[str, Any]
    results: list[SavingsRankItem]
    excluded_min_amount: int = Field(description="Offers left out: minimum above the amount")


class HistoryPoint(Model):
    version_id: int
    rate_pct: Decimal
    valid_from: dt.datetime | None = Field(description="Approved (published) at")
    valid_to: dt.datetime | None = Field(description="Replaced at; null while current")
    provenance: Provenance


class HistorySeries(Model):
    product_name: str
    channel: str
    region: str
    term_months: int
    term_days: int
    min_amount_vnd: int
    interest_payment: str
    points: list[HistoryPoint]


class HistoryOut(Envelope):
    institution: InstitutionRef
    series: list[HistorySeries]


# --------------------------------------------------------------------------- cards


class Valued(Model):
    """One versioned row's values, with provenance."""

    version_id: int
    values: dict[str, Any]
    provenance: Provenance


class CardSummary(Model):
    id: int
    institution: InstitutionRef
    name: str
    network: str
    card_type: str
    tier: str | None
    unverified: bool
    terms: Valued | None
    rewards_count: int


class CardsOut(Envelope):
    cards: list[CardSummary]


class CardDetail(CardSummary):
    rewards: list[Valued]
    perks: Valued | None
    interest: Valued | None = Field(
        default=None,
        description="Yearly interest from the card's product page; used instead of terms'",
    )


class CardOut(Envelope):
    card: CardDetail


class CardRankItem(Model):
    rank: int
    card: CardSummary
    annual_value_vnd: int
    breakdown: dict[str, int | bool]
    flags: dict[str, bool]
    provenance: list[Provenance] = Field(description="Every approved row the score used")


class CardNotRanked(Model):
    card: CardSummary
    reasons: list[str]


class CardRankOut(Envelope):
    persona: str | None
    profile: dict[str, Any]
    results: list[CardRankItem]
    not_ranked: list[CardNotRanked]


class PersonaOut(Model):
    key: str
    name_vi: str
    name_en: str
    profile: dict[str, Any]


class PersonasOut(Envelope):
    personas: list[PersonaOut]


# --------------------------------------------------------------------------- changes


class FieldChange(Model):
    field: str
    old: Any
    new: Any


class ChangeOut(Model):
    table: str
    version_id: int
    kind: str = Field(description="new | changed")
    institution: InstitutionRef
    label: str
    approved_at: dt.datetime
    changes: list[FieldChange]
    provenance: Provenance


class ChangesOut(Envelope):
    since: dt.date
    changes: list[ChangeOut]


# --------------------------------------------------------------------------- reports


class ReportCreated(Envelope):
    id: int
    status: str
    message: str


class MethodologyOut(Envelope):
    document: str
    savings_channels: list[str]
    spend_categories: list[str]
    personas: list[str]


# --------------------------------------------------------------------------- VNCMA


class VncmaScenarios(Model):
    adverse: Decimal
    base: Decimal
    favourable: Decimal


class VncmaClass(Model):
    id: str
    name: str
    expected_return: Decimal = Field(description="Geometric, VND nominal, percent per year (final)")
    model_return: Decimal
    adjustment_pp: Decimal
    adjustment_reason: str | None = None
    arithmetic_return: Decimal | None = None
    volatility: Decimal | None = Field(default=None, description="Annual, percent")
    volatility_historical: Decimal | None = None
    band_80: list[Decimal] | None = Field(
        default=None, description="expected +- 1.28 vol / sqrt(10)"
    )
    range: list[Decimal] | None = Field(default=None, description="Low and high (real estate)")
    scenarios: VncmaScenarios
    grade: str = Field(description="Data quality: A, B or C")
    optimizer_default: bool
    formula: str


class VncmaCorrelation(Model):
    classes: list[str]
    matrix: list[list[float]]


class VncmaMacro(Model):
    value: Decimal
    name: str
    derivation: str


class VncmaProvenance(Model):
    run_id: int
    code_version: str
    config_sha256: str
    inputs_sha256: str
    payload_sha256: str | None = None


class VncmaOut(Model):
    """One approved VNCMA release. `methodology_version` is the VNCMA method's version."""

    version: str
    status: str
    methodology_version: str
    as_of: dt.date
    horizon_years: int
    currency: str
    return_basis: str
    approved_by: str | None
    approved_at: dt.datetime | None
    classes: list[VncmaClass]
    correlation: VncmaCorrelation
    macro: dict[str, VncmaMacro]
    checks: list[str]
    provenance: VncmaProvenance
    disclaimer: dict[str, str]
    methodology_url: str
    downloads: dict[str, str]


class VncmaReleaseRef(Model):
    version: str
    as_of: dt.date
    approved_at: dt.datetime
    methodology_version: str


class VncmaReleasesOut(Envelope):
    releases: list[VncmaReleaseRef]


class ModelWeight(Model):
    asset_class: str
    name: str
    percent: int


class ModelPortfolio(Model):
    id: str
    name: str
    name_en: str
    target_volatility: Decimal
    weights: list[ModelWeight]
    expected_return: Decimal = Field(description="Geometric, VND, percent per year")
    expected_return_arithmetic: Decimal
    volatility: Decimal


class ModelPortfoliosOut(Model):
    """Model portfolios approved for one VNCMA release (asset-class level, not advice)."""

    release: str
    as_of: dt.date
    methodology_version: str
    vncma_methodology_version: str
    approved_by: str
    approved_at: dt.datetime
    bounds: dict[str, list[Decimal]]
    resampling: dict[str, int]
    config_sha256: str
    payload_sha256: str
    portfolios: list[ModelPortfolio]
    disclaimer: dict[str, str]


class FundStatsOut(Model):
    """Fund statistics by group (open-end equity, bond, balanced funds; ETFs), approved by a
    named reviewer. Derived figures only; no fund is named until its NAV is confirmed with
    the manager (DECISIONS 2026-11-07)."""

    as_of: dt.date
    horizons: list[int]
    groups: dict[str, Any]
    benchmarks: dict[str, dict[str, float | None]]
    approved_by: str
    approved_at: dt.datetime
    payload_sha256: str
    method: str
    disclaimer: dict[str, str]
