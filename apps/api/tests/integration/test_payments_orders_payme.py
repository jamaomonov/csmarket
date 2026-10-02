"""Payme pays an order (M4a): over HTTP with M3's JSON-RPC builders.

``account.order`` is the order number; the amount is its ``price_uzs`` in tiyin. A performed
order transaction can never be cancelled (ruling R7: −31007). Every key here is fake.
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
from tests.integration.test_payme_merchant import (  # M3's builders and env
    TIME,
    _call,
    _code,
    _payme_env,  # noqa: F401 -- autouse fixture: the Payme credentials
    _payment_status,
    _txn,
)

PRICE = Decimal(171_800)
TIYIN = 17_180_000


def _params(number: str, payme_id: str, amount: int = TIYIN) -> dict[str, Any]:
    return {"id": payme_id, "time": TIME, "amount": amount, "account": {"order": number}}


async def _order(db: AsyncSession, order_id: str) -> Order:
    stmt = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def test_check_create_perform_pay_the_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    check = await _call(
        integration_client,
        "CheckPerformTransaction",
        {"amount": TIYIN, "account": {"order": order.number}},
    )
    assert check["result"] == {"allow": True}
    created = await _call(integration_client, "CreateTransaction", _params(order.number, "o1"))
    assert created["result"]["state"] == 1
    performed = await _call(integration_client, "PerformTransaction", {"id": "o1"})
    assert performed["result"]["state"] == 2
    paid = await _order(db_session, order.id)
    assert (paid.status, paid.paid_with) == ("paid", "payme")
    assert await _payment_status(db_session, (await _txn(db_session, "o1")).payment_id) == (
        "succeeded"
    )


async def test_the_amount_must_be_the_order_price_in_tiyin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    for amount in (TIYIN + 1, int(PRICE)):  # off by a tiyin; soʻm instead of tiyin
        body = await _call(
            integration_client, "CreateTransaction", _params(order.number, "amt", amount)
        )
        assert _code(body) == -31001


async def test_a_paid_order_refuses_a_second_charge(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    paid = await make_order(db_session, price_uzs=PRICE, status="paid")
    body = await _call(integration_client, "CreateTransaction", _params(paid.number, "again"))
    assert _code(body) == -31051

    order = await make_order(db_session, price_uzs=PRICE)
    await _call(integration_client, "CreateTransaction", _params(order.number, "elsewhere"))
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:elsewhere")
    await db_session.commit()
    body = await _call(integration_client, "PerformTransaction", {"id": "elsewhere"})
    assert _code(body) == -31008
    txn = await _txn(db_session, "elsewhere")
    assert (txn.state, txn.reason) == (-1, 3)
    assert (await _order(db_session, order.id)).paid_with == "mock"


async def test_payme_cancel_of_performed_order_is_31007(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await _call(integration_client, "CreateTransaction", _params(order.number, "done"))
    await _call(integration_client, "PerformTransaction", {"id": "done"})

    body = await _call(integration_client, "CancelTransaction", {"id": "done", "reason": 5})
    assert _code(body) == -31007
    txn = await _txn(db_session, "done")
    assert txn.state == 2
    assert await _payment_status(db_session, txn.payment_id) == "succeeded"
    assert (await _order(db_session, order.id)).status == "paid"


async def test_cancel_before_perform_releases_the_attempt_and_keeps_the_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await _call(integration_client, "CreateTransaction", _params(order.number, "drop"))
    body = await _call(integration_client, "CancelTransaction", {"id": "drop", "reason": 3})
    assert body["result"]["state"] == -1
    txn = await _txn(db_session, "drop")
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
        check = await _call(
            integration_client,
            "CheckPerformTransaction",
            {"amount": TIYIN, "account": {"order": order.number}},
        )
        assert _code(check) == -31051
        create = await _call(
            integration_client, "CreateTransaction", _params(order.number, f"x-{order.number}")
        )
        assert _code(create) == -31051


async def test_a_cancelled_orders_late_perform_is_refused(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await _call(integration_client, "CreateTransaction", _params(order.number, "late"))
    await cancel_while_held(db_session, order)
    body = await _call(integration_client, "PerformTransaction", {"id": "late"})
    assert _code(body) == -31051  # the order is not payable, not "operation" (minor 6)
    txn = await _txn(db_session, "late")
    assert (txn.state, txn.reason) == (-1, 3)
    late = await _order(db_session, order.id)
    assert (late.status, late.paid_with) == ("cancelled", None)
