"""``GET /reviews``: nothing while the page is off; on, only published reviews of live
accounts, the visitor's locale first, no Steam ID, email, amount or number."""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core.clock import now
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.reviews_factory import (
    credited_sale,
    delivered_order,
    make_review,
    set_public,
)

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/reviews"
EMPTY = {"enabled": False, "count": 0, "items": [], "next_cursor": None}
FIELDS = frozenset(
    {
        "id",
        "author_name",
        "author_avatar_url",
        "rating",
        "text",
        "kind",
        "skin_name",
        "locale",
        "created_at",
    }
)


async def test_off_is_an_empty_page(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await make_review(db_session, deal=await delivered_order(db_session), rating=5)
    r = await integration_client.get(BASE)
    assert (r.status_code, r.json()) == (200, EMPTY)
    await set_public(db_session, on=False)
    assert (await integration_client.get(BASE)).json() == EMPTY


async def test_only_published_by_live_accounts(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await set_public(db_session)
    at = now()
    five = await make_review(
        db_session, deal=await delivered_order(db_session), rating=5, locale="ru", created_at=at
    )
    four = await make_review(
        db_session,
        deal=await credited_sale(db_session),
        rating=4,
        locale="uz",
        created_at=at - timedelta(hours=1),
    )
    await make_review(db_session, deal=await delivered_order(db_session), rating=5, hidden=True)
    await make_review(db_session, deal=await delivered_order(db_session), rating=3)
    gone = await make_user(db_session)
    await make_review(db_session, deal=await delivered_order(db_session, user=gone), rating=5)
    await db_session.execute(update(User).where(User.id == gone.id).values(deleted_at=now()))
    await db_session.commit()
    uz = (await integration_client.get(BASE, params={"locale": "uz"})).json()
    assert (uz["enabled"], uz["count"]) == (True, 2)
    assert "average" not in uz  # no average: published reviews are 4–5★ only (owner ruling)
    assert [i["id"] for i in uz["items"]] == [four.id, five.id]  # the visitor's locale first
    ru = (await integration_client.get(BASE, params={"locale": "ru"})).json()
    assert [i["id"] for i in ru["items"]] == [five.id, four.id]


async def test_an_item_names_no_person_and_no_money(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await set_public(db_session)
    user = await make_user(db_session)
    user.display_name, user.avatar_url = "Gabe", "https://avatars.steamstatic.com/x_full.jpg"
    user.email = "gabe@example.com"
    await db_session.commit()
    order = await delivered_order(db_session, user=user)
    sale = await credited_sale(db_session, user=user)
    await make_review(db_session, deal=order, rating=5, text="Всё пришло")
    await make_review(db_session, deal=sale, rating=4)
    r = await integration_client.get(BASE)
    items = r.json()["items"]
    assert {frozenset(i) for i in items} == {FIELDS}
    market = next(i for i in items if i["kind"] == "market")
    sold = next(i for i in items if i["kind"] == "sale")
    assert (market["author_name"], market["skin_name"], market["text"]) == (
        "Gabe",
        order.market_hash_name,
        "Всё пришло",
    )
    assert sold["skin_name"] is None
    for secret in (user.steam_id, "gabe@example.com", user.id, order.number, sale.number):
        assert secret not in r.text
    assert str(int(order.price_uzs)) not in r.text


async def test_pages_of_twenty_with_a_cursor(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    await set_public(db_session)
    user = await make_user(db_session)
    for n in range(21):
        order = await delivered_order(db_session, user=user)
        await make_review(
            db_session,
            deal=order,
            rating=5,
            locale="uz" if n % 2 else "ru",
            created_at=now() - timedelta(minutes=n),
        )
    first = (await integration_client.get(BASE, params={"locale": "uz"})).json()
    assert (len(first["items"]), first["count"]) == (20, 21)
    assert first["next_cursor"]
    rest = (
        await integration_client.get(BASE, params={"locale": "uz", "cursor": first["next_cursor"]})
    ).json()
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None
    seen = [i["id"] for i in first["items"] + rest["items"]]
    assert len(set(seen)) == 21
    assert [i["locale"] for i in first["items"][:10]] == ["uz"] * 10
    bad = await integration_client.get(BASE, params={"cursor": "x"})
    assert (bad.status_code, bad.json()["code"]) == (422, "cursor")
    assert (await integration_client.get(BASE, params={"locale": "de"})).status_code == 422
