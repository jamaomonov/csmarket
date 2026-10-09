"""``POST /public/orders`` for a LIS-SKINS lot: one live ``check-availability`` before the
wallet is debited (the snapshot can be minutes old). A sold lot is ``offer_gone`` for a named
offer, the next cheapest for «cheapest within max»; a dearer live price is re-quoted (and
``price_above_max`` past the cap); a failed call accepts the snapshot; other sources are never
checked. No substitute lot is ever bought: the partner chose this one (owner, 2026-10-10)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import (
    Availability,
    LisskinsUnavailableError,
    availability_client,
)
from csmarket.modules.lisskins.availability import BREAKER_KEY
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.orders.models import Order
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.offers import api_offers
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import admin_adjust_usd, user_usd_balance
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.fake_lisskins_client import FakeAvailability
from tests.integration.orders_factory import FAKE_TRADE_LINK, make_item_and_rate

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
Live = Callable[[Availability | Exception], FakeAvailability]
ORDERS = "/api/v1/public/orders"
ADMIN = "00000000-0000-4000-8000-000000000001"
LOT = 553_846_266
FUNDS = 50_000


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINS_BUY_ENABLED": "true",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
        "LISSKINS_ENABLED": "true",
        "LISSKINS_API_KEY": "k",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
def live(integration_app: FastAPI) -> Iterator[Live]:
    def use(answer: Availability | Exception) -> FakeAvailability:
        fake = FakeAvailability(answer)
        integration_app.dependency_overrides[availability_client] = lambda: fake
        return fake

    yield use
    integration_app.dependency_overrides.pop(availability_client, None)


async def _item(db: AsyncSession) -> SkinItem:
    """An item whose cheapest lot is LIS-SKINS' ($4.000), then a Skinslink one ($4.100)."""
    item, _ = await make_item_and_rate(db)
    item.active = True
    at = datetime.now(UTC)
    db.add_all(
        [
            LisskinsState(id=1, snapshot_at=at, lots=1),
            LisskinsOffer(id=LOT, skin_item_id=item.id, price_units=4_000, asset_id="9"),
            SkinslinkState(id=1, cursor="c", mirror_synced_at=at),
            SkinslinkItem(
                id="380",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=4_100,
                skin_item_id=item.id,
            ),
        ]
    )
    await db.commit()
    await db.refresh(item)
    return item


async def _token(db: AsyncSession, customer_headers: Headers) -> tuple[User, str]:
    """The customer on the ``cost`` tariff (price = cost), the USD wallet funded, a key."""
    await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    user.usd_wallet_enabled = True
    key, token = await keys.issue(db, user=user)
    key.pricing_profile = "cost"
    await db.commit()
    await admin_adjust_usd(
        db,
        user_id=user.id,
        amount=Decimal(FUNDS),
        reason="seed",
        admin_id=ADMIN,
        idempotency_key="seed-ls",
    )
    await db.commit()
    return user, token


async def _lot_id(db: AsyncSession, item: SkinItem) -> str:
    priced = await api_offers(
        db, item, profile="cost", settings=cfg.get_settings(), now=datetime.now(UTC)
    )
    return next(p.public_id for p in priced if p.offer.source == "lisskins")


def _body(item: SkinItem, **extra: object) -> dict[str, object]:
    return {
        "item_id": item.id,
        "max_price_usd": "10",
        "trade_link": FAKE_TRADE_LINK,
        "client_order_id": "c-1",
        **extra,
    }


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _orders(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Order)) or 0)


async def test_a_sold_named_lot_is_offer_gone_and_nothing_is_debited(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    user, token = await _token(db_session, customer_headers)
    fake = live(Availability(available={}, unavailable=frozenset({LOT})))
    r = await integration_client.post(
        ORDERS, json=_body(item, offer_id=await _lot_id(db_session, item)), headers=_h(token)
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "offer_gone"
    assert fake.calls == [[LOT]]
    assert await _orders(db_session) == 0
    assert await user_usd_balance(db_session, user.id) == Decimal(FUNDS)


async def test_cheapest_within_max_skips_a_sold_lot(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    user, token = await _token(db_session, customer_headers)
    live(Availability(available={}, unavailable=frozenset({LOT})))
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 201, r.text
    order = await db_session.scalar(select(Order).where(Order.number == r.json()["order_id"]))
    assert order is not None
    assert (order.source, order.cost_units) == ("skinslink", 4_100)
    assert await user_usd_balance(db_session, user.id) == Decimal(FUNDS - 4_100)


async def test_a_dearer_live_price_is_billed(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    user, token = await _token(db_session, customer_headers)
    live(Availability(available={LOT: Decimal("4.5")}, unavailable=frozenset()))
    r = await integration_client.post(
        ORDERS, json=_body(item, offer_id=await _lot_id(db_session, item)), headers=_h(token)
    )
    assert r.status_code == 201, r.text
    assert r.json()["price_usd"] == "4.500"
    order = await db_session.scalar(select(Order).where(Order.number == r.json()["order_id"]))
    assert order is not None
    assert (order.source, order.cost_units) == ("lisskins", 4_500)
    assert await user_usd_balance(db_session, user.id) == Decimal(FUNDS - 4_500)


async def test_a_live_price_past_the_cap_is_price_above_max(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    user, token = await _token(db_session, customer_headers)
    live(Availability(available={LOT: Decimal("4.5")}, unavailable=frozenset()))
    r = await integration_client.post(
        ORDERS,
        json=_body(item, offer_id=await _lot_id(db_session, item), max_price_usd="4.2"),
        headers=_h(token),
    )
    assert r.status_code == 409, r.text
    assert (r.json()["code"], r.json()["price_usd"]) == ("price_above_max", "4.500")
    assert await _orders(db_session) == 0
    assert await user_usd_balance(db_session, user.id) == Decimal(FUNDS)


async def test_no_answer_accepts_the_snapshot(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    _, token = await _token(db_session, customer_headers)
    live(LisskinsUnavailableError("down"))
    try:
        r = await integration_client.post(
            ORDERS, json=_body(item, offer_id=await _lot_id(db_session, item)), headers=_h(token)
        )
        assert r.status_code == 201, r.text
        assert r.json()["price_usd"] == "4.000"
    finally:
        await get_redis().delete(BREAKER_KEY)


async def test_another_source_is_never_checked(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    _, token = await _token(db_session, customer_headers)
    fake = live(Availability(available={}, unavailable=frozenset({LOT})))
    priced = await api_offers(
        db_session, item, profile="cost", settings=cfg.get_settings(), now=datetime.now(UTC)
    )
    sl = next(p.public_id for p in priced if p.offer.source == "skinslink")
    r = await integration_client.post(ORDERS, json=_body(item, offer_id=sl), headers=_h(token))
    assert r.status_code == 201, r.text
    assert fake.calls == []


async def test_a_link_lisskins_refused_never_buys_its_lots(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    from csmarket.modules.lisskins.api import remember_rejection
    from csmarket.modules.users.api import parse_tradelink

    item = await _item(db_session)
    user, token = await _token(db_session, customer_headers)
    fake = live(Availability(available={LOT: Decimal("4")}, unavailable=frozenset()))
    await remember_rejection(get_redis(), parse_tradelink(FAKE_TRADE_LINK).url)
    named = await integration_client.post(
        ORDERS, json=_body(item, offer_id=await _lot_id(db_session, item)), headers=_h(token)
    )
    assert named.status_code == 409, named.text
    assert named.json()["code"] == "trade_link_rejected"
    assert await _orders(db_session) == 0
    cheapest = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert cheapest.status_code == 201, cheapest.text
    order = await db_session.scalar(
        select(Order).where(Order.number == cheapest.json()["order_id"])
    )
    assert order is not None
    assert order.source == "skinslink"
    assert fake.calls == []
    assert await user_usd_balance(db_session, user.id) == Decimal(FUNDS - 4_100)
