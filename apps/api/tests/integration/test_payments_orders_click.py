"""Click pays an order (M4a): over HTTP with M3's signed request builders.

An order's ``merchant_trans_id`` is its number; the amount is its ``price_uzs`` in soʻm.
Every key here is fake.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from csmarket.core import clock
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.orders.models import Order
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment
from csmarket.modules.payments.payable import resolve
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.test_click_webhook import (  # M3's builders and env
    COMPLETE_URL,
    PREPARE_URL,
    _click_env,  # noqa: F401 -- autouse fixture: the Click credentials
    _complete_body,
    _post,
    _prepare_body,
)

PRICE = Decimal(171_800)
PRICE_STR = "171800.00"


async def _order(db: AsyncSession, order_id: str) -> Order:
    stmt = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _txn(db: AsyncSession, click_trans_id: int) -> ClickTransaction:
    stmt = (
        select(ClickTransaction)
        .where(ClickTransaction.click_trans_id == click_trans_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _prepare(client: AsyncClient, number: str, trans_id: str, amount: str = PRICE_STR) -> int:
    body = await _post(
        client,
        PREPARE_URL,
        _prepare_body(click_trans_id=trans_id, merchant_trans_id=number, amount=amount),
    )
    error = body["error"]
    assert isinstance(error, int)
    return error


async def test_prepare_and_complete_pay_the_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    prepared = await _post(
        integration_client,
        PREPARE_URL,
        _prepare_body(click_trans_id="7001", merchant_trans_id=order.number, amount=PRICE_STR),
    )
    assert prepared["error"] == 0
    completed = await _post(
        integration_client,
        COMPLETE_URL,
        _complete_body(
            click_trans_id="7001",
            merchant_trans_id=order.number,
            merchant_prepare_id=str(prepared["merchant_prepare_id"]),
            amount=PRICE_STR,
        ),
    )
    assert completed["error"] == 0
    paid = await _order(db_session, order.id)
    assert (paid.status, paid.paid_with) == ("paid", "click")
    txn = await _txn(db_session, 7001)
    payment = await db_session.get(Payment, txn.payment_id)
    assert payment is not None
    assert (txn.status, payment.status, payment.purpose, payment.order_id) == (
        "CONFIRMED",
        "succeeded",
        "order",
        order.id,
    )


async def test_the_amount_must_be_the_order_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    assert await _prepare(integration_client, order.number, "7002", "171801.00") == -2
    assert await _prepare(integration_client, order.number, "7003", "50000.00") == -2


async def test_a_paid_order_refuses_a_second_charge(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    paid = await make_order(db_session, price_uzs=PRICE, status="paid")
    assert await _prepare(integration_client, paid.number, "7004") == -4

    order = await make_order(db_session, price_uzs=PRICE)
    prepared = await _post(
        integration_client,
        PREPARE_URL,
        _prepare_body(click_trans_id="7005", merchant_trans_id=order.number, amount=PRICE_STR),
    )
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:elsewhere")
    await db_session.commit()
    completed = await _post(
        integration_client,
        COMPLETE_URL,
        _complete_body(
            click_trans_id="7005",
            merchant_trans_id=order.number,
            merchant_prepare_id=str(prepared["merchant_prepare_id"]),
            amount=PRICE_STR,
        ),
    )
    assert completed["error"] == -4
    assert (await _txn(db_session, 7005)).status == "CANCELLED"
    assert (await _order(db_session, order.id)).paid_with == "mock"


async def test_expired_order_is_not_payable(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    late = await make_order(db_session, expires_at=clock.now() - timedelta(seconds=1))
    cancelled = await make_order(db_session, status="cancelled")
    assert await _prepare(integration_client, late.number, "7006") == -9
    assert await _prepare(integration_client, cancelled.number, "7007") == -9
    assert await _prepare(integration_client, "K7M3Q9X2", "7008") == -5  # no such order
