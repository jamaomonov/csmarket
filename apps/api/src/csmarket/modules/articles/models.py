"""SQLAlchemy ORM for ``articles`` (spec ``2026-10-26-articles-design.md``, ADR-0025).

- :class:`Article` — one article in one section, one slug for every language, a cover, counters.
- :class:`ArticleTranslation` — its text in one locale; *live* when the article is published and
  the translation is ready with a title and a body (:func:`live`).
- :class:`ArticleSlugOld` — a former slug of a published article, answered with a 301.
- :class:`ArticleMedia` — an uploaded image (bytes in the row, as payout receipts, ADR-0024).
- :class:`ArticleLike` — one like per signed-in user or per anonymous browser id.

Like keys (a user id, an anonymous id) are never logged; no IP is stored anywhere here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.db import Base
from csmarket.core.ids import new_id

SECTIONS = ("news", "guides", "tops")
LOCALES = ("ru", "uz", "en")
STATUSES = ("draft", "published")
TITLE_MAX = 120
DESCRIPTION_MAX = 200
COVER_ALT_MAX = 160
BODY_MAX = 60_000


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


def _admin_fk() -> Mapped[str | None]:
    """The admin who did it; kept as ``NULL`` if the account is ever erased."""
    return mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ArticleMedia(Base):
    """One uploaded image; the same bytes uploaded twice are one row (``hash``)."""

    __tablename__ = "article_media"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    #: SHA-256 of the bytes, hex; the public URL's name.
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    uploaded_by: Mapped[str | None] = _admin_fk()
    created_at: Mapped[datetime] = _ts()


class Article(Base):
    """One article: its section, slug, cover and counters; the words are translations."""

    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint(f"section IN {_in(SECTIONS)}", name="ck_articles_section"),
        CheckConstraint(f"status IN {_in(STATUSES)}", name="ck_articles_status"),
        Index("ix_articles_live", "status", "section", "published_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    section: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    cover_media_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("article_media.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    #: The first publication; set once, shown as the article's date.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The last edit of a ready translation of a published article («обновлено»).
    updated_at: Mapped[datetime] = _ts()
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = _admin_fk()
    updated_by: Mapped[str | None] = _admin_fk()
    created_at: Mapped[datetime] = _ts()


class ArticleTranslation(Base):
    """An article's words in one locale."""

    __tablename__ = "article_translations"
    __table_args__ = (CheckConstraint(f"locale IN {_in(LOCALES)}", name="ck_article_tr_locale"),)

    article_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(2), primary_key=True)
    title: Mapped[str] = mapped_column(String(TITLE_MAX), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(DESCRIPTION_MAX), nullable=False, default="")
    cover_alt: Mapped[str] = mapped_column(
        String(COVER_ALT_MAX), nullable=False, default="", server_default=""
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = _ts()


class ArticleSlugOld(Base):
    """A former slug of a published article; it 301s to the article's current one."""

    __tablename__ = "article_slugs_old"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    article_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )


class ArticleLike(Base):
    """One like: by a signed-in user or by an anonymous browser id, never both."""

    __tablename__ = "article_likes"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (anon_id IS NULL)", name="ck_article_likes_one_key"),
        UniqueConstraint("article_id", "user_id", name="uq_article_likes_user"),
        UniqueConstraint("article_id", "anon_id", name="uq_article_likes_anon"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    anon_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = _ts()


def live() -> ColumnElement[bool]:
    """A translation readers may see: the article published, the translation ready and whole."""
    return and_(
        Article.status == "published",
        ArticleTranslation.ready.is_(True),
        func.length(ArticleTranslation.title) > 0,
        func.length(ArticleTranslation.body) > 0,
    )


__all__ = [
    "BODY_MAX",
    "COVER_ALT_MAX",
    "DESCRIPTION_MAX",
    "LOCALES",
    "SECTIONS",
    "STATUSES",
    "TITLE_MAX",
    "Article",
    "ArticleLike",
    "ArticleMedia",
    "ArticleSlugOld",
    "ArticleTranslation",
    "live",
]
