"""The LIS-SKINS reconcile: one ``market/info`` call for every due purchase, the unconfirmed
rule, Steam's trade protection, a failed call, a pending buy."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.config import get_settings
from csmarket.modules.lisskins.api import LisskinsError, LisskinsUnavailableError
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.orders import lisskins_reconcile
from csmarket.modules.orders.lisskins_reconcile import reconcile_lisskins
from csmarket.modules.orders.models import Order
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_lisskins_client import FakeLisskinsClient, purchase
from tests.integration.lisskins_factory import OFFER, PRICE, make_lisskins_order

SETTINGS = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


async def _tick(engine: AsyncEngine, fake: FakeLisskinsClient) -> int:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return await reconcile_lisskins(factory, fake, settings=SETTINGS)


async def _state(db: AsyncSession, order: Order) -> tuple[Order, LisskinsPurchase]:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    p = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert p is not None
    return row, p


async def test_one_info_call_for_every_open_purchase(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    a, _ = await make_lisskins_order(db_session, status="buying", skin_status="processing")
    b, _ = await make_lisskins_order(db_session)
    c, _ = await make_lisskins_order(db_session)
    fake = FakeLisskinsClient(
        infos={
            a.id: purchase("wait_accept", custom_id=a.id, offer_id=OFFER),
            b.id: purchase("accepted", custom_id=b.id),
            c.id: purchase("return", custom_id=c.id, return_reason="trade_timeout"),
        }
    )
    assert await _tick(db_engine, fake) == 3
    assert len(fake.info_calls) == 1
    assert sorted(fake.info_calls[0]) == sorted([a.id, b.id, c.id])
    assert [(await _state(db_session, o))[0].status for o in (a, b, c)] == [
        "trade_sent",
        "delivered",
        "returned",
    ]
    assert await user_balance(db_session, c.user_id) == PRICE


async def test_open_orders_are_asked_before_protected_ones(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    monkeypatch.setattr(lisskins_reconcile, "INFO_MAX_IDS", 2)
    for _ in range(2):
        await make_lisskins_order(
            db_session,
            status="delivered",
            skin_status="accepted",
            order={"delivered_at": clock.now() - timedelta(days=1)},
            last_polled_at=clock.now() - timedelta(hours=1),
        )
    fresh, _ = await make_lisskins_order(
        db_session, last_polled_at=clock.now() - timedelta(seconds=40)
    )
    fake = FakeLisskinsClient()
    await _tick(db_engine, fake)
    assert len(fake.info_calls[0]) == 2
    assert fresh.id in fake.info_calls[0]


async def test_an_unconfirmed_buy_found_is_adopted(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        buy_unconfirmed_at=clock.now() - timedelta(minutes=1),
    )
    fake = FakeLisskinsClient(
        infos={order.id: purchase("processing", custom_id=order.id, purchase_id=77)}
    )
    await _tick(db_engine, fake)
    _, p = await _state(db_session, order)
    assert (p.purchase_id, p.buy_unconfirmed_at, p.status) == (77, None, "processing")


async def test_an_unseen_buy_is_bought_again_under_the_same_custom_id_after_the_wait(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    lost = clock.now() - timedelta(minutes=get_settings().order_unconfirmed_minutes + 1)
    order, _ = await make_lisskins_order(
        db_session, status="buying", skin_status=None, purchase_id=None, buy_unconfirmed_at=lost
    )
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    await _tick(db_engine, fake)  # LIS-SKINS shows nothing under our id: due again
    _, p = await _state(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at) == (True, lost)  # the mark of a repeat stays
    await _tick(db_engine, fake)
    assert [c["custom_id"] for c in fake.calls] == [order.id]
    _, p = await _state(db_session, order)
    assert (p.buy_pending, p.purchase_id) == (False, 55)


async def test_unseen_before_the_wait_is_left_alone(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        buy_unconfirmed_at=clock.now() - timedelta(minutes=1),
    )
    fake = FakeLisskinsClient()
    await _tick(db_engine, fake)
    _, p = await _state(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None, fake.calls) == (False, True, [])


async def test_a_known_purchase_missing_from_info_is_left_alone(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(db_session)  # purchase 55, offer sent
    fake = FakeLisskinsClient()  # info answers without it
    await _tick(db_engine, fake)
    row, p = await _state(db_session, order)
    assert (row.status, p.buy_pending, p.attention_reason) == ("trade_sent", False, None)
    assert fake.calls == []
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_a_rollback_after_delivery_is_seen_by_the_protection_poll(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="delivered",
        skin_status="accepted",
        order={"delivered_at": clock.now() - timedelta(days=2)},
        last_polled_at=clock.now() - timedelta(minutes=11),
    )
    await make_lisskins_order(  # past the protection: never asked again
        db_session,
        status="delivered",
        skin_status="accepted",
        order={"delivered_at": clock.now() - timedelta(days=9)},
        last_polled_at=clock.now() - timedelta(days=1),
    )
    await make_lisskins_order(  # asked 2 minutes ago: waits
        db_session,
        status="delivered",
        skin_status="accepted",
        order={"delivered_at": clock.now() - timedelta(days=1)},
        last_polled_at=clock.now() - timedelta(minutes=2),
    )
    fake = FakeLisskinsClient(
        infos={order.id: purchase("return", custom_id=order.id, return_reason="rollback_user")}
    )
    await _tick(db_engine, fake)
    assert fake.info_calls == [[order.id]]
    row, p = await _state(db_session, order)
    assert (row.status, p.attention_reason) == ("delivered", "rolled_back")
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_a_failed_info_call_changes_nothing(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(db_session)
    fake = FakeLisskinsClient(info_error=LisskinsUnavailableError("down"))
    await _tick(db_engine, fake)
    row, p = await _state(db_session, order)
    assert (row.status, p.last_polled_at) == ("trade_sent", None)


async def test_a_pending_buy_is_bought_by_the_tick(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session, status="buying", skin_status=None, purchase_id=None, buy_pending=True
    )
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    await _tick(db_engine, fake)
    assert [c["custom_id"] for c in fake.calls] == [order.id]
    assert fake.info_calls == []  # it was not due a poll in the same tick


async def test_a_repeat_refused_for_its_lot_is_never_refunded_nor_substituted(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """The lost first buy may have taken the lot: a repeat that LIS-SKINS refuses for the lot
    (not for the ``custom_id``) proves nothing — an admin decides, nobody buys or refunds."""
    lost = clock.now() - timedelta(minutes=get_settings().order_unconfirmed_minutes + 1)
    order, _ = await make_lisskins_order(
        db_session, status="buying", skin_status=None, purchase_id=None, buy_unconfirmed_at=lost
    )
    db_session.add(  # a cheaper lot that a substitute would take
        LisskinsOffer(id=6, skin_item_id=order.skin_item_id, price_units=12_000, asset_id="6")
    )
    await db_session.merge(LisskinsState(id=1, snapshot_at=clock.now(), lots=1))
    await db_session.commit()
    before = await user_balance(db_session, order.user_id)
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    for _ in range(3):  # re-arm, the refused repeat, a later tick
        await _tick(db_engine, fake)
    assert [c["custom_id"] for c in fake.calls] == [order.id]
    row, p = await _state(db_session, order)
    assert (row.status, row.refunded_at) == ("buying", None)
    assert (p.custom_id, p.buy_pending, p.attention_reason) == (order.id, False, "buy_unconfirmed")
    assert await user_balance(db_session, order.user_id) == before


async def test_a_rolled_back_open_order_is_not_polled_forever(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """A rollback seen before ``accepted`` leaves the order to an admin: LIS-SKINS' answer is
    final, so the 200-id call never spends a slot on it again."""
    order, _ = await make_lisskins_order(
        db_session,
        skin_status="return",
        return_reason="rollback_user",
        attention_reason="rolled_back",
        resolved_at=clock.now(),
    )
    fake = FakeLisskinsClient()
    await _tick(db_engine, fake)
    assert all(order.id not in ids for ids in fake.info_calls)
    row, _ = await _state(db_session, order)
    assert (row.status, row.refunded_at) == ("trade_sent", None)
