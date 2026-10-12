"""sales: resolvable attentions, the sell block, indices for the limits

Review 2026-10-11 (SB-2, SB-6): an admin marks a sale's attention checked
(``resolved_at`` / ``resolved_by`` / ``resolved_note``); ``sale_blocks`` holds the users an
admin stopped from selling; ``ix_sales_created_at`` serves the daily USD limits and the poll
of recently closed sales; ``ix_sales_attention_open`` the open-attention gauge and filter.

Revision ID: 0032_sale_flags_limits
Revises: 0031_skin_lore
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_sale_flags_limits"
down_revision: str | None = "0031_skin_lore"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    """Add the resolution columns, the indices and ``sale_blocks``."""
    op.add_column("sales", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sales", sa.Column("resolved_by", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_sales_resolved_by_users", "sales", "users", ["resolved_by"], ["id"], ondelete="SET NULL"
    )
    op.add_column("sales", sa.Column("resolved_note", sa.Text(), nullable=True))
    op.create_index("ix_sales_created_at", "sales", ["created_at"])
    op.create_index(
        "ix_sales_attention_open",
        "sales",
        ["attention_reason"],
        postgresql_where=sa.text("attention_reason IS NOT NULL AND resolved_at IS NULL"),
    )
    op.create_table(
        "sale_blocks",
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("blocked_by", _UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_sale_blocks"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sale_blocks_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["blocked_by"],
            ["users.id"],
            name="fk_sale_blocks_blocked_by_users",
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    """Drop them again (resolutions and blocks are lost)."""
    op.drop_table("sale_blocks")
    op.drop_index("ix_sales_attention_open", table_name="sales")
    op.drop_index("ix_sales_created_at", table_name="sales")
    op.drop_column("sales", "resolved_note")
    op.drop_constraint("fk_sales_resolved_by_users", "sales", type_="foreignkey")
    op.drop_column("sales", "resolved_by")
    op.drop_column("sales", "resolved_at")
