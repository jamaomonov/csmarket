"""users + refresh_tokens

Revision ID: 0002_users_auth
Revises: 0001_core_init
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_users_auth"
down_revision: str | None = "0001_core_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("steam_id", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locale", sa.String(2), nullable=False, server_default="ru"),
        sa.Column("trade_link", sa.Text(), nullable=True),
        sa.Column("trade_link_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trade_link_verdict", sa.String(8), nullable=True),
        sa.Column("trade_link_reason", sa.String(16), nullable=True),
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ban_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # Bare suffixes: the metadata naming convention adds the ``ck_users_`` prefix.
        sa.CheckConstraint("locale IN ('ru', 'uz', 'en')", name="locale"),
        sa.CheckConstraint(
            "trade_link_verdict IS NULL OR trade_link_verdict IN ('ok', 'warn', 'bad')",
            name="trade_link_verdict",
        ),
        sa.CheckConstraint(
            "trade_link_reason IS NULL OR trade_link_reason IN "
            "('invalid', 'private', 'trade_ban', 'hold', 'unavailable')",
            name="trade_link_reason",
        ),
        sa.UniqueConstraint("steam_id", name="uq_users_steam_id"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index("ix_refresh_tokens_revoked_at", "refresh_tokens", ["revoked_at"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("users")
