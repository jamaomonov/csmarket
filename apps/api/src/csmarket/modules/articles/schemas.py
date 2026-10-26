"""Request and response shapes of ``articles`` (spec 2026-10-26-articles)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from csmarket.modules.articles.models import BODY_MAX, COVER_ALT_MAX, DESCRIPTION_MAX, TITLE_MAX
from csmarket.modules.skins.api import SkinItemOut


class MediaOut(BaseModel):
    """An uploaded image. ``url`` is the relative path Markdown stores (``/media/<hash>.<ext>``)."""

    hash: str
    url: str
    width: int
    height: int
    content_type: str


Section = Literal["news", "guides", "tops"]
Locale = Literal["ru", "uz", "en"]
Status = Literal["draft", "published"]


class TranslationIn(BaseModel):
    """An article's words in one locale, as the admin saves them."""

    title: str = Field(default="", max_length=TITLE_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    cover_alt: str = Field(default="", max_length=COVER_ALT_MAX)
    body: str = Field(default="", max_length=BODY_MAX)
    ready: bool = False

    @field_validator("title", "description", "cover_alt", "body", mode="after")
    @classmethod
    def _strip(cls, v: str) -> str:
        """Blank is empty: a title of spaces is no title."""
        return v.strip()


class TranslationOut(TranslationIn):
    """A saved translation."""

    updated_at: datetime


class ArticleIn(BaseModel):
    """A new article. ``translations`` holds only the locales written so far."""

    section: Section
    slug: str = Field(max_length=80)
    cover_hash: str | None = Field(default=None, max_length=64)
    translations: dict[Locale, TranslationIn] = Field(default_factory=dict)


class ArticlePatch(BaseModel):
    """An edit: only what is given changes; a given locale's translation is replaced whole."""

    section: Section | None = None
    slug: str | None = Field(default=None, max_length=80)
    cover_hash: str | None = Field(default=None, max_length=64)
    translations: dict[Locale, TranslationIn] = Field(default_factory=dict)


class AdminArticleOut(BaseModel):
    """One article in the admin's editor."""

    id: str
    section: Section
    slug: str
    status: Status
    cover: MediaOut | None
    translations: dict[Locale, TranslationOut | None]
    live_locales: list[Locale]
    views: int
    likes: int
    published_at: datetime | None
    updated_at: datetime
    created_at: datetime


class AdminArticleRow(BaseModel):
    """One line of the admin's list."""

    id: str
    section: Section
    slug: str
    status: Status
    title: str
    live_locales: list[Locale]
    views: int
    likes: int
    published_at: datetime | None
    updated_at: datetime


class AdminArticlesOut(BaseModel):
    """The admin's list, last edited first."""

    items: list[AdminArticleRow]


class ArticleCardOut(BaseModel):
    """One article in a list."""

    slug: str
    section: Section
    title: str
    description: str
    cover: MediaOut
    cover_alt: str
    published_at: datetime
    views: int
    likes: int


class ArticlesPageOut(BaseModel):
    """A page of live articles, newest first, and the cursor for the next (``None`` on the last)."""

    items: list[ArticleCardOut]
    next_cursor: str | None


class ArticleOut(ArticleCardOut):
    """One live translation of an article."""

    kind: Literal["article"] = "article"
    body: str
    updated_at: datetime
    #: The locales with a live translation of this article.
    locales: list[Locale]
    #: The skin cards behind its ``[[skin:<slug>]]`` lines; a slug missing here is not shown.
    embeds: dict[str, SkinItemOut]
    related: list[ArticleCardOut]


class ArticleRedirectOut(BaseModel):
    """A former slug: the storefront answers a 301 to ``slug``."""

    kind: Literal["redirect"] = "redirect"
    slug: str


class ArticleLocalesOut(BaseModel):
    """The sections with at least one live article, per locale."""

    ru: list[Section]
    uz: list[Section]
    en: list[Section]


class SitemapEntryOut(BaseModel):
    """One live translation for the sitemap."""

    slug: str
    locale: Locale
    updated_at: datetime


class ArticleSitemapOut(BaseModel):
    """Every live translation."""

    items: list[SitemapEntryOut]


class LikeOut(BaseModel):
    """The article's likes after a like or unlike, and whether this reader likes it."""

    likes: int
    liked: bool


class ArticleMeOut(LikeOut):
    """The live counters for this reader (the article page itself stays cached)."""

    views: int
