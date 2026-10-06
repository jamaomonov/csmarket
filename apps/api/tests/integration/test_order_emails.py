"""Order letters: enqueued with their event, once; sent to a verified buyer (M4b T4, R5).

``mark_paid`` → ``receipt``; ``trades.apply`` → ``trade_sent`` (not when the order jumps
straight to ``delivered``); ``refund_to_balance`` → ``refunded`` (not when held or
replayed). The drain renders each in the buyer's locale through the dev transport.
"""

from __future__ import annotations

import json

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.dev_transport import DEV_MAIL_KEY, DevTransport
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.notifications.sender import drain_emails
from csmarket.modules.orders.letters import enqueue_trade_sent
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.payments.hooks import ensure_attempt, settle
from csmarket.modules.payments.payable import resolve
from csmarket.modules.users.models import User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.trade_sweeps_kit import (  # noqa: F401 -- fixtures
    buying_order_fixture,
    clock_fixture,
    db_fixture,
    fake_fixture,
    reconcile_once,
    set_trade,
    trade,
    trade_sent_order_fixture,
)

ADDRESS = "buyer@example.test"


async def _kinds(db: AsyncSession, order: Order) -> list[str]:
    rows = await db.scalars(
        select(EmailOutbox.kind).where(EmailOutbox.order_id == order.id).order_by("created_at")
    )
    return list(rows)


async def _verify_buyer(db: AsyncSession, user_id: str, *, locale: str = "ru") -> None:
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(email=ADDRESS, email_verified_at=core_clock.now(), locale=locale)
    )
    await db.commit()


async def _letters() -> list[dict[str, str]]:
    return [json.loads(x) for x in await get_redis().lrange(DEV_MAIL_KEY, 0, -1)]


async def test_replayed_paid_enqueues_one_receipt(db: AsyncSession) -> None:
    order = await make_order(db, status="pending")
    attempt = await ensure_attempt(
        db, payable=await resolve(db, order.number, lock=True), provider="mock"
    )
    await settle(db, payment=attempt, event_id="e1")
    await db.commit()
    await settle(db, payment=attempt, event_id="e1")  # the kassa retries its callback
    await db.commit()
    assert await _kinds(db, order) == ["receipt"]
    row = await db.scalar(select(EmailOutbox).where(EmailOutbox.order_id == order.id))
    assert row is not None
    assert row.payload == {"number": order.number, "skin": order.market_hash_name}
    assert row.address is None


async def test_trade_sent_is_enqueued_once_with_its_deadline(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    waxpeer_id = 70_000_002
    await set_trade(db, buying_order, waxpeer_id=waxpeer_id, buy_pending=False)
    fake.lookup_returns([trade(project_id=buying_order.id, status=4, id=waxpeer_id)])
    await reconcile_once(db, fake)
    await reconcile_once(db, fake)  # the same report again: no second letter
    assert await _kinds(db, buying_order) == ["trade_sent"]
    row = await db.scalar(select(EmailOutbox).where(EmailOutbox.order_id == buying_order.id))
    assert row is not None
    assert row.payload["send_until"] == "2026-10-02T13:00:00+00:00"


async def test_a_jump_straight_to_delivered_sends_no_trade_letter(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    waxpeer_id = 70_000_003
    await set_trade(db, buying_order, waxpeer_id=waxpeer_id, buy_pending=False)
    fake.lookup_returns(
        [
            trade(
                project_id=buying_order.id,
                status=4,
                id=waxpeer_id,
                release_date="2026-10-09T00:00:00Z",
            )
        ]
    )
    await reconcile_once(db, fake)
    assert await _kinds(db, buying_order) == []


async def test_a_refund_enqueues_one_letter_with_its_amount(db: AsyncSession) -> None:
    order = await make_order(db, status="buying", paid_with="wallet", paid_at=core_clock.now())
    locked = await db.get(Order, order.id, with_for_update=True)
    assert locked is not None
    assert await refund_to_balance(
        db, order=locked, to_status="failed", reason="sold_out", actor="orders"
    )
    assert not await refund_to_balance(
        db, order=locked, to_status="failed", reason="sold_out", actor="orders"
    )
    await db.commit()
    assert await _kinds(db, order) == ["refunded"]
    row = await db.scalar(select(EmailOutbox).where(EmailOutbox.order_id == order.id))
    assert row is not None
    assert row.payload["amount_uzs"] == str(order.price_uzs)


async def test_a_held_refund_enqueues_nothing(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    await set_trade(db, trade_sent_order, attention_reason="ambiguous_trade")
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=6, done=True)])
    await reconcile_once(db, fake)
    assert await _kinds(db, trade_sent_order) == []


@pytest.mark.parametrize("locale", ["ru", "uz", "en"])
async def test_each_order_letter_reaches_a_verified_buyer_in_their_locale(
    db: AsyncSession, locale: str
) -> None:
    order = await make_order(db, status="pending")
    number, user_id = order.number, order.user_id
    await _verify_buyer(db, user_id, locale=locale)
    attempt = await ensure_attempt(
        db, payable=await resolve(db, number, lock=True), provider="mock"
    )
    await settle(db, payment=attempt, event_id="e1")
    await db.commit()
    await db.execute(update(Order).where(Order.id == order.id).values(status="trade_sent"))
    sent = await make_trade(db, order, status=4, send_until=core_clock.now())
    locked = await db.get(Order, order.id, with_for_update=True)
    assert locked is not None
    await enqueue_trade_sent(db, locked, sent)
    await refund_to_balance(
        db, order=locked, to_status="returned", reason="not_accepted", actor="orders"
    )
    await db.commit()
    assert await drain_emails(db, transport=DevTransport(get_redis())) == 3
    letters = await _letters()
    assert sorted(m["kind"] for m in letters) == ["receipt", "refunded", "trade_sent"]
    prefix = {"ru": "", "uz": "/uz", "en": "/en"}[locale]
    for letter in letters:
        assert letter["to_user"] == user_id
        assert number in letter["subject"]
        link = "/account/transactions" if letter["kind"] == "refunded" else f"/orders/{number}"
        assert f"{prefix}{link}" in letter["text"]
    receipt = next(m for m in letters if m["kind"] == "receipt")
    expected = {"ru": "Оплата получена", "uz": "Toʻlov qabul qilindi", "en": "Payment received"}
    assert expected[locale] in receipt["text"]


async def test_a_buyer_who_changed_email_after_verifying_is_skipped(db: AsyncSession) -> None:
    order = await make_order(db, status="pending")
    await _verify_buyer(db, order.user_id)
    attempt = await ensure_attempt(
        db, payable=await resolve(db, order.number, lock=True), provider="mock"
    )
    await settle(db, payment=attempt, event_id="e1")
    await db.commit()
    # A new address resets the verification (users.service, PATCH /me).
    await db.execute(
        update(User)
        .where(User.id == order.user_id)
        .values(email="new@example.test", email_verified_at=None)
    )
    await db.commit()
    await drain_emails(db, transport=DevTransport(get_redis()))
    row = await db.scalar(select(EmailOutbox).where(EmailOutbox.order_id == order.id))
    assert row is not None
    assert row.status == "skipped"
    assert await _letters() == []
