"""Payout proofs: up to three receipts an admin attaches to a paid payout (ADR-0024).

Revision ID: 0041_payout_proofs
Revises: 0040_reviews
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_payout_proofs"
down_revision: str | None = "0040_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "payout_proofs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "request_id",
            _UUID,
            sa.ForeignKey("payout_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column(
            "uploaded_by", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_payout_proofs_request_id", "payout_proofs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_payout_proofs_request_id", table_name="payout_proofs")
    op.drop_table("payout_proofs")
