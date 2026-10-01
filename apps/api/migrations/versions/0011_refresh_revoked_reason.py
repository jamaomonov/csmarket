"""auth: refresh_tokens.revoked_reason (scope the reuse trip-wire to rotated tokens)

Revision ID: 0011_refresh_revoked_reason
Revises: 0010_uzum_transactions
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_refresh_revoked_reason"
down_revision: str | None = "0010_uzum_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable reason; existing revoked rows stay NULL (read as ``rotated``)."""
    op.add_column("refresh_tokens", sa.Column("revoked_reason", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f("ck_refresh_tokens_revoked_reason"),
        "refresh_tokens",
        "revoked_reason IN ('rotated', 'logout', 'admin', 'reuse')",
    )


def downgrade() -> None:
    """Drop the reason (and its check with it)."""
    op.drop_constraint(op.f("ck_refresh_tokens_revoked_reason"), "refresh_tokens", type_="check")
    op.drop_column("refresh_tokens", "revoked_reason")
