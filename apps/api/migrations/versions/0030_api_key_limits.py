"""public API v1.1: per-key limits

Revision ID: 0030_api_key_limits
Revises: 0029_api_webhooks
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_api_key_limits"
down_revision: str | None = "0029_api_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("read_per_min", "orders_per_min", "feed_per_min", "check_per_min")


def upgrade() -> None:
    """Add the four limit columns (NULL = the default) and their positivity checks."""
    for c in _COLUMNS:
        op.add_column("api_keys", sa.Column(c, sa.Integer, nullable=True))
        # Bare suffix: the metadata naming convention adds ``ck_api_keys_``.
        op.create_check_constraint(f"{c}_positive", "api_keys", f"{c} IS NULL OR {c} > 0")


def downgrade() -> None:
    """Drop the checks, then the columns."""
    for c in reversed(_COLUMNS):
        op.drop_constraint(f"{c}_positive", "api_keys", type_="check")
        op.drop_column("api_keys", c)
