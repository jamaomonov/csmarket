"""notifications: email_outbox — letters waiting for the worker's emails queue

One row per letter (M4b ruling R5): order letters unique per order and kind, a partial
index on the claimable rows, and one on a user's letters of a kind (the latest ``verify``).

Revision ID: 0015_email_outbox
Revises: 0014_payments_order_id_idx
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_email_outbox"
down_revision: str | None = "0014_payments_order_id_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    """Create ``email_outbox`` and its indexes."""
    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("address", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(8), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        _ts("next_attempt_at"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(64), nullable=True),
        sa.Column("last_error_code", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("kind IN ('receipt', 'trade_sent', 'refunded', 'verify')", name="kind"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'skipped', 'failed')", name="status"),
    )
    op.create_index(
        "uq_email_outbox_order_kind",
        "email_outbox",
        ["order_id", "kind"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )
    op.create_index(
        "ix_email_outbox_claimable",
        "email_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_email_outbox_user_kind",
        "email_outbox",
        ["user_id", "kind", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Drop ``email_outbox``."""
    op.drop_table("email_outbox")
