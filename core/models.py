"""ORM models. Every model lives here so Alembic autogenerate can see it.

Conventions (CLAUDE.md): money is integer VND (BIGINT), rates are percent per year
as NUMERIC, terms are months (0 = demand deposit). Timestamps are timezone-aware.

Versioned tables (SavingsRate, CardTerms, CardReward, CardPerk, CardInterest) extend `Versioned`.
Never write them directly: use the helpers in core/versioning.py.
"""

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.enums import (
    CardNetwork,
    CardType,
    Channel,
    CommunityReportStatus,
    ExtractionMethod,
    FetchMethod,
    InstitutionType,
    InterestPayment,
    NewsClassification,
    NewsDirection,
    ReviewActionKind,
    ReviewTaskKind,
    ReviewTaskStatus,
    RewardCategory,
    RewardType,
    SourceKind,
    VersionStatus,
)

TZDateTime = DateTime(timezone=True)
Pct = Numeric(6, 3)  # percent, e.g. 5.900


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK constraint holding the enum's values (not its member names)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


def non_negative(*cols: str) -> list[CheckConstraint]:
    return [CheckConstraint(f"{c} IS NULL OR {c} >= 0", name=f"{c}_non_negative") for c in cols]


def pct_range(*cols: str) -> list[CheckConstraint]:
    return [
        CheckConstraint(f"{c} IS NULL OR ({c} >= 0 AND {c} <= 100)", name=f"{c}_range")
        for c in cols
    ]


# --------------------------------------------------------------------------- reference data


class Institution(Base):
    __tablename__ = "institution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legal_name_vi: Mapped[str] = mapped_column(Text)
    short_name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[InstitutionType] = mapped_column(str_enum(InstitutionType, "institution_type"))
    sbv_licence_no: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(Text)
    deposit_insurance: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # True when a seeded fact (name, type, website) still needs a human to confirm it.
    needs_check: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint("cadence_hours > 0", name="cadence_hours_positive"),
        # A source without a known URL is a to-do item and must be flagged.
        CheckConstraint("url IS NOT NULL OR needs_check", name="url_or_needs_check"),
        UniqueConstraint(
            "institution_id", "kind", "variant", name="uq_source_institution_kind_variant"
        ),
        # One page can hold several kinds (e.g. MB's /fee has savings rates and card fees).
        UniqueConstraint("url", "kind", name="uq_source_url_kind"),
        *non_negative("consecutive_failures"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Null for feeds that are not about one institution (news, SBV announcements).
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institution.id"), index=True)
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind, "source_kind"))
    # Distinguishes several sources of one kind, e.g. a bank's counter and online
    # rate pages. Empty for the usual single source.
    variant: Mapped[str] = mapped_column(String(32), server_default=text("''"))
    url: Mapped[str | None] = mapped_column(Text)
    fetch_method: Mapped[FetchMethod] = mapped_column(str_enum(FetchMethod, "fetch_method"))
    cadence_hours: Mapped[int] = mapped_column(Integer)
    adapter_name: Mapped[str | None] = mapped_column(String(64))
    # Null until robots.txt has been checked.
    robots_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Monitoring: the outcome of the most recent run (runner.Status) and when it ran.
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    needs_check: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Snapshot(Base):
    """One fetched file, stored in MinIO. Append-only (enforced by a DB trigger)."""

    __tablename__ = "snapshot"
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        Index("ix_snapshot_source_id_fetched_at", "source_id", "fetched_at"),
        Index("ix_snapshot_sha256", "sha256"),
        *non_negative("size_bytes"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    # The URL actually fetched; source.url may change later.
    url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Same sha256 as the previous snapshot of this source: nothing was parsed.
    unchanged: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# --------------------------------------------------------------------------- versioning

# Columns that describe where a version came from; not compared when diffing values.
PROVENANCE_COLUMNS = frozenset(
    {"id", "snapshot_id", "effective_from", "extraction_method", "proposed_at", "source_evidence"}
)
# Columns that may change after insert (the DB trigger freezes everything else).
LIFECYCLE_COLUMNS = frozenset(
    {
        "status",
        "valid_from",
        "valid_to",
        "reviewer",
        "decided_at",
        "review_task_id",
        "last_seen_snapshot_id",
        "last_seen_at",
    }
)

_LIFECYCLE_CHECK = """
(status = 'pending' AND valid_from IS NULL AND valid_to IS NULL
    AND reviewer IS NULL AND decided_at IS NULL)
OR (status = 'approved' AND valid_from IS NOT NULL
    AND reviewer IS NOT NULL AND decided_at IS NOT NULL)
OR (status = 'rejected' AND valid_from IS NULL AND valid_to IS NULL
    AND reviewer IS NOT NULL AND decided_at IS NOT NULL)
OR (status = 'superseded' AND valid_from IS NULL AND valid_to IS NULL
    AND decided_at IS NOT NULL)
"""


def versioned_table_args(table: str, key: tuple[str, ...], *extra: Any) -> tuple[Any, ...]:
    """Indexes and checks shared by every versioned table.

    The two partial unique indexes guarantee at most one current approved version
    and at most one pending version per key.
    """
    return (
        Index(
            f"uq_{table}_current",
            *key,
            unique=True,
            postgresql_where=text("status = 'approved' AND valid_to IS NULL"),
        ),
        Index(
            f"uq_{table}_pending", *key, unique=True, postgresql_where=text("status = 'pending'")
        ),
        Index(f"ix_{table}_snapshot_id", "snapshot_id"),
        CheckConstraint(_LIFECYCLE_CHECK, name="lifecycle"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        *extra,
    )


class Versioned(Base):
    """Base for versioned value tables.

    A row's values never change after insert. Lifecycle:
    pending -> approved (current while valid_to IS NULL) | rejected | superseded.
    Subclasses set `__version_key__`: the columns that identify one value series
    (e.g. bank + product + channel + term + tier).
    """

    __abstract__ = True
    __version_key__: ClassVar[tuple[str, ...]]

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Provenance (principle 2). Source URL and hash come through the snapshot.
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshot.id"))
    effective_from: Mapped[dt.date | None] = mapped_column(Date)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        str_enum(ExtractionMethod, "extraction_method")
    )
    proposed_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())
    # Where each value was read, for LLM-extracted values:
    # {field: {"page": 3, "quote": "exact text from the document", "value": "as written"}}.
    # Frozen like every other non-lifecycle column.
    source_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Lifecycle.
    status: Mapped[VersionStatus] = mapped_column(
        str_enum(VersionStatus, "status"), server_default=VersionStatus.PENDING.value
    )
    valid_from: Mapped[dt.datetime | None] = mapped_column(TZDateTime)  # = approved_at
    valid_to: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    reviewer: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    review_task_id: Mapped[int | None] = mapped_column(ForeignKey("review_task.id"))

    # Last time a fetch confirmed these values unchanged ("checked on ...").
    last_seen_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshot.id"))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)


# --------------------------------------------------------------------------- savings

SAVINGS_RATE_KEY = (
    "institution_id",
    "region",
    "product_name",
    "channel",
    "term_months",
    "term_days",
    "min_amount_vnd",
    "interest_payment",
)


class SavingsRate(Versioned):
    __tablename__ = "savings_rate"
    __version_key__ = SAVINGS_RATE_KEY
    __table_args__ = versioned_table_args(
        "savings_rate",
        SAVINGS_RATE_KEY,
        *non_negative("term_months", "term_days", "min_amount_vnd"),
        # A term is either months or days (weekly terms), never both. 0/0 = demand deposit.
        CheckConstraint("term_months = 0 OR term_days = 0", name="one_term_unit"),
        CheckConstraint("region ~ '^[a-z_]*$'", name="region_code"),
        *pct_range("rate_pct"),
    )

    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id"))
    # '' = applies nationwide. Otherwise a lowercase code for the bank's own region
    # split, e.g. 'north' / 'central_south' (MB) or 'hanoi' / 'hcm' (BIDV).
    region: Mapped[str] = mapped_column(String(32), server_default=text("''"))
    product_name: Mapped[str] = mapped_column(Text)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel, "channel"))
    term_months: Mapped[int] = mapped_column(Integer)
    # Terms shorter than a month ("1 tuần" = 7). 0 when the term is in months.
    term_days: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Tier floor; 0 when the rate applies to any amount.
    min_amount_vnd: Mapped[int] = mapped_column(BigInteger)
    interest_payment: Mapped[InterestPayment] = mapped_column(
        str_enum(InterestPayment, "interest_payment")
    )
    rate_pct: Mapped[Decimal] = mapped_column(Pct)
    conditions_text: Mapped[str | None] = mapped_column(Text)
    is_cd: Mapped[bool] = mapped_column(Boolean)


# --------------------------------------------------------------------------- cards


class CardProduct(Base):
    __tablename__ = "card_product"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "name", "network", name="uq_card_product_institution_name_network"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id"))
    name: Mapped[str] = mapped_column(Text)
    network: Mapped[CardNetwork] = mapped_column(str_enum(CardNetwork, "network"))
    # Bank wording (classic / gold / platinum / signature ...); not normalised yet.
    tier: Mapped[str | None] = mapped_column(String(64))
    card_type: Mapped[CardType] = mapped_column(str_enum(CardType, "card_type"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())


CARD_TERMS_KEY = ("card_product_id",)


class CardTerms(Versioned):
    __tablename__ = "card_terms"
    __version_key__ = CARD_TERMS_KEY
    __table_args__ = versioned_table_args(
        "card_terms",
        CARD_TERMS_KEY,
        *non_negative(
            "annual_fee_primary_vnd",
            "annual_fee_supp_vnd",
            "fee_waiver_spend_vnd",
            "interest_free_days",
            "cash_advance_min_vnd",
            "late_fee_min_vnd",
            "min_monthly_income_vnd",
        ),
        *pct_range("interest_rate_pct", "cash_advance_pct", "fx_fee_pct", "late_fee_pct"),
    )

    card_product_id: Mapped[int] = mapped_column(ForeignKey("card_product.id"))
    annual_fee_primary_vnd: Mapped[int | None] = mapped_column(BigInteger)
    annual_fee_supp_vnd: Mapped[int | None] = mapped_column(BigInteger)
    fee_waiver_rule_text: Mapped[str | None] = mapped_column(Text)
    fee_waiver_spend_vnd: Mapped[int | None] = mapped_column(BigInteger)
    interest_rate_pct: Mapped[Decimal | None] = mapped_column(Pct)  # per year
    interest_free_days: Mapped[int | None] = mapped_column(Integer)  # maximum
    cash_advance_pct: Mapped[Decimal | None] = mapped_column(Pct)
    cash_advance_min_vnd: Mapped[int | None] = mapped_column(BigInteger)
    fx_fee_pct: Mapped[Decimal | None] = mapped_column(Pct)
    late_fee_pct: Mapped[Decimal | None] = mapped_column(Pct)
    late_fee_min_vnd: Mapped[int | None] = mapped_column(BigInteger)
    min_monthly_income_vnd: Mapped[int | None] = mapped_column(BigInteger)


CARD_REWARD_KEY = ("card_product_id", "category", "reward_type")


class CardReward(Versioned):
    """Cashback is a percent. Points/miles are stored as the bank states them
    (N points per X VND); converting them to a value is the scoring formula's job."""

    __tablename__ = "card_reward"
    __version_key__ = CARD_REWARD_KEY
    __table_args__ = versioned_table_args(
        "card_reward",
        CARD_REWARD_KEY,
        CheckConstraint(
            "(reward_type = 'cashback' AND rate_pct IS NOT NULL)"
            " OR (reward_type IN ('points', 'miles')"
            " AND points_per_spend IS NOT NULL AND spend_unit_vnd IS NOT NULL)",
            name="earn_rate_present",
        ),
        CheckConstraint("spend_unit_vnd IS NULL OR spend_unit_vnd > 0", name="spend_unit_positive"),
        *non_negative("points_per_spend", "monthly_cap_vnd"),
        *pct_range("rate_pct"),
    )

    card_product_id: Mapped[int] = mapped_column(ForeignKey("card_product.id"))
    category: Mapped[RewardCategory] = mapped_column(str_enum(RewardCategory, "category"))
    reward_type: Mapped[RewardType] = mapped_column(str_enum(RewardType, "reward_type"))
    rate_pct: Mapped[Decimal | None] = mapped_column(Pct)
    points_per_spend: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    spend_unit_vnd: Mapped[int | None] = mapped_column(BigInteger)
    monthly_cap_vnd: Mapped[int | None] = mapped_column(BigInteger)
    conditions_text: Mapped[str | None] = mapped_column(Text)


CARD_PERK_KEY = ("card_product_id",)


class CardPerk(Versioned):
    __tablename__ = "card_perk"
    __version_key__ = CARD_PERK_KEY
    __table_args__ = versioned_table_args(
        "card_perk",
        CARD_PERK_KEY,
        *non_negative("lounge_visits_per_year", "travel_insurance_cover_vnd"),
    )

    card_product_id: Mapped[int] = mapped_column(ForeignKey("card_product.id"))
    # Null + lounge_unlimited = unlimited; null + not unlimited = not stated.
    lounge_visits_per_year: Mapped[int | None] = mapped_column(Integer)
    lounge_unlimited: Mapped[bool] = mapped_column(Boolean)
    travel_insurance: Mapped[bool] = mapped_column(Boolean)
    travel_insurance_cover_vnd: Mapped[int | None] = mapped_column(BigInteger)
    other_perks_text: Mapped[str | None] = mapped_column(Text)


CARD_INTEREST_KEY = ("card_product_id",)


class CardInterest(Versioned):
    """A card's yearly interest rate as its product page states it ("20%/năm").

    Kept apart from card_terms (read from the fee schedule) so two sources never
    write the same row. Scoring uses this rate when present, else card_terms'.
    Only rates stated per year are stored; nothing is converted.
    """

    __tablename__ = "card_interest"
    __version_key__ = CARD_INTEREST_KEY
    __table_args__ = versioned_table_args(
        "card_interest",
        CARD_INTEREST_KEY,
        *non_negative("interest_free_days"),
        *pct_range("interest_rate_pct"),
    )

    card_product_id: Mapped[int] = mapped_column(ForeignKey("card_product.id"))
    interest_rate_pct: Mapped[Decimal] = mapped_column(Pct)  # per year
    interest_free_days: Mapped[int | None] = mapped_column(Integer)  # maximum


# --------------------------------------------------------------------------- review


class ReviewTask(Base):
    __tablename__ = "review_task"
    __table_args__ = (Index("ix_review_task_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id"))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshot.id"))
    kind: Mapped[ReviewTaskKind] = mapped_column(str_enum(ReviewTaskKind, "kind"))
    status: Mapped[ReviewTaskStatus] = mapped_column(
        str_enum(ReviewTaskStatus, "status"), server_default=ReviewTaskStatus.OPEN.value
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())
    reviewer: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    note: Mapped[str | None] = mapped_column(Text)


class ReviewAction(Base):
    """Audit log: who decided what, and when. Append-only (DB trigger)."""

    __tablename__ = "review_action"
    __table_args__ = (
        Index("ix_review_action_created_at", "created_at"),
        Index("ix_review_action_review_task_id", "review_task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    review_task_id: Mapped[int] = mapped_column(ForeignKey("review_task.id"))
    action: Mapped[ReviewActionKind] = mapped_column(str_enum(ReviewActionKind, "action"))
    # Set for single-version actions; task-level actions list versions in `version_ids`.
    version_table: Mapped[str | None] = mapped_column(String(64))
    version_ids: Mapped[list[int]] = mapped_column(JSONB, server_default=text("'[]'"))
    reviewer: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())


class PipelineRun(Base):
    """One attempt to run one source (scheduled or manual), for monitoring."""

    __tablename__ = "pipeline_run"
    __table_args__ = (
        Index("ix_pipeline_run_started_at", "started_at"),
        Index("ix_pipeline_run_source_id_started_at", "source_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    started_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    finished_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    status: Mapped[str] = mapped_column(String(32))  # parsed | unchanged | *_failed
    error: Mapped[str | None] = mapped_column(Text)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshot.id"))
    new: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    changed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    removed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    review_task_id: Mapped[int | None] = mapped_column(ForeignKey("review_task.id"))
    trigger: Mapped[str] = mapped_column(String(16), server_default=text("'manual'"))


class Notification(Base):
    """Every message sent (or attempted) to the operator, e.g. via Telegram."""

    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_kind_sent_at", "kind", "sent_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # daily_summary | adapter_broken | adapter_recovered
    kind: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16))  # telegram | log
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id"))


class ChangeEvent(Base):
    """One changed field in a proposed version. Append-only (DB trigger)."""

    __tablename__ = "change_event"
    __table_args__ = (Index("ix_change_event_entity_entity_id", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity: Mapped[str] = mapped_column(String(64))  # table name, e.g. "savings_rate"
    entity_id: Mapped[int] = mapped_column(BigInteger)  # the proposed version's id
    field: Mapped[str] = mapped_column(String(64))
    # JSON keeps types; decimals are stored as strings so they stay exact.
    old_value: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshot.id"))
    detected_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())
    review_task_id: Mapped[int | None] = mapped_column(ForeignKey("review_task.id"), index=True)


# --------------------------------------------------------------------------- signals
# Community reports and news only trigger re-checks; they never publish a value.


class CommunityReport(Base):
    __tablename__ = "community_report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institution.id"))
    product_ref: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    evidence_storage_key: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)  # personal data: never publish
    status: Mapped[CommunityReportStatus] = mapped_column(
        str_enum(CommunityReportStatus, "status"),
        server_default=CommunityReportStatus.NEW.value,
    )
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())


news_item_institution = Table(
    "news_item_institution",
    Base.metadata,
    Column("news_item_id", ForeignKey("news_item.id", ondelete="CASCADE"), primary_key=True),
    Column("institution_id", ForeignKey("institution.id"), primary_key=True),
)


class NewsItem(Base):
    """One article from a news feed. News only triggers re-checks of the bank's own
    pages (CLAUDE.md principle 1): nothing here is ever published as a value."""

    __tablename__ = "news_item"
    __table_args__ = (Index("ix_news_item_title_key", "title_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feed: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    # Folded title (no accents, case or punctuation), to drop the same story twice.
    title_key: Mapped[str] = mapped_column(Text, server_default=text("''"))
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    # NULL until classified (e.g. ambiguous and the LLM is not configured yet).
    classification: Mapped[NewsClassification | None] = mapped_column(
        str_enum(NewsClassification, "classification")
    )
    about_rates: Mapped[bool | None] = mapped_column(Boolean)
    about_card_fees: Mapped[bool | None] = mapped_column(Boolean)
    direction: Mapped[NewsDirection | None] = mapped_column(
        str_enum(NewsDirection, "news_direction")
    )
    classified_by: Mapped[str | None] = mapped_column(String(16))  # keywords | llm
    classified_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    # The decision and its inputs: {about_rates, about_card_fees, institutions (the ones
    # whose rates/fees changed; re-check targets), direction, method, model}.
    classification_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    triggered_recheck: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # What the re-check did, per source: [{institution, source_id, status, review_task_id}]
    recheck_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime, server_default=func.now())

    # Institutions the item mentions (alias match on title + summary).
    institutions: Mapped[list[Institution]] = relationship(secondary=news_item_institution)


class NewsFetch(Base):
    """One attempt to read one configured feed (pipeline/news/feeds.yaml)."""

    __tablename__ = "news_fetch"
    __table_args__ = (Index("ix_news_fetch_feed_started_at", "feed", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feed: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    ok: Mapped[bool] = mapped_column(Boolean)
    items_seen: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_new: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)


VERSIONED_MODELS: tuple[type[Versioned], ...] = (
    SavingsRate,
    CardTerms,
    CardReward,
    CardPerk,
    CardInterest,
)
APPEND_ONLY_TABLES = ("snapshot", "change_event", "review_action")

__all__ = [
    "APPEND_ONLY_TABLES",
    "LIFECYCLE_COLUMNS",
    "PROVENANCE_COLUMNS",
    "VERSIONED_MODELS",
    "Base",
    "CardInterest",
    "CardPerk",
    "CardProduct",
    "CardReward",
    "CardTerms",
    "ChangeEvent",
    "CommunityReport",
    "Institution",
    "NewsFetch",
    "NewsItem",
    "Notification",
    "PipelineRun",
    "ReviewAction",
    "ReviewTask",
    "SavingsRate",
    "Snapshot",
    "Source",
    "Versioned",
    "news_item_institution",
]
