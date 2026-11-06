"""VNCMA model portfolios approved per release (append-only)

Revision ID: c9e5f4a3b2d1
Revises: b8d4e3f2a1c9
Create Date: 2026-11-07 09:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9e5f4a3b2d1"
down_revision: Union[str, Sequence[str], None] = "b8d4e3f2a1c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cma_portfolio_set",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("cma_release.id"), nullable=False),
        sa.Column("methodology_version", sa.String(32), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("release_id", name=op.f("uq_cma_portfolio_set_release_id")),
        sa.CheckConstraint(
            "length(trim(approved_by)) > 0", name=op.f("ck_cma_portfolio_set_reviewer_required")
        ),
    )
    op.execute(
        "CREATE TRIGGER cma_portfolio_set_append_only BEFORE UPDATE OR DELETE "
        "ON cma_portfolio_set FOR EACH ROW EXECUTE FUNCTION soivi_guard_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS cma_portfolio_set_append_only ON cma_portfolio_set")
    op.drop_table("cma_portfolio_set")
