"""Request and response shapes of ``articles`` (spec 2026-10-26-articles)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from csmarket.modules.articles.models import BODY_MAX, COVER_ALT_MAX, DESCRIPTION_MAX, TITLE_MAX


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
