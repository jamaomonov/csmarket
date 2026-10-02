"""The nightly trade-link erase (M4b T11, ruling R11, decision D3).

Thirty days after an order ends, its trade-link token is replaced by the masked form
(``partner`` kept); a ``verify`` letter's address is dropped a week after it was queued.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from csmarket.core import clock
from csmarket.modules.notifications.api import enqueue
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.orders.erase import erase_old_trade_links, erase_old_verify_addresses
from csmarket.modules.orders.models import Order
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import FAKE_TRADE_LINK, make_order
from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
MASKED = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••KE"
TOKEN = "FAKEFAKE"


def _ago(days: float) -> object:
    return clock.now() - timedelta(days=days)


async def _ended(db: AsyncSession, status: str, days: float, **extra: object) -> Order:
    stamp = {"delivered": "delivered_at", "cancelled": "cancelled_at"}.get(status, "failed_at")
    columns: dict[str, object] = {"status": status, "paid_with": "payme", stamp: _ago(days)}
    return await make_order(db, user=None, **columns, **extra)


async def _link(db: AsyncSession, order: Order) -> tuple[str, object]:
    row = (
        await db.execute(
            select(Order.trade_link, Order.trade_link_erased_at).where(Order.id == order.id)
        )
    ).one()
    return row[0], row[1]


@pytest.mark.parametrize("status", ["delivered", "cancelled", "failed", "returned"])
async def test_an_order_ended_31_days_ago_loses_its_token(
    db_session: AsyncSession, status: str
) -> None:
    order = await _ended(db_session, status, 31)
    assert await erase_old_trade_links(db_session, at=clock.now()) == 1
    link, erased_at = await _link(db_session, order)
    assert link == MASKED  # the partner stays: an operator matches it to the Steam account
    assert erased_at is not None


async def test_an_order_ended_29_days_ago_keeps_it(db_session: AsyncSession) -> None:
    order = await _ended(db_session, "delivered", 29)
    assert await erase_old_trade_links(db_session, at=clock.now()) == 0
    assert (await _link(db_session, order)) == (FAKE_TRADE_LINK, None)


@pytest.mark.parametrize("status", ["pending", "paid", "buying", "trade_sent"])
async def test_open_orders_are_never_touched(db_session: AsyncSession, status: str) -> None:
    order = await make_order(
        db_session, status=status, paid_at=_ago(60), created_at=_ago(60), failed_at=_ago(40)
    )
    assert await erase_old_trade_links(db_session, at=clock.now()) == 0
    assert (await _link(db_session, order))[0] == FAKE_TRADE_LINK


async def test_running_twice_changes_nothing(db_session: AsyncSession) -> None:
    order = await _ended(db_session, "delivered", 40)
    await erase_old_trade_links(db_session, at=clock.now())
    first = await _link(db_session, order)
    assert await erase_old_trade_links(db_session, at=clock.now() + timedelta(hours=1)) == 0
    assert await _link(db_session, order) == first


async def test_batches_run_until_done(db_session: AsyncSession) -> None:
    for _ in range(5):
        await _ended(db_session, "delivered", 31)
    assert await erase_old_trade_links(db_session, at=clock.now(), batch=2) == 5


async def test_a_link_that_does_not_parse_is_replaced_whole(db_session: AsyncSession) -> None:
    order = await _ended(db_session, "delivered", 31, trade_link="not a trade link FAKEFAKE")
    await erase_old_trade_links(db_session, at=clock.now())
    assert (await _link(db_session, order))[0] == "erased"


async def test_the_old_token_is_nowhere_in_the_row(db_session: AsyncSession) -> None:
    order = await _ended(db_session, "delivered", 31)
    await erase_old_trade_links(db_session, at=clock.now())
    row: str = (
        await db_session.execute(
            text("SELECT o::text FROM orders o WHERE id = :id"), {"id": order.id}
        )
    ).scalar_one()
    assert TOKEN not in row


async def test_the_admin_sees_the_stored_masked_link(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    order = await _ended(db_session, "delivered", 31)
    await erase_old_trade_links(db_session, at=clock.now())
    r = await integration_client.get(
        f"/api/v1/admin/orders/{order.number}", headers=await admin_headers()
    )
    assert r.status_code == 200, r.text
    assert r.json()["order"]["trade_link_masked"] == MASKED
    assert TOKEN not in r.text


async def test_a_week_old_verify_address_is_dropped(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    old = await enqueue(db_session, kind="verify", user_id=user.id, address="a@example.uz")
    new = await enqueue(db_session, kind="verify", user_id=user.id, address="b@example.uz")
    await db_session.execute(
        update(EmailOutbox).where(EmailOutbox.id == old).values(created_at=_ago(8))
    )
    await db_session.execute(
        update(EmailOutbox).where(EmailOutbox.id == new).values(created_at=_ago(6))
    )
    await db_session.commit()
    assert await erase_old_verify_addresses(db_session, at=clock.now()) == 1
    db_session.expire_all()
    rows = {r.id: r.address for r in (await db_session.scalars(select(EmailOutbox))).all()}
    assert rows == {old: None, new: "b@example.uz"}
    assert await erase_old_verify_addresses(db_session, at=clock.now()) == 0
