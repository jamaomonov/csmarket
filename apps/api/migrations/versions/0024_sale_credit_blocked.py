"""sales: ``credit_blocked`` joins the attention reasons

A balance sale whose credit the wallet refuses (a frozen account) stays in ``hold`` flagged
``credit_blocked`` until the next poll can credit it.

Revision ID: 0024_sale_credit_blocked
Revises: 0023_sales
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_sale_credit_blocked"
down_revision: str | None = "0023_sales"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "attention_reason IS NULL OR attention_reason IN ('rolled_back', 'late_deposit')"
_NEW = (
    "attention_reason IS NULL OR attention_reason IN "
    "('rolled_back', 'late_deposit', 'credit_blocked')"
)


def upgrade() -> None:
    """Widen the attention-reason check."""
    op.drop_constraint("attention_reason", "sales", type_="check")
    op.create_check_constraint("attention_reason", "sales", _NEW)


def downgrade() -> None:
    """Narrow it back (no ``credit_blocked`` row may remain)."""
    op.drop_constraint("attention_reason", "sales", type_="check")
    op.create_check_constraint("attention_reason", "sales", _OLD)
