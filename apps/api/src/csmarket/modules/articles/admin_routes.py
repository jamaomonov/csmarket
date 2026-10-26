"""``/api/v1/admin/articles*`` — the admin's «Статьи» (spec 2026-10-26-articles «Admin»).

Writes take ``Idempotency-Key`` (``required_key``), replay with ``replayed`` / ``remember`` and
leave an audit row ``articles.<verb>`` (ids and slugs only, never the text).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.articles import admin
from csmarket.modules.articles.models import Article
from csmarket.modules.articles.schemas import (
    AdminArticleOut,
    AdminArticlesOut,
    ArticleIn,
    ArticlePatch,
    Section,
    Status,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/articles", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]
_WRITE: dict[int | str, dict[str, str]] = {
    404: {"description": "`article_not_found`"},
    409: {"description": "`slug_taken` or `idempotency_mismatch`"},
    422: {"description": "`slug_invalid` or `cover_not_found`"},
}


async def _write(
    db: AsyncSession,
    *,
    user: User,
    key: str,
    verb: str,
    asked: dict[str, Any],
    act: Callable[[], Awaitable[Article]],
) -> AdminArticleOut:
    scope = f"admin.articles.{verb}"
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return AdminArticleOut.model_validate(hit)
    article = await act()
    await record(
        db,
        actor_id=user.id,
        action=f"articles.{verb}",
        target_type="article",
        target_id=article.id,
        payload={"slug": article.slug, "status": article.status},
    )
    out = await admin.article_out(db, article)
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("", response_model=AdminArticlesOut, summary="Articles")
async def get_articles(
    db: Db, section: Section | None = None, status: Status | None = None
) -> AdminArticlesOut:
    """Every article, last edited first; ``section`` and ``status`` filter."""
    return await admin.list_articles(db, section=section, status=status)


@router.post("", response_model=AdminArticleOut, responses=_WRITE, summary="New article")
async def post_article(body: ArticleIn, user: Admin, db: Db, key: Key) -> AdminArticleOut:
    """A new draft. Audited ``articles.create``."""
    return await _write(
        db,
        user=user,
        key=key,
        verb="create",
        asked=body.model_dump(mode="json"),
        act=lambda: admin.create_article(db, body, by=user.id),
    )


@router.get(
    "/{article_id}",
    response_model=AdminArticleOut,
    responses={404: _WRITE[404]},
    summary="One article",
)
async def get_article(article_id: uuid.UUID, db: Db) -> AdminArticleOut:
    """The article with all three translations (``null`` where none is written)."""
    return await admin.article_out(db, await admin.find(db, str(article_id)))


@router.patch("/{article_id}", response_model=AdminArticleOut, responses=_WRITE, summary="Edit")
async def patch_article(
    article_id: uuid.UUID, body: ArticlePatch, user: Admin, db: Db, key: Key
) -> AdminArticleOut:
    """Change the given fields; a given locale's translation is replaced whole. Audited
    ``articles.update``."""
    return await _write(
        db,
        user=user,
        key=key,
        verb="update",
        asked={"id": str(article_id), **body.model_dump(mode="json", exclude_none=True)},
        act=lambda: admin.update_article(db, str(article_id), body, by=user.id),
    )


@router.post(
    "/{article_id}/publish",
    response_model=AdminArticleOut,
    responses={
        404: _WRITE[404],
        409: {"description": "`publish_needs_cover`, `publish_needs_translation`"},
    },
    summary="Publish",
)
async def post_publish(article_id: uuid.UUID, user: Admin, db: Db, key: Key) -> AdminArticleOut:
    """Readers see its ready translations. Audited ``articles.publish``."""
    return await _write(
        db,
        user=user,
        key=key,
        verb="publish",
        asked={"id": str(article_id)},
        act=lambda: admin.publish(db, str(article_id), by=user.id),
    )


@router.post(
    "/{article_id}/unpublish",
    response_model=AdminArticleOut,
    responses={404: _WRITE[404]},
    summary="Unpublish",
)
async def post_unpublish(article_id: uuid.UUID, user: Admin, db: Db, key: Key) -> AdminArticleOut:
    """Readers no longer see it. Audited ``articles.unpublish``."""
    return await _write(
        db,
        user=user,
        key=key,
        verb="unpublish",
        asked={"id": str(article_id)},
        act=lambda: admin.unpublish(db, str(article_id), by=user.id),
    )
