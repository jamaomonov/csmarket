"""Views and likes on articles (spec 2026-10-26-articles «Calls»)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import pytest
from csmarket.modules.articles import reactions
from csmarket.modules.articles.models import Article
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.articles_factory import make_article

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
#: The test client's address as the API sees it.
IP = "127.0.0.1"


async def _views(db: AsyncSession, article: Article) -> int:
    await db.refresh(article)
    return article.views


async def test_view_counts_once_per_day_per_visitor(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    a = await make_article(db_session, slug="viewed")
    for _ in range(3):
        r = await integration_client.post("/api/v1/articles/viewed/view")
        assert r.status_code == 204
    assert await _views(db_session, a) == 1
    other = await integration_client.post(
        "/api/v1/articles/viewed/view", headers={"X-Forwarded-For": "203.0.113.7"}
    )
    assert other.status_code == 204


async def test_view_of_an_unpublished_article_is_404(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="hidden", status="draft")
    r = await integration_client.post("/api/v1/articles/hidden/view")
    assert r.status_code == 404


async def test_view_without_redis_is_204_and_uncounted(
    db_session: AsyncSession, integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await make_article(db_session, slug="no-redis")

    def broken() -> object:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(reactions, "get_redis", broken)
    r = await integration_client.post("/api/v1/articles/no-redis/view")
    assert r.status_code == 204
    assert await _views(db_session, a) == 0


async def test_anonymous_like_sets_cookie_and_counts(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="liked")
    r = await integration_client.put("/api/v1/articles/liked/like")
    assert r.status_code == 200, r.text
    assert r.json() == {"likes": 1, "liked": True}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("csm_aid=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    me = await integration_client.get("/api/v1/articles/liked/me")
    assert me.json() == {"likes": 1, "liked": True, "views": 0}
    off = await integration_client.delete("/api/v1/articles/liked/like")
    assert off.json() == {"likes": 0, "liked": False}


async def test_like_is_idempotent_per_key(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="twice")
    await integration_client.put("/api/v1/articles/twice/like")
    again = await integration_client.put("/api/v1/articles/twice/like")
    assert again.json() == {"likes": 1, "liked": True}


async def test_unlike_without_like_is_a_noop(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="never")
    r = await integration_client.delete("/api/v1/articles/never/like")
    assert r.json() == {"likes": 0, "liked": False}
    assert "set-cookie" not in r.headers


async def test_signed_in_like_is_keyed_by_the_user(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    await make_article(db_session, slug="mine")
    h = await customer_headers()
    r = await integration_client.put("/api/v1/articles/mine/like", headers=h)
    assert r.json() == {"likes": 1, "liked": True}
    assert "csm_aid" not in r.headers.get("set-cookie", "")
    integration_client.cookies.clear()
    anonymous = await integration_client.get("/api/v1/articles/mine/me")
    assert anonymous.json()["liked"] is False
    signed_in = await integration_client.get("/api/v1/articles/mine/me", headers=h)
    assert signed_in.json()["liked"] is True


async def test_a_bad_token_reads_as_anonymous(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="token")
    r = await integration_client.get(
        "/api/v1/articles/token/me", headers={"Authorization": "Bearer nonsense"}
    )
    assert r.status_code == 200
    assert r.json()["liked"] is False


async def test_the_like_bucket_limits_an_address(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="spam")
    for _ in range(30):
        integration_client.cookies.clear()
        assert (await integration_client.put("/api/v1/articles/spam/like")).status_code == 200
    integration_client.cookies.clear()
    r = await integration_client.put("/api/v1/articles/spam/like")
    assert r.status_code == 429


async def test_like_of_an_unpublished_article_is_404(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="off", status="draft")
    assert (await integration_client.put("/api/v1/articles/off/like")).status_code == 404


async def test_no_address_in_the_logs(
    db_session: AsyncSession, integration_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await make_article(db_session, slug="quiet")
    with caplog.at_level(logging.DEBUG):
        await integration_client.post("/api/v1/articles/quiet/view")
        await integration_client.put("/api/v1/articles/quiet/like")
    assert IP not in caplog.text
