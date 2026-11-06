"""VNCMA market data: market_series, market_observation (append-only), new source kind and fetch method

Revision ID: a7c3d2e1f9b8
Revises: c1a2e7d4b9f0
Create Date: 2026-11-06 15:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c3d2e1f9b8"
down_revision: Union[str, Sequence[str], None] = "c1a2e7d4b9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = ("savings_rate_page", "card_tariff_pdf", "card_product_page", "news_feed", "official")
METHODS = ("http", "browser", "pdf", "ocr")
FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "yearly")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _swap_check(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, f"{column} IN ({_in(values)})")


def upgrade() -> None:
    _swap_check("source", "ck_source_source_kind", "kind", (*KINDS, "market_data"))
    _swap_check("source", "ck_source_fetch_method", "fetch_method", (*METHODS, "api"))

    op.create_table(
        "market_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("asset_class", sa.String(32)),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("value_field", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("native_frequency", sa.String(9), nullable=False),
        sa.Column("period", sa.String(9), nullable=False),
        sa.Column("month_end_rule", sa.String(17), nullable=False),
        sa.Column("max_gap_days", sa.Integer()),
        sa.Column("grade", sa.String(1), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_snapshot_id", sa.BigInteger(), sa.ForeignKey("snapshot.id")),
        sa.UniqueConstraint("code", name=op.f("uq_market_series_code")),
        sa.CheckConstraint(
            f"native_frequency IN ({_in(FREQUENCIES)})", name=op.f("ck_market_series_frequency")
        ),
        sa.CheckConstraint(
            f"period IN ({_in(FREQUENCIES)})", name=op.f("ck_market_series_period_frequency")
        ),
        sa.CheckConstraint(
            "month_end_rule IN ('last_on_or_before', 'period_value')",
            name=op.f("ck_market_series_month_end_rule"),
        ),
        sa.CheckConstraint("grade IN ('A', 'B', 'C')", name=op.f("ck_market_series_data_grade")),
        sa.CheckConstraint(
            "max_gap_days IS NULL OR max_gap_days > 0",
            name=op.f("ck_market_series_max_gap_days_positive"),
        ),
        sa.CheckConstraint(
            "month_end_rule <> 'last_on_or_before' OR max_gap_days IS NOT NULL",
            name=op.f("ck_market_series_gap_for_last_on_or_before"),
        ),
    )
    op.create_index(op.f("ix_market_series_source_id"), "market_series", ["source_id"])

    op.create_table(
        "market_observation",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("market_series.id"), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("obs_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 8), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), sa.ForeignKey("snapshot.id"), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "series_id", "period_end", "revision", name="uq_market_observation_revision"
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_market_observation_revision_positive")),
        sa.CheckConstraint(
            "obs_date <= period_end", name=op.f("ck_market_observation_obs_date_in_period")
        ),
    )
    op.create_index(
        "ix_market_observation_snapshot_id", "market_observation", ["snapshot_id"]
    )
    # Principle 3: observations are never changed or deleted (function from the initial schema).
    op.execute(
        "CREATE TRIGGER market_observation_append_only BEFORE UPDATE OR DELETE "
        "ON market_observation FOR EACH ROW EXECUTE FUNCTION soivi_guard_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS market_observation_append_only ON market_observation")
    op.drop_table("market_observation")
    op.drop_table("market_series")
    op.execute("DELETE FROM source WHERE kind = 'market_data'")
    _swap_check("source", "ck_source_fetch_method", "fetch_method", METHODS)
    _swap_check("source", "ck_source_source_kind", "kind", KINDS)
