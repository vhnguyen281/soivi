"""Fund-group statistics: runs and approved releases (append-only)

Revision ID: d1a2b3c4e5f6
Revises: c9e5f4a3b2d1
Create Date: 2026-11-07 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a2b3c4e5f6"
down_revision: str | Sequence[str] | None = "c9e5f4a3b2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fund_stats_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column("inputs_sha256", sa.String(64), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "fund_stats_release",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("fund_stats_run.id"), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("run_id", name=op.f("uq_fund_stats_release_run_id")),
        sa.CheckConstraint(
            "length(trim(approved_by)) > 0", name=op.f("ck_fund_stats_release_reviewer_required")
        ),
    )
    for table in ("fund_stats_run", "fund_stats_release"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION soivi_guard_append_only()"
        )


def downgrade() -> None:
    for table in ("fund_stats_release", "fund_stats_run"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.drop_table(table)
