"""Reviews: one per deal, the prompt answers, the public-page switch.

Revision ID: 0040_reviews
Revises: 0039_payment_risk
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_reviews"
down_revision: str | None = "0039_payment_risk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")
_KIND = "kind IN ('market', 'sale')"
_ONE_DEAL = "(order_id IS NULL) <> (sale_id IS NULL)"
_KIND_DEAL = "(kind = 'market') = (order_id IS NOT NULL)"


def _deal_columns() -> list[sa.Column[str]]:
    return [
        sa.Column(
            "order_id", _UUID, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("sale_id", _UUID, sa.ForeignKey("sales.id", ondelete="RESTRICT"), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        *_deal_columns(),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolved_at", _TS, nullable=True),
        sa.Column(
            "resolved_by", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("resolved_note", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("order_id", name="uq_reviews_order_id"),
        sa.UniqueConstraint("sale_id", name="uq_reviews_sale_id"),
        sa.CheckConstraint(_KIND, name="kind"),
        sa.CheckConstraint("locale IN ('ru', 'uz', 'en')", name="locale"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),
        sa.CheckConstraint("text IS NULL OR char_length(text) BETWEEN 1 AND 1000", name="text_len"),
        sa.CheckConstraint(_ONE_DEAL, name="one_deal"),
        sa.CheckConstraint(_KIND_DEAL, name="kind_deal"),
    )
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"])
    op.create_index("ix_reviews_user_id", "reviews", ["user_id"])
    op.create_index(
        "ix_reviews_bad_open",
        "reviews",
        ["created_at"],
        postgresql_where=sa.text("rating <= 3 AND resolved_at IS NULL"),
    )
    op.create_index(
        "ix_reviews_published",
        "reviews",
        ["created_at"],
        postgresql_where=sa.text("rating >= 4 AND NOT hidden"),
    )
    op.create_table(
        "review_prompts",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        *_deal_columns(),
        sa.Column("snoozed_until", _TS, nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("order_id", name="uq_review_prompts_order_id"),
        sa.UniqueConstraint("sale_id", name="uq_review_prompts_sale_id"),
        sa.CheckConstraint(_KIND, name="kind"),
        sa.CheckConstraint(_ONE_DEAL, name="one_deal"),
        sa.CheckConstraint(_KIND_DEAL, name="kind_deal"),
    )
    op.create_index("ix_review_prompts_user_id", "review_prompts", ["user_id"])
    op.create_table(
        "review_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reviews_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_by", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("id = 1", name="singleton"),
    )


def downgrade() -> None:
    op.drop_table("review_settings")
    op.drop_table("review_prompts")
    op.drop_table("reviews")
