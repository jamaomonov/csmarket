"""API orders: refunds to the USD wallet, ``trade_hold``, no letters (plan B, Task 6)."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core import config as cfg
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.orders.api_checkout import create_api_order
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.letters import enqueue_receipt, enqueue_refunded, enqueue_trade_sent
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.auth import ApiCaller
from csmarket.modules.public_api.schemas import ApiOrderIn
from csmarket.modules.wallet.api import user_balance, user_usd_balance
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.orders_factory import make_order
from tests.integration.test_public_api_buy import (
    ORDERS,
    Headers,
    _body,
    _customer,
    _env,  # noqa: F401 -- the autouse fixture: buying and Skinslink switched on
    _h,
    _item,
)


async def _api_order(db: AsyncSession, customer_headers: Headers) -> tuple[Order, str, str]:
    item = await _item(db)
    user, token = await _customer(db, customer_headers, profile="cost")
    key = await keys.live_key(db, user.id)
    assert key is not None
    order, _ = await create_api_order(
        db,
        caller=ApiCaller(key=key, user=user),
        body=ApiOrderIn.model_validate(_body(item)),
        settings=cfg.get_settings(),
    )
    return order, user.id, token


async def test_refund_credits_the_usd_wallet_only(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    order, user_id, token = await _api_order(db_session, customer_headers)
    uzs_before = await user_balance(db_session, user_id)
    assert await user_usd_balance(db_session, user_id) == Decimal(50_000 - 9000)
    move(order, "buying")
    done = await refund_to_balance(
        db_session, order=order, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    assert done is True
    assert await user_usd_balance(db_session, user_id) == Decimal(50_000)
    assert await user_balance(db_session, user_id) == uzs_before
    again = await refund_to_balance(
        db_session, order=order, to_status="failed", reason="sold_out", actor="orders"
    )
    assert again is False
    assert await user_usd_balance(db_session, user_id) == Decimal(50_000)
    r = await integration_client.get(f"{ORDERS}/{order.number}", headers=_h(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refunded"
    assert r.json()["refund"] == {"amount_usd": "9.000", "reason": "sold_out"}


async def test_the_refund_log_names_dollars_for_an_api_order(
    customer_headers: Headers, db_session: AsyncSession
) -> None:
    order, _, _ = await _api_order(db_session, customer_headers)
    move(order, "buying")
    with capture_logs() as logs:
        await refund_to_balance(
            db_session, order=order, to_status="failed", reason="sold_out", actor="orders"
        )
    (line,) = [e for e in logs if e["event"] == "orders.refunded"]
    assert line["amount_usd"] == str(order.price_usd)
    assert "amount" not in line


async def test_an_api_order_gets_no_letters(
    customer_headers: Headers, db_session: AsyncSession
) -> None:
    order, _, _ = await _api_order(db_session, customer_headers)
    await enqueue_receipt(db_session, order)
    await enqueue_trade_sent(db_session, order)
    await enqueue_refunded(db_session, order)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(EmailOutbox)) == 0


async def test_a_site_order_still_gets_its_letters(db_session: AsyncSession) -> None:
    order = await make_order(db_session, status="paid", paid_with="payme")
    await enqueue_receipt(db_session, order)
    await enqueue_trade_sent(db_session, order)
    await enqueue_refunded(db_session, order)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(EmailOutbox)) == 3
