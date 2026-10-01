"""Uzum pays an order (M4a): over HTTP with M3's request builders.

``params.order`` is the order number; ``amount`` is its ``price_uzs`` in tiyin. A confirmed
order transaction can never be reversed (ruling R7: 10017). Every credential here is fake.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from csmarket.core import clock
from csmarket.modules.orders.models import Order
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.payable import resolve
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import cancel_while_held, make_order
from tests.integration.test_uzum_webhook import (  # M3's builders and env
    SERVICE_ID,
    STAMP,
    _check_body,
    _confirm_body,
    _fail,
    _ok,
    _payment_status,
    _trans_body,
    _txn,
    _uzum_env,  # noqa: F401 -- autouse fixture: the Uzum credentials
)

PRICE = Decimal(171_800)
TIYIN = 17_180_000


def _create(number: str, trans_id: str, amount: int = TIYIN) -> dict[str, Any]:
    return {
        "serviceId": SERVICE_ID,
        "timestamp": STAMP,
        "transId": trans_id,
        "params": {"order": number},
        "amount": amount,
    }


async def _order(db: AsyncSession, order_id: str) -> Order:
    stmt = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def test_check_create_confirm_pay_the_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    check = await _ok(integration_client, "check", _check_body(order.number))
    assert check["data"]["amount"]["value"] == "171800"
    created = await _ok(integration_client, "create", _create(order.number, "u-o1"))
    assert created["status"] == "CREATED"
    confirmed = await _ok(integration_client, "confirm", _confirm_body("u-o1"))
    assert confirmed["status"] == "CONFIRMED"
    paid = await _order(db_session, order.id)
    assert (paid.status, paid.paid_with) == ("paid", "uzum")
    txn = await _txn(db_session, "u-o1")
    assert await _payment_status(db_session, txn.payment_id) == "succeeded"


async def test_the_amount_must_be_the_order_price_in_tiyin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    for i, amount in enumerate((TIYIN - 1, int(PRICE))):
        body = _create(order.number, f"u-amt-{i}", amount)
        assert await _fail(integration_client, "create", body) == 10011


async def test_a_paid_order_refuses_a_second_charge(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    paid = await make_order(db_session, price_uzs=PRICE, status="paid")
    assert await _fail(integration_client, "create", _create(paid.number, "u-again")) == 10008

    order = await make_order(db_session, price_uzs=PRICE)
    await _ok(integration_client, "create", _create(order.number, "u-elsewhere"))
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:elsewhere")
    await db_session.commit()
    assert await _fail(integration_client, "confirm", _confirm_body("u-elsewhere")) == 10008
    assert (await _txn(db_session, "u-elsewhere")).status == "FAILED"
    assert (await _order(db_session, order.id)).paid_with == "mock"


async def test_uzum_reverse_of_confirmed_order_is_10017(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await _ok(integration_client, "create", _create(order.number, "u-done"))
    await _ok(integration_client, "confirm", _confirm_body("u-done"))

    assert await _fail(integration_client, "reverse", _trans_body("u-done")) == 10017
    txn = await _txn(db_session, "u-done")
    assert txn.status == "CONFIRMED"
    assert await _payment_status(db_session, txn.payment_id) == "succeeded"
    assert (await _order(db_session, order.id)).status == "paid"


async def test_reverse_before_confirm_releases_the_attempt_and_keeps_the_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await _ok(integration_client, "create", _create(order.number, "u-drop"))
    reversed_ = await _ok(integration_client, "reverse", _trans_body("u-drop"))
    assert reversed_["status"] == "REVERSED"
    txn = await _txn(db_session, "u-drop")
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"
    assert (await _order(db_session, order.id)).status == "pending"


async def test_expired_order_is_not_payable(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    late = await make_order(
        db_session, price_uzs=PRICE, expires_at=clock.now() - timedelta(seconds=1)
    )
    cancelled = await make_order(db_session, price_uzs=PRICE, status="cancelled")
    for order in (late, cancelled):
        assert await _fail(integration_client, "check", _check_body(order.number)) == 10009
        body = _create(order.number, f"u-x-{order.number}")
        assert await _fail(integration_client, "create", body) == 10009


async def test_a_cancelled_orders_late_confirm_is_refused(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await _ok(integration_client, "create", _create(order.number, "u-late"))
    await cancel_while_held(db_session, order)
    assert await _fail(integration_client, "confirm", _confirm_body("u-late")) == 10008
    assert (await _txn(db_session, "u-late")).status == "FAILED"
    late = await _order(db_session, order.id)
    assert (late.status, late.paid_with) == ("cancelled", None)
