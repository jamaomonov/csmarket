"""Views and likes (spec 2026-10-26-articles «Calls»).

A view is the browser's beacon after the article renders, counted at most once per article per
visitor per UTC day. The visitor is told apart by ``sha256(daily salt + ip + article id)`` kept
in Redis until midnight; the salt is random per day and lives only in Redis, so the hash cannot
be turned back into an address, and the address itself is never stored or logged. Without Redis
a view is simply not counted.

A like is keyed by the signed-in user, else by the anonymous ``csm_aid`` cookie the first like
sets. Pressing twice changes nothing; the counter on the article moves in the same transaction
as the like row.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from redis.exceptions import RedisError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.clock import now
from csmarket.core.errors import NotFoundError
from csmarket.core.redis import get_redis
from csmarket.modules.articles.models import Article, ArticleLike, ArticleTranslation, live

#: The anonymous like cookie.
ANON_COOKIE = "csm_aid"
#: Its lifetime, seconds (one year).
ANON_MAX_AGE = 365 * 24 * 3600


async def live_article(db: AsyncSession, slug: str) -> Article:
    """The article at ``slug`` when any translation of it is live.

    Raises:
        NotFoundError: ``article_not_found``.
    """
    article = await db.scalar(
        select(Article)
        .join(ArticleTranslation, ArticleTranslation.article_id == Article.id)
        .where(Article.slug == slug, live())
        .limit(1)
    )
    if article is None:
        raise NotFoundError("no such article", code="article_not_found")
    return article


def _next_midnight(at: datetime) -> datetime:
    return (at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


async def count_view(db: AsyncSession, article: Article, *, ip: str) -> bool:
    """Count one view unless this visitor was counted today; ``False`` when not counted."""
    at = now()
    day = at.strftime("%Y-%m-%d")
    try:
        redis = get_redis()
        salt_key = f"articles:view_salt:{day}"
        await redis.set(salt_key, secrets.token_hex(32), nx=True, ex=2 * 24 * 3600)
        salt = await redis.get(salt_key)
        if salt is None:
            return False
        salt_text = salt.decode() if isinstance(salt, bytes) else str(salt)
        digest = hashlib.sha256(f"{salt_text}|{ip}|{article.id}".encode()).hexdigest()
        ttl = max(1, int((_next_midnight(at) - at).total_seconds()))
        if not await redis.set(f"articles:viewed:{digest}", "1", nx=True, ex=ttl):
            return False
    except (RedisError, ConnectionError, OSError):
        return False
    await db.execute(
        update(Article).where(Article.id == article.id).values(views=Article.views + 1)
    )
    await db.commit()
    return True


def _match(user_id: str | None, anon_id: str | None) -> ColumnElement[bool] | None:
    """The like row of this reader: by the user when signed in, else by the cookie."""
    if user_id:
        return ArticleLike.user_id == user_id
    if anon_id:
        return ArticleLike.anon_id == anon_id
    return None


async def liked(
    db: AsyncSession, article: Article, *, user_id: str | None, anon_id: str | None
) -> bool:
    """Whether this reader likes the article."""
    match = _match(user_id, anon_id)
    if match is None:
        return False
    found = await db.scalar(
        select(ArticleLike.id).where(ArticleLike.article_id == article.id, match)
    )
    return found is not None


async def set_like(
    db: AsyncSession, article: Article, *, on: bool, user_id: str | None, anon_id: str
) -> int:
    """Like (``on``) or unlike for this reader; the article's like count after it."""
    match = _match(user_id, anon_id)
    assert match is not None  # anon_id is always set by the route
    if on:
        owner = {"user_id": user_id} if user_id else {"anon_id": anon_id}
        result = await db.execute(
            insert(ArticleLike)
            .values(id=str(uuid.uuid4()), article_id=article.id, **owner)
            .on_conflict_do_nothing()
            .returning(ArticleLike.id)
        )
        delta = 1 if result.scalar_one_or_none() is not None else 0
    else:
        result = await db.execute(
            delete(ArticleLike)
            .where(ArticleLike.article_id == article.id, match)
            .returning(ArticleLike.id)
        )
        delta = -len(result.scalars().all())
    likes = await db.scalar(
        update(Article)
        .where(Article.id == article.id)
        .values(likes=Article.likes + delta)
        .returning(Article.likes)
    )
    await db.commit()
    return int(likes or 0)
