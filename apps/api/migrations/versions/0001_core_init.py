"""core: extensions + idempotent_responses

Revision ID: 0001_core_init
Revises:
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Trusted extensions since PG 13 — a non-superuser with CREATE on the database
# may install them, so this works both in testcontainers and on prod where
# infra/postgres/init/01-extensions.sql has already created them (IF NOT EXISTS
# is then a no-op).
_EXTENSIONS = ("pgcrypto", "citext", "pg_trgm", "btree_gin")


def upgrade() -> None:
    for ext in _EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
    op.create_table(
        "idempotent_responses",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("scope", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotent_responses_scope_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotent_responses")
