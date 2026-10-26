"""Article slugs: one per article for every language, with a 301 from every former one.

A slug is ``[a-z0-9]`` words joined by single dashes, 3–80 characters, never a section word
(``/articles/news`` is the «Новости» list). It is unique across current and former slugs, so a
former slug always leads to the one article that had it. Renaming a published article keeps
the old slug as a redirect; renaming a never-published draft keeps nothing.
"""

from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.articles.models import SECTIONS, Article, ArticleSlugOld

#: Section words (the storefront serves the section lists at ``/articles/<section>``) and the
#: API's own ``/articles/locales`` and ``/articles/sitemap``.
RESERVED_SLUGS = frozenset((*SECTIONS, "locales", "sitemap"))
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def validate_slug(slug: str) -> str:
    """``slug`` when it is a valid article slug.

    Raises:
        ValidationError: ``slug_invalid``.
    """
    if not 3 <= len(slug) <= 80 or not _SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        raise ValidationError(
            "3–80 latin lowercase letters, digits and single dashes", code="slug_invalid"
        )
    return slug


async def resolve_slug(db: AsyncSession, slug: str) -> tuple[Article, bool] | None:
    """The article this slug leads to, and whether it is a former slug of it."""
    article = await db.scalar(select(Article).where(Article.slug == slug))
    if article is not None:
        return article, False
    article = await db.scalar(
        select(Article)
        .join(ArticleSlugOld, ArticleSlugOld.article_id == Article.id)
        .where(ArticleSlugOld.slug == slug)
    )
    return (article, True) if article is not None else None


async def set_slug(db: AsyncSession, article: Article, new: str) -> None:
    """Give ``article`` the slug ``new``, keeping the old one as a redirect once published.

    Raises:
        ValidationError: ``slug_invalid``.
        ConflictError: ``slug_taken`` — another article has or had it.
    """
    validate_slug(new)
    if new == article.slug:
        return
    holder = await resolve_slug(db, new)
    if holder is not None and holder[0].id != article.id:
        raise ConflictError("this address is taken", code="slug_taken")
    await db.execute(delete(ArticleSlugOld).where(ArticleSlugOld.slug == new))
    if article.slug and article.published_at is not None:
        db.add(ArticleSlugOld(slug=article.slug, article_id=article.id))
    article.slug = new
    await db.flush()
