"""sales: the bank's charge on a paid card payout

Spec 2026-10-13-sales-pnl: ``payout_requests.bank_fee_uzs`` is what the bank charged the
sender, written at «Выплачено» from ``bank_fee_pct``. Older paid rows stay null; the P&L uses
the current setting for them.

Revision ID: 0034_payout_bank_fee
Revises: 0033_payout_claims_card_fp
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_payout_bank_fee"
down_revision: str | None = "0033_payout_claims_card_fp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``payout_requests.bank_fee_uzs``."""
    op.add_column("payout_requests", sa.Column("bank_fee_uzs", sa.Numeric(14, 0), nullable=True))


def downgrade() -> None:
    """Drop it."""
    op.drop_column("payout_requests", "bank_fee_uzs")
