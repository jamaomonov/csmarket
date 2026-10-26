"""``/api/v1/articles*`` — what readers see (spec 2026-10-26-articles «API»).

Reads only and no sign-in. ``/articles/locales`` and ``/articles/sitemap`` are declared before
``/articles/{slug}`` and both words are refused as slugs (``slugs.RESERVED_SLUGS``).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.client_ip import client_ip
from csmarket.core.config import get_settings
from csmarket.modules.articles import public, reactions
from csmarket.modules.articles.schemas import (
    ArticleLocalesOut,
    ArticleMeOut,
    ArticleOut,
    ArticleRedirectOut,
    ArticleSitemapOut,
    ArticlesPageOut,
    LikeOut,
    Locale,
    Section,
)
from csmarket.modules.auth.api import guard_ip, optional_user
from csmarket.modules.users.api import User

router = APIRouter(prefix="/articles", tags=["articles"])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Reader = Annotated[User | None, Depends(optional_user)]


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


def _anon(request: Request) -> str | None:
    raw = request.cookies.get(reactions.ANON_COOKIE)
    try:
        return str(uuid.UUID(raw)) if raw else None
    except ValueError:
        return None


@router.post(
    "/{slug}/view",
    status_code=204,
    responses={404: {"description": "`article_not_found`"}},
    summary="Count a view",
)
async def post_view(slug: str, request: Request, db: Db) -> Response:
    """The page's beacon after it renders. Keyless on purpose: it only moves a counter, at most
    once per visitor per day, and a repeat changes nothing."""
    article = await reactions.live_article(db, slug)
    await reactions.count_view(db, article, ip=client_ip(request))
    return Response(status_code=204)


@router.get(
    "/{slug}/me",
    response_model=ArticleMeOut,
    responses={404: {"description": "`article_not_found`"}},
    summary="Counters for me",
)
async def get_me(slug: str, request: Request, db: Db, user: Reader) -> JSONResponse:
    """Views, likes and whether I like it (by my account, else my anonymous cookie). An
    anonymous reader without the cookie gets it here, before any like, so two first likes at
    once (two tabs, a double tap) share one id."""
    article = await reactions.live_article(db, slug)
    anon = _anon(request)
    mine = await reactions.liked(db, article, user_id=user.id if user else None, anon_id=anon)
    response = JSONResponse(
        ArticleMeOut(likes=article.likes, liked=mine, views=article.views).model_dump()
    )
    if user is None and anon is None:
        _set_anon(response, str(uuid.uuid4()))
    return response


def _set_anon(response: JSONResponse, anon: str) -> None:
    response.set_cookie(
        reactions.ANON_COOKIE,
        anon,
        max_age=reactions.ANON_MAX_AGE,
        httponly=True,
        secure=get_settings().is_prod,
        samesite="lax",
    )


async def _like(
    slug: str, request: Request, db: AsyncSession, user: User | None, *, on: bool
) -> JSONResponse:
    await guard_ip(request, bucket="article-like")
    article = await reactions.live_article(db, slug)
    anon = _anon(request)
    fresh = user is None and anon is None and on
    if fresh:
        anon = str(uuid.uuid4())
    if user is None and anon is None:  # an unlike from a reader who never liked
        return JSONResponse(LikeOut(likes=article.likes, liked=False).model_dump())
    likes = await reactions.set_like(
        db, article, on=on, user_id=user.id if user else None, anon_id=anon or ""
    )
    response = JSONResponse(LikeOut(likes=likes, liked=on).model_dump())
    if fresh and anon is not None:
        _set_anon(response, anon)
    return response


@router.put(
    "/{slug}/like",
    response_model=LikeOut,
    responses={404: {"description": "`article_not_found`"}, 429: {"description": "rate limited"}},
    summary="Like",
)
async def put_like(slug: str, request: Request, db: Db, user: Reader) -> JSONResponse:
    """Like the article, signed in or not; liking twice changes nothing. Keyless: the call sets
    a state, so a repeat is harmless. The first anonymous like sets the ``csm_aid`` cookie."""
    return await _like(slug, request, db, user, on=True)


@router.delete(
    "/{slug}/like",
    response_model=LikeOut,
    responses={404: {"description": "`article_not_found`"}, 429: {"description": "rate limited"}},
    summary="Unlike",
)
async def delete_like(slug: str, request: Request, db: Db, user: Reader) -> JSONResponse:
    """Take my like back; without one nothing changes. Keyless, like ``PUT``."""
    return await _like(slug, request, db, user, on=False)
