"""Public articles: live translations only, skin cards, locales, sitemap (spec 2026-10-26)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.modules.articles.models import ArticleSlugOld, ArticleTranslation
from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.articles_factory import make_article, tr
from tests.integration.orders_factory import make_item_and_rate

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 20, tzinfo=UTC)


async def test_lists_only_live_translations_of_a_locale(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="newer", published_at=T0 + timedelta(days=1))
    await make_article(db_session, slug="older", published_at=T0)
    await make_article(db_session, slug="draft", status="draft")
    await make_article(db_session, slug="unready", translations={"ru": tr(ready=False)})
    await make_article(db_session, slug="english", translations={"en": tr("English")})
    await make_article(db_session, slug="guide", section="guides")
    r = await integration_client.get("/api/v1/articles", params={"locale": "ru"})
    assert r.status_code == 200
    assert [a["slug"] for a in r.json()["items"]] == ["guide", "newer", "older"]
    tops = await integration_client.get(
        "/api/v1/articles", params={"locale": "ru", "section": "tops"}
    )
    assert [a["slug"] for a in tops.json()["items"]] == ["newer", "older"]
    card = tops.json()["items"][0]
    assert card["title"] == "Топ бюджетных ножей"
    assert card["cover"]["url"].startswith("/media/")
    assert (card["views"], card["likes"]) == (0, 0)
    en = await integration_client.get("/api/v1/articles", params={"locale": "en"})
    assert [a["slug"] for a in en.json()["items"]] == ["english"]


async def test_the_list_pages_by_cursor(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    for n in range(13):
        await make_article(db_session, slug=f"news-{n:02d}", published_at=T0 + timedelta(hours=n))
    first = (await integration_client.get("/api/v1/articles", params={"locale": "ru"})).json()
    assert len(first["items"]) == 12
    assert first["items"][0]["slug"] == "news-12"
    rest = (
        await integration_client.get(
            "/api/v1/articles", params={"locale": "ru", "cursor": first["next_cursor"]}
        )
    ).json()
    assert [a["slug"] for a in rest["items"]] == ["news-00"]
    assert rest["next_cursor"] is None


async def test_an_article_in_a_locale(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(
        db_session, slug="ak-tier-list", translations={"ru": tr(), "en": tr("AK tier list")}
    )
    r = await integration_client.get("/api/v1/articles/ak-tier-list", params={"locale": "en"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["kind"] == "article"
    assert (a["title"], a["locales"], a["section"]) == ("AK tier list", ["ru", "en"], "tops")
    assert a["body"] == "Текст."
    assert a["cover_alt"] == "Обложка"


async def test_missing_translation_is_404(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="ru-only")
    await make_article(db_session, slug="hidden", status="draft")
    for slug, locale in (("ru-only", "uz"), ("hidden", "ru"), ("nothing", "ru")):
        r = await integration_client.get(f"/api/v1/articles/{slug}", params={"locale": locale})
        assert r.status_code == 404, (slug, locale)
        assert r.json()["code"] == "article_not_found"


async def test_unready_last_translation_hides_the_article(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    a = await make_article(db_session, slug="last-one")
    await db_session.execute(
        update(ArticleTranslation).where(ArticleTranslation.article_id == a.id).values(ready=False)
    )
    await db_session.commit()
    listed = await integration_client.get("/api/v1/articles", params={"locale": "ru"})
    assert listed.json()["items"] == []
    locales = (await integration_client.get("/api/v1/articles/locales")).json()
    assert locales["ru"] == []
    sitemap = (await integration_client.get("/api/v1/articles/sitemap")).json()
    assert sitemap["items"] == []


async def test_old_slug_answers_redirect(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    a = await make_article(db_session, slug="new-name")
    db_session.add(ArticleSlugOld(slug="old-name", article_id=a.id))
    await db_session.commit()
    r = await integration_client.get("/api/v1/articles/old-name", params={"locale": "ru"})
    assert r.status_code == 200
    assert r.json() == {"kind": "redirect", "slug": "new-name"}


async def test_embeds_skip_unknown_and_hidden_items(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    priced, _ = await make_item_and_rate(db_session)
    priced.sell_price_usd = Decimal("12.5")
    priced.active = True
    hidden, _ = await make_item_and_rate(db_session)
    hidden.sell_price_usd = Decimal("3")
    hidden.hidden = True
    hidden.active = True
    await db_session.commit()
    body = "\n".join(
        [
            "Лучшие скины:",
            f"[[skin:{priced.slug}]]",
            f"[[skin:{hidden.slug}]]",
            "[[skin:no-such-item]]",
            f"inline [[skin:{priced.slug}]] is not an embed",
        ]
    )
    await make_article(db_session, slug="best", translations={"ru": tr(body=body)})
    r = await integration_client.get("/api/v1/articles/best", params={"locale": "ru"})
    embeds = r.json()["embeds"]
    assert list(embeds) == [priced.slug]
    assert Decimal(embeds[priced.slug]["price_usd"]) == Decimal("12.5")


async def test_related_excludes_self_and_other_sections(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    for n in range(5):
        await make_article(db_session, slug=f"top-{n}", published_at=T0 + timedelta(days=n))
    await make_article(db_session, slug="a-guide", section="guides")
    r = await integration_client.get("/api/v1/articles/top-4", params={"locale": "ru"})
    assert [a["slug"] for a in r.json()["related"]] == ["top-3", "top-2", "top-1"]


async def test_locales_summary(db_session: AsyncSession, integration_client: AsyncClient) -> None:
    await make_article(db_session, slug="ru-top", translations={"ru": tr(), "uz": tr("Uz")})
    await make_article(db_session, slug="ru-news", section="news")
    r = await integration_client.get("/api/v1/articles/locales")
    assert r.json() == {"ru": ["news", "tops"], "uz": ["tops"], "en": []}


async def test_sitemap_lists_live_translations_only(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_article(db_session, slug="both", translations={"ru": tr(), "en": tr("En")})
    await make_article(db_session, slug="off", status="draft")
    items = (await integration_client.get("/api/v1/articles/sitemap")).json()["items"]
    assert sorted((i["slug"], i["locale"]) for i in items) == [("both", "en"), ("both", "ru")]
    assert all(i["updated_at"] for i in items)


async def test_list_query_count_is_constant(
    db_session: AsyncSession, integration_client: AsyncClient, db_engine: AsyncEngine
) -> None:
    async def _count(articles: int, prefix: str) -> int:
        for n in range(articles):
            await make_article(db_session, slug=f"{prefix}-{n}")
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_engine.sync_engine
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            r = await integration_client.get("/api/v1/articles", params={"locale": "ru"})
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert r.status_code == 200
        return len(statements)

    assert await _count(2, "few") == await _count(8, "many")
