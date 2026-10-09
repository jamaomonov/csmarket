"""API orders end only on the market's answer (spec 2026-10-09 v1.1 §5).

Pins what the Skinslink and LIS-SKINS buy paths already do, seen from an API order (USD
wallet, the partner's public status, the webhook outbox): a lost buy answer is settled by
sending the same id again; the market's own answer continues the order or refunds it; a
repeat LIS-SKINS refuses and ``market/info`` cannot explain waits for an admin; no timer
refunds anything. A scripted market stands in; the database is real.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.core.config import Settings
from csmarket.modules.lisskins.api import LisskinsError, LisskinsUnavailableError
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.api_checkout import create_api_order
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.lisskins_buying import attempt_lisskins_buy
from csmarket.modules.orders.lisskins_reconcile import reconcile_lisskins
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.skinslink_buying import attempt_skinslink_buy
from csmarket.modules.orders.skinslink_reconcile import reconcile_skinslink
from csmarket.modules.orders.skinslink_status import check_purchase
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.auth import ApiCaller
from csmarket.modules.public_api.models import ApiWebhook, ApiWebhookDelivery
from csmarket.modules.public_api.schemas import ApiOrderIn
from csmarket.modules.skinslink.api import SkinslinkError, SkinslinkUnavailableError
from csmarket.modules.skinslink.models import SkinslinkPurchase
from csmarket.modules.wallet.api import user_usd_balance
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_lisskins_client import FakeLisskinsClient
from tests.integration.fake_lisskins_client import purchase as ls_purchase
from tests.integration.fake_skinslink_client import FakeSkinslinkClient, purchase
from tests.integration.test_public_api_buy import (
    ORDERS,
    Headers,
    _body,
    _customer,
    _env,  # noqa: F401 -- the autouse fixture: buying and Skinslink switched on
    _h,
    _item,
)

FUNDS = 50_000
COST = 9000
OFFER = "6912345678"
HOOK = "https://partner.example/hook"

Shift = Callable[[timedelta], None]


@pytest.fixture
def shift() -> Iterator[Shift]:
    """Move the app clock forward by a delta (from the real now); reset after the test."""

    def _to(delta: timedelta) -> None:
        at: datetime = clock.now() + delta
        clock.set_clock(lambda: at)

    yield _to
    clock.reset_clock()


def _settings() -> Settings:
    return cfg.get_settings().model_copy(
        update={
            "skinslink_enabled": True,
            "skinslink_api_key": "k",
            "skinslink_secret": "s",
            "lisskins_enabled": True,
            "lisskins_api_key": "k",
        }
    )


def _past_the_wait() -> timedelta:
    return timedelta(minutes=cfg.get_settings().order_unconfirmed_minutes + 1)


async def _api_order(db: AsyncSession, headers: Headers, *, source: str) -> tuple[Order, str]:
    """A ``buying`` API order paid from the USD wallet, its buy pending at ``source``.

    Returns:
        The order and the partner's API key token.
    """
    item = await _item(db, (COST,))
    user, token = await _customer(db, headers, profile="cost", units=FUNDS)
    db.add(ApiWebhook(user_id=user.id, url=HOOK))
    await db.commit()
    key = await keys.live_key(db, user.id)
    assert key is not None
    order, _ = await create_api_order(
        db,
        caller=ApiCaller(key=key, user=user),
        body=ApiOrderIn.model_validate(_body(item)),
        settings=cfg.get_settings(),
    )
    move(order, "buying")
    if source == "skinslink":
        db.add(
            SkinslinkPurchase(
                order_id=order.id,
                merchant_tx_id=order.id,
                asset_id="100",
                paid_units=order.cost_units,
                buy_pending=True,
            )
        )
    else:
        order.source, order.offer_id = "lisskins", "ls:5"
        db.add(
            LisskinsPurchase(
                order_id=order.id,
                custom_id=order.id,
                skin_id=5,
                paid_units=order.cost_units,
                buy_pending=True,
            )
        )
    await db.commit()
    assert await user_usd_balance(db, user.id) == Decimal(FUNDS - COST)
    return order, token


async def _fresh(db: AsyncSession, order: Order) -> Order:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _sl(db: AsyncSession, order: Order) -> SkinslinkPurchase:
    row = await db.scalar(
        select(SkinslinkPurchase)
        .where(SkinslinkPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _ls(db: AsyncSession, order: Order) -> LisskinsPurchase:
    row = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _public(client: AsyncClient, order: Order, token: str) -> dict[str, object]:
    r = await client.get(f"{ORDERS}/{order.number}", headers=_h(token))
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


async def _events(db: AsyncSession, order: Order) -> list[str]:
    rows = await db.scalars(
        select(ApiWebhookDelivery.event)
        .where(ApiWebhookDelivery.order_id == order.id)
        .order_by(ApiWebhookDelivery.created_at)
    )
    return list(rows)


async def _lost_skinslink_buy(db: AsyncSession, order: Order, fake: FakeSkinslinkClient) -> None:
    """The first buy's answer is lost; past the wait Skinslink shows nothing under our id,
    so the same ``merchant_tx_id`` is due again."""
    assert await attempt_skinslink_buy(db, fake, order_id=order.id) == "unconfirmed"
    assert (await _sl(db, order)).buy_unconfirmed_at is not None


async def _repeat_due(db: AsyncSession, order: Order, shift: Shift) -> None:
    shift(_past_the_wait())
    silent = FakeSkinslinkClient(statuses={order.id: None})
    assert await check_purchase(db, silent, order_id=order.id, settings=_settings()) == "repeat"
    assert (await _sl(db, order)).buy_pending is True


async def test_skinslink_repeat_answered_with_the_stored_purchase_continues(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    shift: Shift,
) -> None:
    order, token = await _api_order(db_session, customer_headers, source="skinslink")
    stored = purchase("pending", merchant_tx_id=order.id)
    fake = FakeSkinslinkClient(SkinslinkUnavailableError("ReadTimeout"), stored)
    await _lost_skinslink_buy(db_session, order, fake)
    await _repeat_due(db_session, order, shift)
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id) == "bought"
    assert [c["merchant_tx_id"] for c in fake.calls] == [order.id, order.id]
    row, p = await _fresh(db_session, order), await _sl(db_session, order)
    assert (row.status, row.refunded_at) == ("buying", None)
    assert (p.purchase_id, p.buy_pending, p.buy_unconfirmed_at) == (178, False, None)
    assert (await _public(integration_client, order, token))["status"] == "buying"
    report = FakeSkinslinkClient(statuses={order.id: purchase("active", offer_id=OFFER)})
    assert await check_purchase(db_session, report, order_id=order.id) == "trade_sent"
    body = await _public(integration_client, order, token)
    assert body["status"] == "trade_sent"
    assert body["refund"] is None
    assert await user_usd_balance(db_session, row.user_id) == Decimal(FUNDS - COST)
    assert "order.refunded" not in await _events(db_session, order)


async def test_skinslink_repeat_refused_refunds_the_usd_wallet(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    shift: Shift,
) -> None:
    order, token = await _api_order(db_session, customer_headers, source="skinslink")
    fake = FakeSkinslinkClient(
        SkinslinkUnavailableError("ReadTimeout"),
        SkinslinkError("sold", status=400, code="item_not_available"),
    )
    await _lost_skinslink_buy(db_session, order, fake)
    await _repeat_due(db_session, order, shift)
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id) == "sold_out"
    row = await _fresh(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", "sold_out")
    assert row.refunded_at is not None
    assert await user_usd_balance(db_session, row.user_id) == Decimal(FUNDS)
    body = await _public(integration_client, order, token)
    assert body["status"] == "refunded"
    assert body["refund"] == {"amount_usd": "9.000", "reason": "sold_out"}
    assert "order.refunded" in await _events(db_session, order)


async def _lisskins_tick(engine: AsyncEngine, fake: FakeLisskinsClient) -> None:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    await reconcile_lisskins(factory, fake, settings=_settings())


async def _lost_lisskins_repeat_due(
    db: AsyncSession, engine: AsyncEngine, order: Order, fake: FakeLisskinsClient, shift: Shift
) -> None:
    """The first buy's answer is lost; past the wait ``market/info`` shows nothing under our
    ``custom_id``, so the same id is due again."""
    assert await attempt_lisskins_buy(db, fake, order_id=order.id) == "unconfirmed"
    shift(_past_the_wait())
    await _lisskins_tick(engine, fake)  # info: nothing under our id → due again
    p = await _ls(db, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None) == (True, True)


async def test_lisskins_repeat_seen_by_info_continues(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    shift: Shift,
) -> None:
    order, token = await _api_order(db_session, customer_headers, source="lisskins")
    fake = FakeLisskinsClient(
        LisskinsUnavailableError("ReadTimeout"),
        LisskinsError("known", status=400, code="custom_id_already_exists"),
    )
    await _lost_lisskins_repeat_due(db_session, db_engine, order, fake, shift)
    fake.infos[order.id] = ls_purchase("processing", custom_id=order.id, purchase_id=77)
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id) == "adopted"
    assert [c["custom_id"] for c in fake.calls] == [order.id, order.id]
    row, p = await _fresh(db_session, order), await _ls(db_session, order)
    assert (row.status, row.refunded_at) == ("buying", None)
    assert (p.purchase_id, p.buy_pending, p.attention_reason) == (77, False, None)
    assert (await _public(integration_client, order, token))["status"] == "buying"
    fake.infos[order.id] = ls_purchase(
        "wait_accept", custom_id=order.id, purchase_id=77, offer_id=OFFER
    )
    await _lisskins_tick(db_engine, fake)
    assert (await _public(integration_client, order, token))["status"] == "trade_sent"
    assert await user_usd_balance(db_session, row.user_id) == Decimal(FUNDS - COST)
    assert len(fake.calls) == 2


async def test_lisskins_repeat_refused_and_unseen_stays_buying(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    shift: Shift,
) -> None:
    """Owner decision 1: the first send may have bought the lot — no refund, no new buy."""
    order, token = await _api_order(db_session, customer_headers, source="lisskins")
    fake = FakeLisskinsClient(
        LisskinsUnavailableError("ReadTimeout"),
        LisskinsError("known", status=400, code="custom_id_already_exists"),
    )
    await _lost_lisskins_repeat_due(db_session, db_engine, order, fake, shift)
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id) == "unconfirmed"
    for _ in range(2):  # later ticks neither buy again nor refund
        await _lisskins_tick(db_engine, fake)
    assert [c["custom_id"] for c in fake.calls] == [order.id, order.id]
    row, p = await _fresh(db_session, order), await _ls(db_session, order)
    assert (row.status, row.refunded_at) == ("buying", None)
    assert (p.attention_reason, p.resolved_at, p.buy_pending) == ("buy_unconfirmed", None, False)
    assert await user_usd_balance(db_session, row.user_id) == Decimal(FUNDS - COST)
    body = await _public(integration_client, order, token)
    assert (body["status"], body["refund"]) == ("buying", None)
    assert "order.refunded" not in await _events(db_session, order)


async def test_no_timer_refunds(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    shift: Shift,
) -> None:
    """An unconfirmed API order a day old, Skinslink silent all along: still ``buying``."""
    order, token = await _api_order(db_session, customer_headers, source="skinslink")
    silent = FakeSkinslinkClient(
        *(SkinslinkUnavailableError("ReadTimeout") for _ in range(10)),
        statuses={order.id: None},
    )
    await _lost_skinslink_buy(db_session, order, silent)
    shift(timedelta(hours=24))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    for _ in range(4):  # each repeat is lost again; nothing ever refunds it
        await reconcile_skinslink(factory, silent, settings=_settings())
    assert {c["merchant_tx_id"] for c in silent.calls} == {order.id}
    row = await _fresh(db_session, order)
    assert (row.status, row.refunded_at, row.failure_reason) == ("buying", None, None)
    assert await user_usd_balance(db_session, row.user_id) == Decimal(FUNDS - COST)
    body = await _public(integration_client, order, token)
    assert (body["status"], body["refund"]) == ("buying", None)
    assert "order.refunded" not in await _events(db_session, order)
