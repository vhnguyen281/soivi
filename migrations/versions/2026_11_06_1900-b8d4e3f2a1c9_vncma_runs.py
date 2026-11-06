"""VNCMA runs, adjustments and releases (append-only)

Revision ID: b8d4e3f2a1c9
Revises: a7c3d2e1f9b8
Create Date: 2026-11-06 19:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8d4e3f2a1c9"
down_revision: Union[str, Sequence[str], None] = "a7c3d2e1f9b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("cma_run", "cma_adjustment", "cma_release", "cma_release_value")


def upgrade() -> None:
    op.create_table(
        "cma_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("methodology_version", sa.String(32), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("inputs_sha256", sa.String(64), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "cma_adjustment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("cma_run.id"), nullable=False),
        sa.Column("asset_class", sa.String(32), nullable=False),
        sa.Column("delta_pp", sa.Numeric(5, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("author", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("abs(delta_pp) <= 1.0", name=op.f("ck_cma_adjustment_delta_within_1pp")),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name=op.f("ck_cma_adjustment_reason_required")
        ),
        sa.UniqueConstraint("run_id", "asset_class", name="uq_cma_adjustment_class"),
    )
    op.create_index(op.f("ix_cma_adjustment_run_id"), "cma_adjustment", ["run_id"])
    op.create_table(
        "cma_release",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("cma_run.id"), nullable=False),
        sa.Column("methodology_version", sa.String(32), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("note", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("version", name=op.f("uq_cma_release_version")),
        sa.UniqueConstraint("run_id", name=op.f("uq_cma_release_run_id")),
        sa.CheckConstraint(
            "length(trim(approved_by)) > 0", name=op.f("ck_cma_release_reviewer_required")
        ),
    )
    op.create_table(
        "cma_release_value",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("cma_release.id"), nullable=False),
        sa.Column("asset_class", sa.String(32), nullable=False),
        sa.Column("expected_return", sa.Numeric(6, 2), nullable=False),
        sa.Column("model_return", sa.Numeric(6, 2), nullable=False),
        sa.Column("adjustment_pp", sa.Numeric(5, 2), nullable=False),
        sa.Column("arithmetic_return", sa.Numeric(6, 2)),
        sa.Column("volatility", sa.Numeric(6, 2)),
        sa.Column("band_low", sa.Numeric(6, 2)),
        sa.Column("band_high", sa.Numeric(6, 2)),
        sa.Column("grade", sa.String(1), nullable=False),
        sa.UniqueConstraint("release_id", "asset_class", name="uq_cma_release_value_class"),
    )
    op.create_index(op.f("ix_cma_release_value_release_id"), "cma_release_value", ["release_id"])
    for table in TABLES:  # principles 3 and 4: runs and releases are never changed or deleted
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION soivi_guard_append_only()"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.drop_table(table)
