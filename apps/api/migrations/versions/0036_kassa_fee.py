"""payments: the kassa fee the buyer pays on top

Spec 2026-10-14-kassa-fee: ``payment_settings`` (row 1, a percent per kassa an admin edits) and,
on every attempt, the frozen ``fee_pct`` and the ``fee_uzs`` added to ``amount_uzs``. Existing
attempts carry no fee.

Revision ID: 0036_kassa_fee
Revises: 0035_skin_colors
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_kassa_fee"
down_revision: str | None = "0035_skin_colors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``payment_settings`` and ``payments.fee_pct`` / ``fee_uzs``."""
    op.create_table(
        "payment_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.add_column(
        "payments", sa.Column("fee_pct", sa.Numeric(4, 2), nullable=False, server_default="0")
    )
    op.add_column(
        "payments", sa.Column("fee_uzs", sa.Numeric(14, 0), nullable=False, server_default="0")
    )
    op.create_check_constraint("fee_non_negative", "payments", "fee_uzs >= 0")


def downgrade() -> None:
    """Drop them."""
    op.drop_constraint("fee_non_negative", "payments", type_="check")
    op.drop_column("payments", "fee_uzs")
    op.drop_column("payments", "fee_pct")
    op.drop_table("payment_settings")
