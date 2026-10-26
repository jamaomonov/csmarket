"""What readers see: live translations only (spec 2026-10-26-articles «API»).

A translation is live when its article is published and it is ready with a title and a body
(:func:`csmarket.modules.articles.models.live`); anything else answers 404. Lists are newest
first by the first publication date. An article's ``[[skin:<slug>]]`` lines come back as catalogue
cards in ``embeds`` so the page renders from one request.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import cast

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import NotFoundError, ValidationError
from csmarket.modules.articles.media import media_out
from csmarket.modules.articles.models import (
    LOCALES,
    Article,
    ArticleMedia,
    ArticleTranslation,
    live,
)
from csmarket.modules.articles.schemas import (
    ArticleCardOut,
    ArticleLocalesOut,
    ArticleOut,
    ArticleRedirectOut,
    ArticleSitemapOut,
    ArticlesPageOut,
    Locale,
    Section,
    SitemapEntryOut,
)
from csmarket.modules.articles.slugs import resolve_slug
from csmarket.modules.skins.api import item_cards

PAGE = 12
RELATED = 3
#: The most skin cards one article may show.
MAX_EMBEDS = 50
_EMBED = re.compile(r"^\[\[skin:([a-z0-9-]+)\]\]$", re.MULTILINE)

_Row = tuple[Article, ArticleTranslation, ArticleMedia]


def _live(locale: str) -> Select[Article, ArticleTranslation, ArticleMedia]:
    return (
        select(Article, ArticleTranslation, ArticleMedia)
        .join(ArticleTranslation, ArticleTranslation.article_id == Article.id)
        .join(ArticleMedia, ArticleMedia.id == Article.cover_media_id)
        .where(ArticleTranslation.locale == locale, live())
    )


def _card(row: _Row) -> ArticleCardOut:
    article, tr, cover = row
    assert article.published_at is not None  # published articles always have one
    return ArticleCardOut(
        slug=article.slug,
        section=cast("Section", article.section),
        title=tr.title,
        description=tr.description,
        cover=media_out(cover),
        cover_alt=tr.cover_alt,
        published_at=article.published_at,
        views=article.views,
        likes=article.likes,
    )


def _encode(article: Article) -> str:
    assert article.published_at is not None
    raw = f"{article.published_at.isoformat()}|{article.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode(cursor: str) -> tuple[datetime, str]:
    try:
        at, article_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(at), article_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("invalid cursor") from exc


async def list_live(
    db: AsyncSession, *, locale: Locale, section: Section | None, cursor: str | None
) -> ArticlesPageOut:
    """A page of live articles in ``locale``, newest first."""
    query = _live(locale).order_by(Article.published_at.desc(), Article.id.desc()).limit(PAGE + 1)
    if section is not None:
        query = query.where(Article.section == section)
    if cursor is not None:
        at, article_id = _decode(cursor)
        query = query.where(
            or_(
                Article.published_at < at,
                and_(Article.published_at == at, Article.id < article_id),
            )
        )
    rows = [cast("_Row", tuple(r)) for r in await db.execute(query)]
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    return ArticlesPageOut(
        items=[_card(r) for r in rows],
        next_cursor=_encode(rows[-1][0]) if more and rows else None,
    )


def embed_slugs(body: str) -> list[str]:
    """The ``[[skin:<slug>]]`` lines of ``body``, in order, each once, at most :data:`MAX_EMBEDS`."""
    seen: dict[str, None] = {}
    for m in _EMBED.finditer(body):
        seen.setdefault(m.group(1), None)
    return list(seen)[:MAX_EMBEDS]


async def _locales_of(db: AsyncSession, article_id: str) -> list[Locale]:
    found = set(
        await db.scalars(
            select(ArticleTranslation.locale)
            .join(Article, Article.id == ArticleTranslation.article_id)
            .where(Article.id == article_id, live())
        )
    )
    return [cast("Locale", loc) for loc in LOCALES if loc in found]


async def read_live(
    db: AsyncSession, slug: str, *, locale: Locale
) -> ArticleOut | ArticleRedirectOut:
    """The live ``locale`` translation of the article at ``slug``, or a redirect for a former slug.

    Raises:
        NotFoundError: ``article_not_found`` — no such slug, or nothing live in ``locale``.
    """
    found = await resolve_slug(db, slug)
    if found is not None and found[1]:
        return ArticleRedirectOut(slug=found[0].slug)
    row = (
        (await db.execute(_live(locale).where(Article.slug == slug))).one_or_none()
        if found is not None
        else None
    )
    if row is None:
        raise NotFoundError("no such article", code="article_not_found")
    article, tr, _ = row
    related = await db.execute(
        _live(locale)
        .where(Article.section == article.section, Article.id != article.id)
        .order_by(Article.published_at.desc(), Article.id.desc())
        .limit(RELATED)
    )
    card = _card(row)
    return ArticleOut(
        **card.model_dump(),
        body=tr.body,
        updated_at=max(article.updated_at, card.published_at),
        locales=await _locales_of(db, article.id),
        embeds=await item_cards(db, embed_slugs(tr.body)),
        related=[_card(cast("_Row", tuple(r))) for r in related],
    )


async def live_locales(db: AsyncSession) -> ArticleLocalesOut:
    """The sections with a live article, per locale (the header link, tabs, noindex)."""
    pairs = await db.execute(
        select(ArticleTranslation.locale, Article.section)
        .join(Article, Article.id == ArticleTranslation.article_id)
        .where(live(), Article.cover_media_id.is_not(None))
        .distinct()
    )
    by_locale: dict[str, set[str]] = {loc: set() for loc in LOCALES}
    for locale, section in pairs:
        by_locale[locale].add(section)
    order = ("news", "guides", "tops")
    return ArticleLocalesOut(
        **{
            loc: [cast("Section", s) for s in order if s in sections]
            for loc, sections in by_locale.items()
        }
    )


async def sitemap(db: AsyncSession) -> ArticleSitemapOut:
    """Every live translation with its last change."""
    rows = await db.execute(
        select(
            Article.slug,
            ArticleTranslation.locale,
            func.greatest(Article.updated_at, Article.published_at),
        )
        .join(Article, Article.id == ArticleTranslation.article_id)
        .where(live(), Article.cover_media_id.is_not(None))
        .order_by(Article.published_at.desc(), ArticleTranslation.locale)
    )
    return ArticleSitemapOut(
        items=[
            SitemapEntryOut(slug=slug, locale=cast("Locale", locale), updated_at=at)
            for slug, locale, at in rows
        ]
    )
