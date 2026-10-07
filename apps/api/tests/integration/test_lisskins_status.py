"""``orders.lisskins_status.apply_report``: spec 2026-10-07 §6 row by row, and the buyer's
card for a LIS-SKINS order."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.lisskins.api import Purchase
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.lisskins_status import apply_report
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.trade_view import skin_trade_out
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_lisskins_client import purchase
from tests.integration.lisskins_factory import OFFER, PRICE, make_lisskins_order

EXPIRY = "2026-10-07T19:50:35.000000Z"


async def _apply(
    db: AsyncSession, order: Order, report: Purchase
) -> tuple[str, Order, LisskinsPurchase]:
    locked = await db.scalar(
        select(Order)
        .where(Order.id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    p = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert locked is not None
    assert p is not None
    outcome = await apply_report(db, order=locked, purchase=p, report=report)
    await db.commit()
    return outcome, locked, p


async def test_processing_changes_nothing(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status=None)
    outcome, row, p = await _apply(db_session, order, purchase("processing", custom_id=order.id))
    assert (outcome, row.status, p.status, p.amount_units) == (
        "unchanged",
        "buying",
        "processing",
        12_340,
    )


async def test_wait_accept_sends_the_trade_with_its_deadline(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status=None)
    report = purchase("wait_accept", custom_id=order.id, offer_id=OFFER, offer_expiry_at=EXPIRY)
    outcome, row, p = await _apply(db_session, order, report)
    assert (outcome, row.status, p.steam_trade_offer_id) == ("trade_sent", "trade_sent", OFFER)
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None
    assert card.state == "offer_sent"
    assert card.offer_url == f"https://steamcommunity.com/tradeoffer/{OFFER}/"
    assert card.send_until is not None
    assert card.send_until.isoformat().startswith("2026-10-07T19:50:35")


async def test_accepted_delivers(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session)
    outcome, row, p = await _apply(db_session, order, purchase("accepted", custom_id=order.id))
    assert (outcome, row.status) == ("delivered", "delivered")
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None
    assert card.state == "accepted"


@pytest.mark.parametrize("reason", ["trade_timeout", "trade_canceled", "manual_cancel"])
async def test_a_trade_not_accepted_is_returned_and_refunded(
    db_session: AsyncSession, reason: str
) -> None:
    order, _ = await make_lisskins_order(db_session)
    report = purchase("return", custom_id=order.id, return_reason=reason)
    outcome, row, p = await _apply(db_session, order, report)
    assert (outcome, row.status, row.failure_reason) == ("returned", "returned", "not_accepted")
    assert await user_balance(db_session, order.user_id) == PRICE
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None
    assert (card.state, card.reason_code) == ("failed", "not_accepted")


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("private_inventory", "invalid_trade_link"),
        ("user_inventory_full", "invalid_trade_link"),
        ("unknown_error", "sold_out"),
        (None, "sold_out"),
    ],
)
async def test_a_trade_that_could_not_be_created_fails_and_refunds(
    db_session: AsyncSession, error: str | None, reason: str
) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status="processing")
    report = purchase("return", custom_id=order.id, return_reason="trade_create_error", error=error)
    outcome, row, _ = await _apply(db_session, order, report)
    assert (outcome, row.status, row.failure_reason) == ("failed", "failed", reason)
    assert await user_balance(db_session, order.user_id) == PRICE


@pytest.mark.parametrize("reason", ["rollback_user", "rollback_" + "supplier"])
async def test_a_rollback_is_an_attention_never_a_refund(
    db_session: AsyncSession, reason: str
) -> None:
    order, _ = await make_lisskins_order(db_session, status="delivered", skin_status="accepted")
    report = purchase("return", custom_id=order.id, return_reason=reason)
    outcome, row, p = await _apply(db_session, order, report)
    assert (outcome, row.status, p.attention_reason) == ("rolled_back", "delivered", "rolled_back")
    assert await user_balance(db_session, order.user_id) == Decimal(0)
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None
    assert card.reason_code == "support"
    assert (await _apply(db_session, order, report))[0] == "unchanged"  # already open


@pytest.mark.parametrize("status", ["wait_unlock", "wait_withdraw"])
async def test_a_locked_lot_is_ambiguous(db_session: AsyncSession, status: str) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status=None)
    outcome, row, p = await _apply(db_session, order, purchase(status, custom_id=order.id))
    assert (outcome, row.status, p.attention_reason) == ("ambiguous", "buying", "ambiguous_trade")


async def test_a_refund_an_attention_blocks_is_held(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, attention_reason="buy_unconfirmed")
    report = purchase("return", custom_id=order.id, return_reason="trade_timeout")
    outcome, row, _ = await _apply(db_session, order, report)
    assert (outcome, row.status) == ("held", "trade_sent")
