"""``/api/v1/articles*`` — what readers see (spec 2026-10-26-articles «API»).

Reads only and no sign-in. ``/articles/locales`` and ``/articles/sitemap`` are declared before
``/articles/{slug}`` and both words are refused as slugs (``slugs.RESERVED_SLUGS``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.articles import public
from csmarket.modules.articles.schemas import (
    ArticleLocalesOut,
    ArticleOut,
    ArticleRedirectOut,
    ArticleSitemapOut,
    ArticlesPageOut,
    Locale,
    Section,
)

router = APIRouter(prefix="/articles", tags=["articles"])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]


@router.get("", response_model=ArticlesPageOut, summary="Live articles")
async def get_articles(
    db: Db,
    locale: Locale = "ru",
    section: Section | None = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ArticlesPageOut:
    """Live articles in ``locale``, newest first, 12 a page; ``section`` filters."""
    return await public.list_live(db, locale=locale, section=section, cursor=cursor)


@router.get("/locales", response_model=ArticleLocalesOut, summary="Sections with articles")
async def get_locales(db: Db) -> ArticleLocalesOut:
    """Per locale, the sections that have at least one live article."""
    return await public.live_locales(db)


@router.get("/sitemap", response_model=ArticleSitemapOut, summary="Live translations")
async def get_sitemap(db: Db) -> ArticleSitemapOut:
    """Every live translation with its last change, for the storefront's sitemap."""
    return await public.sitemap(db)


@router.get(
    "/{slug}",
    response_model=ArticleOut | ArticleRedirectOut,
    responses={404: {"description": "`article_not_found`"}},
    summary="One article",
)
async def get_article(slug: str, db: Db, locale: Locale = "ru") -> ArticleOut | ArticleRedirectOut:
    """The live ``locale`` translation (``kind: article``), or ``kind: redirect`` with the
    current slug when ``slug`` is a former one; 404 when nothing is live in ``locale``."""
    return await public.read_live(db, slug, locale=locale)
