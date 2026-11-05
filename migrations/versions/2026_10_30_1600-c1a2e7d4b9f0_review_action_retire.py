"""review_action: allow the 'retire' action

Revision ID: c1a2e7d4b9f0
Revises: d8f039b33d53
Create Date: 2026-10-30 16:00:00

"""

from typing import Sequence, Union

from alembic import op

revision: str = "c1a2e7d4b9f0"
down_revision: Union[str, Sequence[str], None] = "d8f039b33d53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = ("approve", "reject", "approve_all", "reject_all", "needs_fix")
AFTER = (*BEFORE, "retire")


def _check(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_review_action_action"), "review_action", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(
        op.f("ck_review_action_action"), "review_action", f"action IN ({listed})"
    )


def upgrade() -> None:
    _check(AFTER)


def downgrade() -> None:
    _check(BEFORE)
