"""Card pictures from the banks' card pages, and reviewer decisions (append-only)

Revision ID: e2b3c4d5f6a7
Revises: d1a2b3c4e5f6
Create Date: 2026-11-07 18:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2b3c4d5f6a7"
down_revision: Union[str, Sequence[str], None] = "d1a2b3c4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_image",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_product_id", sa.Integer(), sa.ForeignKey("card_product.id"), nullable=False
        ),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("card_product_id", "sha256", name=op.f("uq_card_image_card_sha256")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_card_image_sha256_hex")),
    )
    op.create_index(op.f("ix_card_image_card_product_id"), "card_image", ["card_product_id"])
    op.create_table(
        "card_image_decision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_image_id", sa.Integer(), sa.ForeignKey("card_image.id"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(128), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name=op.f("ck_card_image_decision_decision_known"),
        ),
        sa.CheckConstraint(
            "length(trim(reviewer)) > 0", name=op.f("ck_card_image_decision_reviewer_required")
        ),
    )
    op.create_index(
        op.f("ix_card_image_decision_card_image_id"), "card_image_decision", ["card_image_id"]
    )
    for table in ("card_image", "card_image_decision"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION soivi_guard_append_only()"
        )


def downgrade() -> None:
    for table in ("card_image_decision", "card_image"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.drop_table(table)
