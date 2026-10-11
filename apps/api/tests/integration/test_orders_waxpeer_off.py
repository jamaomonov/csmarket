"""``CSMARKET_WAXPEER_BUY_ENABLED=false`` stops every new Waxpeer buy (WAX-02, ADR-0007).

The switch is read where a buy would start — the worker's drain, the reconcile sweep, an
admin's retry — and where money would come in for a Waxpeer order (``POST /orders/{n}/pay``).
A paid Waxpeer order with no buy at Waxpeer (the ``project_id`` lookup finds none) is refunded
to the balance as ``sold_out``; a buy that did happen is still adopted by lookup — a lookup
is not a buy. A scripted Waxpeer stands in; the database is real.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.modules.orders.api import Order, attempt_buy, drain_paid
from csmarket.modules.skins.api import WaxpeerUnavailableError
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_topup, user_balance
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.fake_trade_client import FakeTradeClient, waxpeer_trade
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.trade_sweeps_kit import load, reconcile_once

pytestmark = pytest.mark.asyncio

PRICE = Decimal(171_800)


@pytest.fixture(autouse=True)
def _waxpeer_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_WAXPEER_BUY_ENABLED", "false")
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "test-key-not-real")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _buying(db: AsyncSession, **trade: Any) -> Order:
    """A kassa-paid Waxpeer order in ``buying`` with its buy pending."""
    order = await make_order(
        db, status="buying", paid_with="payme", paid_at=clock.now(), price_uzs=PRICE
    )
    await make_trade(db, order, **{"buy_pending": True, **trade})
    return order


async def test_a_pending_buy_is_refunded_never_bought(db_session: AsyncSession) -> None:
    order = await _buying(db_session)
    fake = FakeTradeClient()
    fake.buy_raises(AssertionError("must not buy while Waxpeer buying is off"))
    assert await attempt_buy(db_session, fake, order_id=order.id) == "sold_out"
    assert (fake.lookup_calls, fake.buy_calls) == (1, 0)
    row, trade = await load(db_session, order)
    assert (row.status, row.failure_reason, row.refunded_to) == ("failed", "sold_out", "balance")
    assert trade.buy_pending is False
    assert await user_balance(db_session, row.user_id) == PRICE


async def test_a_buy_that_did_happen_is_still_adopted(db_session: AsyncSession) -> None:
    order = await _buying(db_session)
    fake = FakeTradeClient()
    fake.lookup_returns([waxpeer_trade(order.id, status=2)])
    fake.buy_raises(AssertionError("must not buy"))
    assert await attempt_buy(db_session, fake, order_id=order.id) == "adopted"
    row, trade = await load(db_session, order)
    assert row.refunded_at is None
    assert (trade.status, trade.buy_pending) == (2, False)


async def test_a_failed_lookup_neither_buys_nor_refunds(db_session: AsyncSession) -> None:
    """Retryable: nothing is known yet, so nothing is decided — the lookup runs again."""
    order = await _buying(db_session)
    fake = FakeTradeClient()
    fake.lookup_raises(WaxpeerUnavailableError("down"))
    assert await attempt_buy(db_session, fake, order_id=order.id) == "lookup_later"
    row, trade = await load(db_session, order)
    assert (row.status, row.refunded_at, trade.buy_pending) == ("buying", None, True)
    assert fake.buy_calls == 0


async def test_a_lost_answer_is_parked_for_the_lookup_not_refunded(
    db_session: AsyncSession,
) -> None:
    order = await _buying(db_session, buy_unconfirmed_at=clock.now() - timedelta(minutes=1))
    fake = FakeTradeClient()
    assert await attempt_buy(db_session, fake, order_id=order.id) != "sold_out"
    row, _ = await load(db_session, order)
    assert row.refunded_at is None
    assert fake.buy_calls == 0


async def test_the_worker_drain_buys_nothing(db_session: AsyncSession) -> None:
    order = await make_order(
        db_session, status="paid", paid_with="payme", paid_at=clock.now(), price_uzs=PRICE
    )
    fake = FakeTradeClient()
    assert await drain_paid(db_session, client=fake, settings=cfg.get_settings()) == 1
    assert fake.buy_calls == 0
    row, _ = await load(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", "sold_out")


async def test_the_reconcile_sweep_buys_nothing(db_session: AsyncSession) -> None:
    order = await _buying(db_session)
    fake = FakeTradeClient()
    await reconcile_once(db_session, fake)
    assert fake.buy_calls == 0
    row, _ = await load(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", "sold_out")


async def test_an_admin_retry_is_refused(
    integration_client: AsyncClient, admin_headers: Any, db_session: AsyncSession
) -> None:
    order = await _buying(
        db_session,
        buy_pending=False,
        attention_reason="source_forbidden",
        resolved_at=clock.now() - timedelta(minutes=1),
        resolved_by="an-earlier-admin",
    )
    h = await admin_headers()
    r = await integration_client.post(
        f"/api/v1/admin/orders/{order.number}/retry",
        headers={**h, "Idempotency-Key": f"retry-{uuid.uuid4()}"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "waxpeer_buy_off"
    _, trade = await load(db_session, order)
    assert (trade.buy_pending, trade.attention_reason) == (False, "source_forbidden")


@pytest.mark.parametrize("provider", ["wallet", "mock"])
async def test_a_waxpeer_order_cannot_be_paid(
    integration_client: AsyncClient, db_session: AsyncSession, provider: str
) -> None:
    headers = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    buyer = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert buyer is not None
    await credit_topup(
        db_session, user_id=buyer.id, topup_id=str(uuid.uuid4()), amount=PRICE, provider="mock"
    )
    await db_session.commit()
    order = await make_order(db_session, user=buyer, price_uzs=PRICE)
    r = await integration_client.post(
        f"/api/v1/orders/{order.number}/pay",
        headers={**headers, "Idempotency-Key": f"pay-{uuid.uuid4()}"},
        json={"provider": provider, "locale": "ru"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "buying_disabled"
    assert await user_balance(db_session, buyer.id) == PRICE
    row = await db_session.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    assert row is not None
    assert row.status == "pending"
