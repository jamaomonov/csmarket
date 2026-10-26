"""Articles: news, guides and top lists in ru / uz / en, their images and likes (ADR-0025).

Revision ID: 0042_articles
Revises: 0041_payout_proofs
"""

from collections.abc import Sequence
from typing import Any  # Column[Any]: a column spec of any type

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_articles"
down_revision: str | None = "0041_payout_proofs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)


def _ts(name: str) -> sa.Column[Any]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _admin(name: str) -> sa.Column[Any]:
    return sa.Column(name, _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def upgrade() -> None:
    op.create_table(
        "article_media",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("hash", sa.String(64), nullable=False, unique=True),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        _admin("uploaded_by"),
        _ts("created_at"),
    )
    op.create_table(
        "articles",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column(
            "cover_media_id",
            _UUID,
            sa.ForeignKey("article_media.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _ts("updated_at"),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer, nullable=False, server_default="0"),
        _admin("created_by"),
        _admin("updated_by"),
        _ts("created_at"),
        sa.CheckConstraint("section IN ('news', 'guides', 'tops')", name="ck_articles_section"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_articles_status"),
    )
    op.create_index("ix_articles_live", "articles", ["status", "section", "published_at"])
    op.create_table(
        "article_translations",
        sa.Column(
            "article_id",
            _UUID,
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("locale", sa.String(2), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("cover_alt", sa.String(160), nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("ready", sa.Boolean, nullable=False),
        _ts("updated_at"),
        sa.CheckConstraint("locale IN ('ru', 'uz', 'en')", name="ck_article_tr_locale"),
    )
    op.create_table(
        "article_slugs_old",
        sa.Column("slug", sa.String(80), primary_key=True),
        sa.Column(
            "article_id", _UUID, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
        ),
    )
    op.create_table(
        "article_likes",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "article_id", _UUID, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("anon_id", _UUID, nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (anon_id IS NULL)", name="ck_article_likes_one_key"
        ),
        sa.UniqueConstraint("article_id", "user_id", name="uq_article_likes_user"),
        sa.UniqueConstraint("article_id", "anon_id", name="uq_article_likes_anon"),
    )


def downgrade() -> None:
    op.drop_table("article_likes")
    op.drop_table("article_slugs_old")
    op.drop_table("article_translations")
    op.drop_index("ix_articles_live", table_name="articles")
    op.drop_table("articles")
    op.drop_table("article_media")
