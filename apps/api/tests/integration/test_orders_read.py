"""``GET /orders/{number}`` and ``GET /me/orders``: owner only, expiry read as cancelled,
newest first by cursor, one query per page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.modules.orders.service import list_for_user
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import (
    build_order,
    make_item_and_rate,
    make_order,
    make_trade,
)
from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio

ORDERS = "/api/v1/orders"
MINE = "/api/v1/me/orders"
SEND_UNTIL = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)


@pytest.fixture
async def headers(integration_client: AsyncClient) -> dict[str, str]:
    return await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)


@pytest.fixture
async def buyer(headers: dict[str, str], db_session: AsyncSession) -> User:
    user = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


async def test_the_owner_reads_the_order(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    order = await make_order(db_session, user=buyer)
    r = await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["number"] == order.number
    assert (body["status"], body["payable"], body["trade"]) == ("pending", True, None)
    assert (body["price_uzs"], body["price_usd"]) == ("171800", "13.580000")
    assert body["slug"] == order.slug
    assert body["name"] == order.market_hash_name
    assert (body["paid_with"], body["refunded_to"], body["paid_at"]) == (None, None, None)
    assert "trade_link" not in body
    assert "cost_units" not in body


async def test_an_old_order_reads_null_float_seed_and_look(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    order = await make_order(db_session, user=buyer)
    body = (await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)).json()
    assert (body["float_value"], body["paint_seed"]) == (None, None)
    assert (body["exterior"], body["rarity_color"]) == (None, None)


async def test_the_order_shows_its_float_seed_and_the_catalogue_look(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    item, fx = await make_item_and_rate(db_session)
    item.exterior, item.rarity_color = "FT", "#eb4b4b"
    order = await build_order(
        db_session,
        user=buyer,
        item=item,
        fx=fx,
        float_value=Decimal("0.621400"),
        paint_seed=661,
    )
    await db_session.commit()
    one = (await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)).json()
    assert (one["float_value"], one["paint_seed"]) == ("0.6214", 661)
    assert (one["exterior"], one["rarity_color"]) == ("FT", "#eb4b4b")
    [listed] = (await integration_client.get(MINE, headers=headers)).json()["items"]
    assert (listed["float_value"], listed["exterior"]) == ("0.6214", "FT")


async def test_a_paid_order_shows_its_trade(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    order = await make_order(
        db_session, user=buyer, status="trade_sent", paid_with="wallet", paid_at=clock.now()
    )
    await make_trade(
        db_session,
        order,
        status=4,
        trade_id="9393511289",
        send_until=SEND_UNTIL,
        seller={"name": "fake-seller", "avatar_url": None, "level": 3, "joined_at": None},
    )
    body = (await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)).json()
    assert (body["status"], body["payable"], body["paid_with"]) == ("trade_sent", False, "wallet")
    trade = body["trade"]
    assert trade["state"] == "offer_sent"
    assert trade["offer_url"] == "https://steamcommunity.com/tradeoffer/9393511289/"
    assert trade["seller"]["name"] == "fake-seller"
    assert trade["reason_code"] is None


async def test_a_paid_order_without_a_trade_reads_buying(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    order = await make_order(db_session, user=buyer, status="paid", paid_at=clock.now())
    body = (await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)).json()
    assert body["trade"]["state"] == "buying"


async def test_another_users_order_is_404(
    integration_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    order = await make_order(db_session)  # someone else's
    r = await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("number", ["nope", "abcdefgh", "T1234567", "00000000", "A" * 9])
async def test_a_malformed_or_unknown_number_is_404(
    integration_client: AsyncClient, headers: dict[str, str], number: str
) -> None:
    r = await integration_client.get(f"{ORDERS}/{number}", headers=headers)
    assert r.status_code == 404, r.text


async def test_reads_need_a_sign_in(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(f"{ORDERS}/A1B2C3D4")).status_code == 401
    assert (await integration_client.get(MINE)).status_code == 401


async def test_an_expired_pending_order_reads_cancelled(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    order = await make_order(db_session, user=buyer, expires_at=clock.now() - timedelta(seconds=1))
    body = (await integration_client.get(f"{ORDERS}/{order.number}", headers=headers)).json()
    assert (body["status"], body["payable"], body["trade"]) == ("cancelled", False, None)


async def test_the_list_hides_cancelled_and_expired_orders(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    item, fx = await make_item_and_rate(db_session)
    live = await build_order(db_session, user=buyer, item=item, fx=fx)
    paid = await build_order(db_session, user=buyer, item=item, fx=fx, status="paid")
    await build_order(db_session, user=buyer, item=item, fx=fx, status="cancelled")
    await build_order(
        db_session, user=buyer, item=item, fx=fx, expires_at=clock.now() - timedelta(minutes=1)
    )
    other = await make_user(db_session)
    await build_order(db_session, user=other, item=item, fx=fx)
    await db_session.commit()
    r = await integration_client.get(MINE, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {o["number"] for o in body["items"]} == {live.number, paid.number}
    assert body["next_cursor"] is None


async def test_the_list_pages_newest_first_by_cursor(
    integration_client: AsyncClient,
    headers: dict[str, str],
    buyer: User,
    db_session: AsyncSession,
) -> None:
    item, fx = await make_item_and_rate(db_session)
    base = clock.now() - timedelta(hours=1)
    numbers: list[str] = []
    for i in range(25):
        order = await build_order(db_session, user=buyer, item=item, fx=fx, status="paid")
        # Five share one timestamp: the id breaks the tie, never a row twice or lost.
        order.created_at = base + timedelta(seconds=i - i % 5)
        numbers.append(order.number)
    await db_session.commit()
    first = (await integration_client.get(MINE, headers=headers)).json()
    assert len(first["items"]) == 20
    assert first["next_cursor"]
    second = (
        await integration_client.get(MINE, headers=headers, params={"cursor": first["next_cursor"]})
    ).json()
    assert len(second["items"]) == 5
    assert second["next_cursor"] is None
    seen = [o["number"] for o in first["items"] + second["items"]]
    assert sorted(seen) == sorted(numbers)
    stamps = [o["created_at"] for o in first["items"] + second["items"]]
    assert stamps == sorted(stamps, reverse=True)


async def test_a_bad_cursor_is_422(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await integration_client.get(MINE, headers=headers, params={"cursor": "garbage!"})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "cursor"


async def test_one_page_costs_a_constant_number_of_queries(db_session: AsyncSession) -> None:
    async def _queries(count: int) -> int:
        user = await make_user(db_session)
        item, fx = await make_item_and_rate(db_session)
        for i in range(count):
            order = await build_order(db_session, user=user, item=item, fx=fx, status="buying")
            await db_session.flush()
            if i % 2:
                await make_trade(db_session, order, status=4, trade_id=str(1000 + i))
        await db_session.commit()
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_session.bind.sync_engine  # type: ignore[union-attr]
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            rows, _ = await list_for_user(db_session, user.id, None)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert len(rows) == count
        assert sum(r.trade is not None for r in rows) == count // 2
        return len(statements)

    small, large = await _queries(2), await _queries(12)
    assert small == large > 0
