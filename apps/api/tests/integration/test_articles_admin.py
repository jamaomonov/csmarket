"""The admin's «Статьи»: create, edit, publish, slugs with 301 history (spec 2026-10-26)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.articles.slugs import resolve_slug
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.articles_factory import ADMIN, png, tr

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]


class Admin:
    """A signed-in admin's calls, each with a fresh idempotency key."""

    def __init__(self, client: AsyncClient, headers: dict[str, str]) -> None:
        self.client, self.headers, self.n = client, headers, 0

    def _h(self) -> dict[str, str]:
        self.n += 1
        return {**self.headers, "Idempotency-Key": f"test-admin-article-{self.n:06d}"}

    async def cover(self, salt: bytes = b"") -> str:
        r = await self.client.post(
            f"{ADMIN}/media",
            content=png(salt=salt),
            headers={**self._h(), "Content-Type": "image/png"},
        )
        return str(r.json()["hash"])

    async def create(self, **body: Any) -> Any:
        payload = {"section": "tops", "slug": "top-budget-knives", "translations": {}, **body}
        return await self.client.post(ADMIN, json=payload, headers=self._h())

    async def patch(self, article_id: str, **body: Any) -> Any:
        return await self.client.patch(f"{ADMIN}/{article_id}", json=body, headers=self._h())

    async def act(self, article_id: str, verb: str) -> Any:
        return await self.client.post(f"{ADMIN}/{article_id}/{verb}", headers=self._h())


@pytest.fixture
async def admin(integration_client: AsyncClient, admin_headers: Headers) -> Admin:
    return Admin(integration_client, await admin_headers())


async def _published(admin: Admin, slug: str = "top-budget-knives") -> dict[str, Any]:
    r = await admin.create(
        slug=slug, cover_hash=await admin.cover(slug.encode()), translations={"ru": tr()}
    )
    assert r.status_code == 200, r.text
    p = await admin.act(r.json()["id"], "publish")
    assert p.status_code == 200, p.text
    return dict(p.json())


async def test_create_edit_and_publish(admin: Admin, integration_client: AsyncClient) -> None:
    cover = await admin.cover()
    r = await admin.create(
        cover_hash=cover, translations={"ru": tr(), "uz": tr("Arzon pichoqlar", ready=False)}
    )
    assert r.status_code == 200, r.text
    a = r.json()
    assert (a["status"], a["section"], a["slug"]) == ("draft", "tops", "top-budget-knives")
    assert a["cover"]["hash"] == cover
    assert a["live_locales"] == []
    assert a["translations"]["ru"]["title"] == "Топ бюджетных ножей"
    assert a["translations"]["uz"]["ready"] is False
    assert a["translations"]["en"] is None

    e = await admin.patch(a["id"], translations={"en": tr("Top budget knives")})
    assert e.status_code == 200, e.text
    assert e.json()["translations"]["en"]["title"] == "Top budget knives"
    assert e.json()["translations"]["ru"]["title"] == "Топ бюджетных ножей"  # untouched

    p = await admin.act(a["id"], "publish")
    assert p.status_code == 200, p.text
    assert p.json()["status"] == "published"
    assert p.json()["published_at"] is not None
    assert p.json()["live_locales"] == ["ru", "en"]

    listed = await integration_client.get(ADMIN, headers=admin.headers)
    [row] = listed.json()["items"]
    assert (row["title"], row["live_locales"], row["views"], row["likes"]) == (
        "Топ бюджетных ножей",
        ["ru", "en"],
        0,
        0,
    )
    only_news = await integration_client.get(
        ADMIN, params={"section": "news"}, headers=admin.headers
    )
    assert only_news.json()["items"] == []
    drafts = await integration_client.get(ADMIN, params={"status": "draft"}, headers=admin.headers)
    assert drafts.json()["items"] == []


async def test_publish_needs_cover_and_a_ready_translation(admin: Admin) -> None:
    no_cover = (await admin.create(translations={"ru": tr()})).json()
    r = await admin.act(no_cover["id"], "publish")
    assert (r.status_code, r.json()["code"]) == (409, "publish_needs_cover")
    unready = (
        await admin.create(
            slug="unready",
            cover_hash=await admin.cover(b"u"),
            translations={"ru": tr(ready=False), "en": tr(body="")},
        )
    ).json()
    r = await admin.act(unready["id"], "publish")
    assert (r.status_code, r.json()["code"]) == (409, "publish_needs_translation")


async def test_slug_change_before_publish_keeps_no_history(
    admin: Admin, db_session: AsyncSession
) -> None:
    a = (await admin.create(translations={"ru": tr()})).json()
    r = await admin.patch(a["id"], slug="cheap-knives")
    assert r.json()["slug"] == "cheap-knives"
    assert await resolve_slug(db_session, "top-budget-knives") is None


async def test_every_former_slug_points_to_the_current(
    admin: Admin, db_session: AsyncSession
) -> None:
    a = await _published(admin, "slug-a")
    await admin.patch(a["id"], slug="slug-b")
    await admin.patch(a["id"], slug="slug-c")
    for old in ("slug-a", "slug-b"):
        found = await resolve_slug(db_session, old)
        assert found is not None
        article, is_old = found
        assert (article.id, article.slug, is_old) == (a["id"], "slug-c", True)
    back = await admin.patch(a["id"], slug="slug-a")  # its own former slug may be taken back
    assert back.json()["slug"] == "slug-a"
    found = await resolve_slug(db_session, "slug-a")
    assert found is not None
    assert found[1] is False


async def test_a_slug_in_use_or_formerly_used_elsewhere_is_taken(admin: Admin) -> None:
    a = await _published(admin, "first")
    await admin.patch(a["id"], slug="first-renamed")
    for slug in ("first", "first-renamed"):
        r = await admin.create(slug=slug)
        assert (r.status_code, r.json()["code"]) == (409, "slug_taken")
    bad = await admin.create(slug="news")
    assert (bad.status_code, bad.json()["code"]) == (422, "slug_invalid")


async def test_unpublish_then_republish_keeps_published_at(admin: Admin) -> None:
    a = await _published(admin)
    off = await admin.act(a["id"], "unpublish")
    assert (off.json()["status"], off.json()["live_locales"]) == ("draft", [])
    on = await admin.act(a["id"], "publish")
    assert on.json()["published_at"] == a["published_at"]


async def test_editing_a_published_translation_moves_updated_at(admin: Admin) -> None:
    a = await _published(admin)
    r = await admin.patch(a["id"], translations={"ru": tr(body="Новый текст.")})
    assert r.json()["updated_at"] > a["updated_at"]


async def test_replay_and_mismatch(admin: Admin) -> None:
    h = {**admin.headers, "Idempotency-Key": "test-admin-article-replay-1"}
    body = {"section": "news", "slug": "cs2-update", "translations": {}}
    first = await admin.client.post(ADMIN, json=body, headers=h)
    again = await admin.client.post(ADMIN, json=body, headers=h)
    other = await admin.client.post(ADMIN, json={**body, "slug": "other"}, headers=h)
    assert again.json() == first.json()
    assert other.status_code == 409


async def test_unknown_cover_and_article(admin: Admin) -> None:
    r = await admin.create(cover_hash="0" * 64)
    assert (r.status_code, r.json()["code"]) == (422, "cover_not_found")
    missing = await admin.client.get(
        f"{ADMIN}/00000000-0000-0000-0000-000000000000", headers=admin.headers
    )
    assert missing.status_code == 404


async def test_a_customer_gets_403(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    r = await integration_client.get(ADMIN, headers=await customer_headers())
    assert r.status_code == 403


async def test_audit_rows(admin: Admin, db_session: AsyncSession) -> None:
    a = await _published(admin)
    await admin.patch(a["id"], translations={"ru": tr(body="x")})
    await admin.act(a["id"], "unpublish")
    actions = set((await db_session.scalars(select(AdminAuditLog.action))).all())
    assert {
        "articles.create",
        "articles.update",
        "articles.publish",
        "articles.unpublish",
    } <= actions
