"""public API webhooks: api_webhooks, api_webhook_deliveries

Revision ID: 0029_api_webhooks
Revises: 0028_public_api_orders
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_api_webhooks"
down_revision: str | None = "0028_public_api_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTS = "'order.paid', 'order.trade_sent', 'order.delivered', 'order.refunded'"


def _now() -> sa.TextClause:
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    """Create the webhook URL table and the delivery queue."""
    op.create_table(
        "api_webhooks",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_table(
        "api_webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.SmallInteger, nullable=True),
        sa.Column("last_error", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.UniqueConstraint("order_id", "event", name="uq_api_webhook_deliveries_order_id_event"),
        sa.CheckConstraint(f"event IN ({_EVENTS})", name="event"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status"),
    )
    op.create_index(
        "ix_api_webhook_deliveries_pending",
        "api_webhook_deliveries",
        ["status", "next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Drop the delivery queue and the webhook URLs."""
    op.drop_index("ix_api_webhook_deliveries_pending", table_name="api_webhook_deliveries")
    op.drop_table("api_webhook_deliveries")
    op.drop_table("api_webhooks")
