"""admin_audit_log: one row per admin action

Revision ID: 0005_admin_audit_log
Revises: 0004_fx_snapshots
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_admin_audit_log"
down_revision: str | None = "0004_fx_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])
    op.create_index("ix_admin_audit_log_target", "admin_audit_log", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_target", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
