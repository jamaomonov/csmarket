"""payments: ix_payments_number with text_pattern_ops (prefix search under any collation)

The admin payments search matches ``number LIKE 'T7K%'``. A plain btree serves a prefix
``LIKE`` only under the C collation; ``text_pattern_ops`` serves it under any, and still
serves equality.

Revision ID: 0012_payments_number_pattern_ops
Revises: 0011_refresh_revoked_reason
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_payments_number_pattern_ops"
down_revision: str | None = "0011_refresh_revoked_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate the index with ``text_pattern_ops``."""
    op.drop_index("ix_payments_number", table_name="payments")
    op.create_index(
        "ix_payments_number",
        "payments",
        ["number"],
        postgresql_ops={"number": "text_pattern_ops"},
    )


def downgrade() -> None:
    """Back to the plain btree."""
    op.drop_index("ix_payments_number", table_name="payments")
    op.create_index("ix_payments_number", "payments", ["number"])
