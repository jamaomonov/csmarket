"""The admin's «Статьи»: create, edit, publish and unpublish (spec 2026-10-26-articles).

Every write locks the article row first. Publishing needs a cover and at least one ready
translation (ready, with a title and a body); the first publication date is set once and kept
through an unpublish. An edit of a published article's translation moves ``updated_at``
(«обновлено» on the site). Nothing is ever deleted.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.modules.articles.media import media_out
from csmarket.modules.articles.models import LOCALES, Article, ArticleMedia, ArticleTranslation
from csmarket.modules.articles.schemas import (
    AdminArticleOut,
    AdminArticleRow,
    AdminArticlesOut,
    ArticleIn,
    ArticlePatch,
    Locale,
    Section,
    Status,
    TranslationIn,
    TranslationOut,
)
from csmarket.modules.articles.slugs import set_slug, validate_slug


# The CHECK constraints hold these columns to their literals; the casts only tell mypy.
def _section(v: str) -> Section:
    return cast("Section", v)


def _status(v: str) -> Status:
    return cast("Status", v)


def _locales() -> tuple[Locale, ...]:
    return cast("tuple[Locale, ...]", LOCALES)


def is_ready(t: ArticleTranslation) -> bool:
    """Whether readers may see this translation once the article is published."""
    return t.ready and bool(t.title) and bool(t.body)


async def find(db: AsyncSession, article_id: str) -> Article:
    """The article.

    Raises:
        NotFoundError: ``article_not_found``.
    """
    article = await db.get(Article, article_id)
    if article is None:
        raise NotFoundError("no such article", code="article_not_found")
    return article


async def _locked(db: AsyncSession, article_id: str) -> Article:
    article = await db.scalar(select(Article).where(Article.id == article_id).with_for_update())
    if article is None:
        raise NotFoundError("no such article", code="article_not_found")
    return article


async def _translations(db: AsyncSession, article_id: str) -> dict[str, ArticleTranslation]:
    rows = await db.scalars(
        select(ArticleTranslation).where(ArticleTranslation.article_id == article_id)
    )
    return {t.locale: t for t in rows}


async def _cover_id(db: AsyncSession, cover_hash: str) -> str:
    media_id = await db.scalar(select(ArticleMedia.id).where(ArticleMedia.hash == cover_hash))
    if media_id is None:
        raise ValidationError("upload the cover first", code="cover_not_found")
    return media_id


async def _save_translations(
    db: AsyncSession, article: Article, given: dict[Locale, TranslationIn]
) -> None:
    saved = await _translations(db, article.id)
    at = now()
    for locale, body in given.items():
        row = saved.get(locale)
        if row is None:
            row = ArticleTranslation(article_id=article.id, locale=locale)
            db.add(row)
        changed = any(getattr(row, k, None) != v for k, v in body.model_dump().items())
        for k, v in body.model_dump().items():
            setattr(row, k, v)
        if changed:
            row.updated_at = at
            if article.status == "published":
                article.updated_at = at
    await db.flush()


async def create_article(db: AsyncSession, body: ArticleIn, *, by: str) -> Article:
    """A new draft.

    Raises:
        ValidationError: ``slug_invalid`` or ``cover_not_found``.
        ConflictError: ``slug_taken``.
    """
    article = Article(
        section=body.section,
        slug="",
        status="draft",
        cover_media_id=await _cover_id(db, body.cover_hash) if body.cover_hash else None,
        created_by=by,
        updated_by=by,
    )
    validate_slug(body.slug)
    db.add(article)
    await db.flush()
    await set_slug(db, article, body.slug)
    await _save_translations(db, article, body.translations)
    return article


async def update_article(
    db: AsyncSession, article_id: str, body: ArticlePatch, *, by: str
) -> Article:
    """Change what ``body`` gives.

    Raises:
        NotFoundError: ``article_not_found``.
        ValidationError: ``slug_invalid`` or ``cover_not_found``.
        ConflictError: ``slug_taken``.
    """
    article = await _locked(db, article_id)
    if body.section is not None:
        article.section = body.section
    if body.cover_hash is not None:
        article.cover_media_id = await _cover_id(db, body.cover_hash)
    if body.slug is not None:
        await set_slug(db, article, body.slug)
    await _save_translations(db, article, body.translations)
    article.updated_by = by
    await db.flush()
    return article


async def publish(db: AsyncSession, article_id: str, *, by: str) -> Article:
    """Show the article's ready translations to readers.

    Raises:
        NotFoundError: ``article_not_found``.
        ConflictError: ``publish_needs_cover`` or ``publish_needs_translation``.
    """
    article = await _locked(db, article_id)
    if article.cover_media_id is None:
        raise ConflictError("add a cover first", code="publish_needs_cover")
    if not any(is_ready(t) for t in (await _translations(db, article.id)).values()):
        raise ConflictError("mark at least one translation ready", code="publish_needs_translation")
    article.status = "published"
    if article.published_at is None:
        article.published_at = now()
    article.updated_by = by
    await db.flush()
    return article


async def unpublish(db: AsyncSession, article_id: str, *, by: str) -> Article:
    """Hide the article from readers; it keeps its first publication date.

    Raises:
        NotFoundError: ``article_not_found``.
    """
    article = await _locked(db, article_id)
    article.status = "draft"
    article.updated_by = by
    await db.flush()
    return article


def _live_locales(article: Article, translations: dict[str, ArticleTranslation]) -> list[Locale]:
    if article.status != "published":
        return []
    return [loc for loc in _locales() if (t := translations.get(loc)) is not None and is_ready(t)]


async def article_out(db: AsyncSession, article: Article) -> AdminArticleOut:
    """The article as the editor shows it."""
    await db.refresh(article)
    translations = await _translations(db, article.id)
    cover = await db.get(ArticleMedia, article.cover_media_id) if article.cover_media_id else None
    return AdminArticleOut(
        id=article.id,
        section=_section(article.section),
        slug=article.slug,
        status=_status(article.status),
        cover=media_out(cover) if cover else None,
        translations={
            loc: TranslationOut.model_validate(t, from_attributes=True)
            if (t := translations.get(loc)) is not None
            else None
            for loc in _locales()
        },
        live_locales=_live_locales(article, translations),
        views=article.views,
        likes=article.likes,
        published_at=article.published_at,
        updated_at=article.updated_at,
        created_at=article.created_at,
    )


async def list_articles(
    db: AsyncSession, *, section: Section | None = None, status: Status | None = None
) -> AdminArticlesOut:
    """Every article, last edited first, with its title in ru (else the first written)."""
    query = select(Article).order_by(Article.updated_at.desc(), Article.id)
    if section is not None:
        query = query.where(Article.section == section)
    if status is not None:
        query = query.where(Article.status == status)
    articles = list(await db.scalars(query))
    by_article: dict[str, dict[str, ArticleTranslation]] = {a.id: {} for a in articles}
    if articles:
        rows = await db.scalars(
            select(ArticleTranslation).where(ArticleTranslation.article_id.in_(list(by_article)))
        )
        for t in rows:
            by_article[t.article_id][t.locale] = t
    items = []
    for a in articles:
        tr = by_article[a.id]
        title = next((tr[loc].title for loc in LOCALES if loc in tr and tr[loc].title), "")
        items.append(
            AdminArticleRow(
                id=a.id,
                section=_section(a.section),
                slug=a.slug,
                status=_status(a.status),
                title=title,
                live_locales=_live_locales(a, tr),
                views=a.views,
                likes=a.likes,
                published_at=a.published_at,
                updated_at=a.updated_at,
            )
        )
    return AdminArticlesOut(items=items)
