"""API order events in the webhook outbox, in the move's transaction (plan C, Task 2)."""

from __future__ import annotations

import json

from csmarket.core import config as cfg
from csmarket.modules.orders.api_checkout import create_api_order
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.orders.skinslink_status import check_purchase
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.auth import ApiCaller
from csmarket.modules.public_api.models import ApiWebhook, ApiWebhookDelivery
from csmarket.modules.public_api.schemas import ApiOrderIn
from csmarket.modules.skinslink.models import SkinslinkPurchase
from sqlalchemy import ScalarResult, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_skinslink_client import FakeSkinslinkClient, purchase
from tests.integration.orders_factory import make_order
from tests.integration.skinslink_factory import OFFER
from tests.integration.test_public_api_buy import (
    Headers,
    _body,
    _customer,
    _env,  # noqa: F401 -- the autouse fixture: buying and Skinslink switched on
    _item,
)

URL = "https://partner.example/hook"


async def _order(db: AsyncSession, headers: Headers, *, webhook: bool = True) -> Order:
    item = await _item(db)
    user, _ = await _customer(db, headers, profile="cost")
    if webhook:
        db.add(ApiWebhook(user_id=user.id, url=URL))
        await db.commit()
    key = await keys.live_key(db, user.id)
    assert key is not None
    order, _ = await create_api_order(
        db,
        caller=ApiCaller(key=key, user=user),
        body=ApiOrderIn.model_validate(_body(item)),
        settings=cfg.get_settings(),
    )
    await db.commit()
    return order


async def _events(db: AsyncSession) -> list[ApiWebhookDelivery]:
    rows: ScalarResult[ApiWebhookDelivery] = await db.scalars(
        select(ApiWebhookDelivery)
        .order_by(ApiWebhookDelivery.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _buying(db: AsyncSession, order: Order) -> None:
    move(order, "buying")
    db.add(
        SkinslinkPurchase(
            order_id=order.id,
            merchant_tx_id=order.id,
            asset_id="100",
            paid_units=order.cost_units,
            purchase_id=178,
            status="pending",
            buy_pending=False,
        )
    )
    await db.commit()


async def _report(db: AsyncSession, order: Order, status: str) -> str:
    return await check_purchase(
        db,
        FakeSkinslinkClient(statuses={order.id: purchase(status, offer_id=OFFER)}),
        order_id=order.id,
    )


def _clean(row: ApiWebhookDelivery) -> None:
    text = json.dumps(row.payload).lower()
    for bad in ("source", "sl:", "ls:", "skinslink", "lisskins", "waxpeer", "tradeoffer", "token="):
        assert bad not in text, bad
    assert row.payload["event"] == row.event
    assert row.payload["event_id"] == row.id
    assert row.payload["order"]["order_id"]


async def test_paid_enqueues_one_event(customer_headers: Headers, db_session: AsyncSession) -> None:
    order = await _order(db_session, customer_headers)
    [row] = await _events(db_session)
    assert (row.event, row.order_id, row.status) == ("order.paid", order.id, "pending")
    assert row.payload["order"]["status"] == "buying"
    _clean(row)


async def test_the_whole_lifecycle(customer_headers: Headers, db_session: AsyncSession) -> None:
    order = await _order(db_session, customer_headers)
    await _buying(db_session, order)
    assert await _report(db_session, order, "active") == "trade_sent"
    assert await _report(db_session, order, "active") == "unchanged"
    assert await _report(db_session, order, "completed") == "delivered"
    assert await _report(db_session, order, "completed") == "unchanged"
    rows = await _events(db_session)
    assert [r.event for r in rows] == ["order.paid", "order.trade_sent", "order.delivered"]
    assert rows[1].payload["order"]["trade"]["offer_sent_at"] is not None
    for row in rows:
        _clean(row)


async def test_refund_event_carries_the_amount(
    customer_headers: Headers, db_session: AsyncSession
) -> None:
    order = await _order(db_session, customer_headers)
    move(order, "buying")
    await db_session.commit()
    await refund_to_balance(
        db_session, order=order, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    rows = await _events(db_session)
    assert [r.event for r in rows] == ["order.paid", "order.refunded"]
    assert rows[1].payload["order"]["refund"] == {"amount_usd": "9.000", "reason": "sold_out"}
    _clean(rows[1])
    again = await refund_to_balance(
        db_session, order=order, to_status="failed", reason="sold_out", actor="orders"
    )
    assert again is False
    assert len(await _events(db_session)) == 2


async def test_no_webhook_no_event(customer_headers: Headers, db_session: AsyncSession) -> None:
    order = await _order(db_session, customer_headers, webhook=False)
    move(order, "buying")
    await refund_to_balance(
        db_session, order=order, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    assert await _events(db_session) == []


async def test_a_site_order_of_a_webhook_user_enqueues_nothing(db_session: AsyncSession) -> None:
    site = await make_order(db_session, status="buying", paid_with="payme")
    db_session.add(ApiWebhook(user_id=site.user_id, url=URL))
    await db_session.commit()
    await refund_to_balance(
        db_session, order=site, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    assert await _events(db_session) == []
