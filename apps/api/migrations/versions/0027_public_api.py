"""public API: api_keys, the API columns of orders

Revision ID: 0027_public_api
Revises: 0026_wallet_currency
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_public_api"
down_revision: str | None = "0026_wallet_currency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL_FIELDS = (
    "(channel = 'site' AND api_key_id IS NULL) OR (channel = 'api' AND api_key_id IS NOT NULL"
    " AND client_order_id IS NOT NULL AND pricing_profile IS NOT NULL)"
)


def upgrade() -> None:
    """Create ``api_keys``; add the channel columns, their checks and the unique id."""
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("pricing_profile", sa.String(8), nullable=False, server_default="retail"),
        sa.Column(
            "ip_allowlist",
            postgresql.ARRAY(sa.String(43)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_api_keys_token_hash"),
        sa.CheckConstraint("pricing_profile IN ('retail', 'cost')", name="pricing_profile"),
    )
    op.create_index(
        "uq_api_keys_live_user",
        "api_keys",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.add_column(
        "orders",
        sa.Column("channel", sa.String(4), nullable=False, server_default=sa.text("'site'")),
    )
    op.add_column(
        "orders",
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("api_keys.id", ondelete="RESTRICT", name="fk_orders_api_key_id_api_keys"),
            nullable=True,
        ),
    )
    op.add_column("orders", sa.Column("client_order_id", sa.String(64), nullable=True))
    op.add_column("orders", sa.Column("pricing_profile", sa.String(8), nullable=True))
    op.create_check_constraint("channel", "orders", "channel IN ('site', 'api')")
    op.create_check_constraint("channel_fields", "orders", _CHANNEL_FIELDS)
    op.create_unique_constraint(
        "uq_orders_api_key_id_client_order_id", "orders", ["api_key_id", "client_order_id"]
    )


def downgrade() -> None:
    """Drop the API columns and ``api_keys`` (API orders must be gone)."""
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM orders WHERE channel = 'api'")).scalar_one():
        raise RuntimeError("cannot downgrade: API orders exist")
    op.drop_constraint("uq_orders_api_key_id_client_order_id", "orders", type_="unique")
    op.drop_constraint("channel_fields", "orders", type_="check")
    op.drop_constraint("channel", "orders", type_="check")
    op.drop_column("orders", "pricing_profile")
    op.drop_column("orders", "client_order_id")
    op.drop_column("orders", "api_key_id")
    op.drop_column("orders", "channel")
    op.drop_index("uq_api_keys_live_user", table_name="api_keys")
    op.drop_table("api_keys")
