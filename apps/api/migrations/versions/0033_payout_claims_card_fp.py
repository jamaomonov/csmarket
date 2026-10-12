"""sales: the payout claim, undo, and the card fingerprint

Admin review 2026-10-12 (H1, H3, M5): ``payout_requests.claimed_by`` / ``claimed_at`` hold
«Беру в работу» (a 15-minute lease); ``undo_count`` keys the ledger of a decision redone
after an undo; ``payout_cards.number_fp`` is an HMAC of the card number that finds the same
card on other accounts. The HMAC key is derived from ``CSMARKET_APP_ENC_KEY`` and never
reaches SQL, so existing cards are filled by ``python -m csmarket.scripts.backfill_card_fp``
after the deploy, not here.

Revision ID: 0033_payout_claims_card_fp
Revises: 0032_sale_flags_limits
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_payout_claims_card_fp"
down_revision: str | None = "0032_sale_flags_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    """Add the claim and undo columns and the card fingerprint."""
    op.add_column("payout_requests", sa.Column("claimed_by", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_payout_requests_claimed_by_users",
        "payout_requests",
        "users",
        ["claimed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "payout_requests", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "payout_requests",
        sa.Column("undo_count", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column("payout_cards", sa.Column("number_fp", sa.String(64), nullable=True))
    op.create_index("ix_payout_cards_number_fp", "payout_cards", ["number_fp"])


def downgrade() -> None:
    """Drop them again (claims and fingerprints are lost; the backfill can rebuild the latter)."""
    op.drop_index("ix_payout_cards_number_fp", table_name="payout_cards")
    op.drop_column("payout_cards", "number_fp")
    op.drop_column("payout_requests", "undo_count")
    op.drop_column("payout_requests", "claimed_at")
    op.drop_constraint("fk_payout_requests_claimed_by_users", "payout_requests", type_="foreignkey")
    op.drop_column("payout_requests", "claimed_by")
