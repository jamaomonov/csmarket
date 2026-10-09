"""``orders.skinslink_buying.attempt_skinslink_buy``: one order, one purchase at Skinslink.

Idempotent on our order id (``merchant_tx_id``); one substitute of either source within the
ceiling; a lost answer is resolved by repeating the same id, never by buying again; low
balance, sold out and a broken trade link are refunded to the balance. A scripted Skinslink
stands in; the database is real.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.skinslink_buying import attempt_skinslink_buy
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.api import (
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkRateLimitedError,
    SkinslinkUnavailableError,
)
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_skinslink_client import FakeSkinslinkClient, purchase
from tests.integration.orders_factory import make_order

PRICE = Decimal(171_800)
COST = 12_345  # the ceiling is 12_345 × 1.03 → 12_715


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(
        update={
            "skinslink_enabled": True,
            "skinslink_api_key": "k",
            "skinslink_secret": "s",
            "waxpeer_api_key": "test-key-not-real",
        }
    )


async def _buying(
    db: AsyncSession, *, mirror: tuple[tuple[str, int], ...] = (("100", COST),)
) -> Order:
    """A balance-paid Skinslink order in ``buying`` with its purchase waiting to be bought."""
    order = await make_order(
        db,
        status="buying",
        paid_with="payme",
        paid_at=clock.now(),
        price_uzs=PRICE,
        source="skinslink",
        offer_id="sl:100",
        listing_id=None,
    )
    item = await db.get(SkinItem, order.skin_item_id)
    assert item is not None
    db.add_all(
        SkinslinkItem(
            id=asset,
            market_hash_name=item.market_hash_name,
            phase="",
            price_units=units,
            skin_item_id=item.id,
        )
        for asset, units in mirror
    )
    await db.merge(SkinslinkState(id=1, cursor="c", mirror_synced_at=clock.now()))
    db.add(
        SkinslinkPurchase(
            order_id=order.id,
            merchant_tx_id=order.id,
            asset_id="100",
            paid_units=COST,
            buy_pending=True,
        )
    )
    await db.commit()
    return order


async def _purchase(db: AsyncSession, order: Order) -> SkinslinkPurchase:
    row = await db.scalar(
        select(SkinslinkPurchase)
        .where(SkinslinkPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _order(db: AsyncSession, order: Order) -> Order:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def test_success_records_the_purchase_and_pays_at_most_the_cost(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(purchase("pending"))
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "bought"
    assert fake.calls == [
        {"asset_id": "100", "merchant_tx_id": order.id, "max_price_usd": Decimal("12.345")}
    ]
    p = await _purchase(db_session, order)
    assert (p.purchase_id, p.status, p.buy_pending, p.amount_units) == (
        178,
        "pending",
        False,
        12_345,
    )
    assert (await _order(db_session, order)).status == "buying"


async def test_an_active_answer_moves_the_order_to_trade_sent(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(purchase("active", offer_id="6912345678"))
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id) == ("bought")
    assert (await _order(db_session, order)).status == "trade_sent"
    assert (await _purchase(db_session, order)).offer_id == "6912345678"


async def test_a_lost_answer_is_unconfirmed_and_never_rebought(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(SkinslinkUnavailableError("timeout"))
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "unconfirmed"
    p = await _purchase(db_session, order)
    assert p.buy_unconfirmed_at is not None
    assert p.buy_pending is False
    assert len(fake.calls) == 1
    again = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert again == "nothing_to_do"


async def test_a_sold_offer_is_refunded_never_replaced(
    db_session: AsyncSession, settings: Settings
) -> None:
    """Another offer has its own float and stickers: the buyer chose this one (ADR-0013)."""
    order = await _buying(db_session, mirror=(("100", COST), ("101", COST - 100)))
    fake = FakeSkinslinkClient(purchase("failed", fail_reason="item_sold"))
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "sold_out"
    assert [c["asset_id"] for c in fake.calls] == ["100"]
    row = await _order(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", "sold_out")
    assert await user_balance(db_session, order.user_id) == PRICE


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (purchase("failed", fail_reason="insufficient_balance"), "source_low_balance"),
        (SkinslinkError("banned", status=400, code="trade_banned"), "invalid_trade_link"),
        (SkinslinkError("hold", status=400, code="hold"), "trade_hold"),
        (SkinslinkError("bad", status=400, code="validation"), "source_refused"),
        (purchase("failed", fail_reason="item_not_available"), "sold_out"),
        (purchase("failed", fail_reason="provider_unavailable"), "source_refused"),
        (SkinslinkError("broke", status=400, code="insufficient_balance"), "source_low_balance"),
    ],
)
async def test_refund_reasons(
    db_session: AsyncSession, settings: Settings, answer: object, reason: str
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(answer)
    await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    row = await _order(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", reason)


async def test_a_bad_stored_link_is_refunded_without_a_call(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    row = await _order(db_session, order)
    row.trade_link = "https://example.com/not-a-trade-link"
    await db_session.commit()
    fake = FakeSkinslinkClient()
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "invalid_link"
    assert fake.calls == []


async def test_forbidden_is_attention_and_keeps_the_buy_pending(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(SkinslinkForbiddenError("no", status=403))
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "forbidden"
    p = await _purchase(db_session, order)
    assert (p.attention_reason, p.buy_pending) == ("source_forbidden", True)


async def test_a_rate_limit_waits_with_the_buy_pending(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(SkinslinkRateLimitedError("slow down"))
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "rate_limited"
    assert (await _purchase(db_session, order)).buy_pending is True
    again = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert again == "nothing_to_do"  # the backoff holds it


@pytest.mark.parametrize(
    "answer",
    [
        SkinslinkError("dup", status=409),
        SkinslinkError("dup", status=400, code="duplicate_purchase"),
        purchase("failed", fail_reason="duplicate_purchase"),
    ],
)
async def test_a_duplicate_adopts_the_stored_purchase(
    db_session: AsyncSession, settings: Settings, answer: object
) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(
        answer, statuses={order.id: purchase("active", offer_id="1", id=180)}
    )
    outcome = await attempt_skinslink_buy(db_session, fake, order_id=order.id)
    assert outcome == "adopted"
    assert (await _purchase(db_session, order)).purchase_id == 180
    assert (await _order(db_session, order)).status == "trade_sent"
