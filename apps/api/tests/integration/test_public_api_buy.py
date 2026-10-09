"""Buying over the public API from the USD wallet (plan B, Task 5; spec 2026-10-09 §5)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders import api_checkout
from csmarket.modules.orders.api_checkout import create_api_order
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.public_view import public_order
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.auth import ApiCaller
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.public_api.offers import api_offers
from csmarket.modules.public_api.schemas import ApiOrderIn
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust_usd,
    user_usd_balance,
)
from csmarket.modules.wallet.models import WalletPosting
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.orders_factory import FAKE_TRADE_LINK, make_item_and_rate
from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
ORDERS = "/api/v1/public/orders"
ADMIN = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINS_BUY_ENABLED": "true",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _item(db: AsyncSession, prices: tuple[int, ...] = (9000,)) -> SkinItem:
    """An active item with one Skinslink offer per price."""
    item, _ = await make_item_and_rate(db)
    item.active = True
    for units in prices:
        db.add(
            SkinslinkItem(
                id=str(38_000_000_000 + int(uuid4().int % 1_000_000_000)),
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=units,
                skin_item_id=item.id,
            )
        )
    if await db.get(SkinslinkState, 1) is None:
        db.add(SkinslinkState(id=1, cursor="c", mirror_synced_at=datetime.now(UTC)))
    await db.commit()
    await db.refresh(item)
    return item


async def _fund(db: AsyncSession, user_id: str, units: int) -> None:
    await admin_adjust_usd(
        db,
        user_id=user_id,
        amount=Decimal(units),
        reason="seed",
        admin_id=ADMIN,
        idempotency_key=f"seed-{uuid4()}",
    )
    await db.commit()


async def _customer(
    db: AsyncSession, customer_headers: Headers, *, profile: str = "retail", units: int = 50_000
) -> tuple[User, str]:
    """The signed-in customer with the USD wallet on, ``units`` in it and a key."""
    await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    user.usd_wallet_enabled = True
    key, token = await keys.issue(db, user=user)
    key.pricing_profile = profile
    await db.commit()
    if units:
        await _fund(db, user.id, units)
    return user, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _offer_ids(db: AsyncSession, item: SkinItem, profile: str = "retail") -> list[str]:
    priced = await api_offers(
        db, item, profile=profile, settings=cfg.get_settings(), now=datetime.now(UTC)
    )
    return [p.public_id for p in priced]


def _body(item: SkinItem, cid: str = "c-1", **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "item_id": item.id,
        "max_price_usd": "100",
        "trade_link": FAKE_TRADE_LINK,
        "client_order_id": cid,
    }
    body.update(extra)
    return body


async def _orders(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Order)) or 0)


async def _postings(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(WalletPosting)) or 0)


async def test_buy_an_offer(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    user, token = await _customer(db_session, customer_headers, profile="cost")
    [offer] = await _offer_ids(db_session, item, "cost")
    r = await integration_client.post(
        ORDERS, json=_body(item, offer_id=offer, max_price_usd="9"), headers=_h(token)
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "buying"
    assert body["price_usd"] == "9.000"
    assert body["client_order_id"] == "c-1"
    assert body["item"] == {
        "item_id": item.id,
        "slug": item.slug,
        "market_hash_name": item.market_hash_name,
    }
    assert body["trade"] is None
    assert body["refund"] is None
    assert "skinslink" not in r.text.lower()
    assert "sl:" not in r.text
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000 - 9000)
    order = await db_session.scalar(select(Order).where(Order.number == body["order_id"]))
    assert order is not None
    assert order.channel == "api"
    assert order.source == "skinslink"
    assert order.status == "paid"
    assert order.paid_with == "usd_wallet"
    assert order.price_uzs == 0
    assert order.fx_uplift_pct == 0
    assert order.price_usd == Decimal("9")
    assert order.cost_units == 9000
    assert order.pricing_profile == "cost"
    assert order.client_order_id == "c-1"
    assert order.trade_link == FAKE_TRADE_LINK
    assert order.offer_id is not None
    assert order.offer_id.startswith("sl:")


async def test_retail_charges_the_storefront_quote(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    user, token = await _customer(db_session, customer_headers)
    priced = await api_offers(
        db_session, item, profile="retail", settings=cfg.get_settings(), now=datetime.now(UTC)
    )
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 201, r.text
    assert priced[0].price_units > 9000
    assert r.json()["price_usd"] == f"{Decimal(priced[0].price_units) / 1000:.3f}"
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000 - priced[0].price_units)


async def test_without_offer_id_the_cheapest_under_max(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, (12_000, 9000, 10_000))
    _, token = await _customer(db_session, customer_headers, profile="cost")
    r = await integration_client.post(
        ORDERS, json=_body(item, max_price_usd="9.5"), headers=_h(token)
    )
    assert r.status_code == 201, r.text
    assert r.json()["price_usd"] == "9.000"


async def test_max_below_the_cheapest_writes_nothing(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, (9000, 10_000))
    user, token = await _customer(db_session, customer_headers, profile="cost")
    before = await _postings(db_session)
    r = await integration_client.post(
        ORDERS, json=_body(item, max_price_usd="8.999"), headers=_h(token)
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "price_above_max"
    assert r.json()["price_usd"] == "9.000"
    assert await _orders(db_session) == 0
    assert await _postings(db_session) == before
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000)


async def test_chosen_offer_above_max(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, (9000, 10_000))
    _, token = await _customer(db_session, customer_headers, profile="cost")
    ids = await _offer_ids(db_session, item, "cost")
    r = await integration_client.post(
        ORDERS, json=_body(item, offer_id=ids[1], max_price_usd="9.999"), headers=_h(token)
    )
    assert r.status_code == 409
    assert r.json()["code"] == "price_above_max"
    assert r.json()["price_usd"] == "10.000"


async def test_no_offers_is_offer_gone(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, ())
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 409
    assert r.json()["code"] == "offer_gone"


async def test_same_client_order_id_twice(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, (9000, 9500))
    user, token = await _customer(db_session, customer_headers, profile="cost")
    first = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert first.status_code == 201
    second = await integration_client.post(
        ORDERS, json=_body(item, max_price_usd="50"), headers=_h(token)
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "duplicate_client_order_id"
    assert second.json()["order"]["order_id"] == first.json()["order_id"]
    assert second.json()["order"]["status"] == "buying"
    assert await _orders(db_session) == 1
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000 - 9000)


async def _callers(
    factory: async_sessionmaker[AsyncSession], key_id: str, user_id: str
) -> tuple[AsyncSession, ApiCaller]:
    db = factory()
    key = await db.get(ApiKey, key_id)
    user = await db.get(User, user_id)
    assert key is not None
    assert user is not None
    return db, ApiCaller(key=key, user=user)


async def test_concurrent_duplicates_buy_once(
    customer_headers: Headers, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item = await _item(db_session)
    user, _ = await _customer(db_session, customer_headers, profile="cost")
    key = await keys.live_key(db_session, user.id)
    assert key is not None
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    body = ApiOrderIn.model_validate(_body(item, cid="race-1"))
    settings = cfg.get_settings()

    async def one() -> tuple[str, bool]:
        db, caller = await _callers(factory, key.id, user.id)
        async with db:
            order, created = await create_api_order(db, caller=caller, body=body, settings=settings)
            return order.number, created

    results = await asyncio.gather(one(), one())
    assert sorted(c for _, c in results) == [False, True]
    assert results[0][0] == results[1][0]
    assert await _orders(db_session) == 1
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000 - 9000)


async def test_lost_race_reads_the_winner(
    customer_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window between the lookup and the insert: the unique pair decides, one debit."""
    item = await _item(db_session)
    user, _ = await _customer(db_session, customer_headers, profile="cost")
    key = await keys.live_key(db_session, user.id)
    assert key is not None
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    body = ApiOrderIn.model_validate(_body(item, cid="race-2"))
    settings = cfg.get_settings()
    db, caller = await _callers(factory, key.id, user.id)
    async with db:
        won, created = await create_api_order(db, caller=caller, body=body, settings=settings)
    assert created
    real = api_checkout._by_client_id
    calls = 0

    async def blind(*args: object, **kwargs: object) -> Order | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None  # as if the winner had not committed yet
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_checkout, "_by_client_id", blind)
    db, caller = await _callers(factory, key.id, user.id)
    async with db:
        lost, created = await create_api_order(db, caller=caller, body=body, settings=settings)
    assert not created
    assert lost.number == won.number
    assert await _orders(db_session) == 1
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000 - 9000)


async def test_short_balance_writes_nothing(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    user, token = await _customer(db_session, customer_headers, profile="cost", units=8999)
    before = await _postings(db_session)
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 402, r.text
    assert r.json()["code"] == "insufficient_balance"
    assert await _orders(db_session) == 0
    assert await _postings(db_session) == before
    assert await user_usd_balance(db_session, user.id) == Decimal(8999)


async def test_usd_wallet_off_is_403(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    user, token = await _customer(db_session, customer_headers)
    user.usd_wallet_enabled = False
    await db_session.commit()
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 403
    assert r.json()["code"] == "usd_wallet_disabled"


async def test_buying_off_is_409(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    monkeypatch.setenv("CSMARKET_SKINS_BUY_ENABLED", "false")
    cfg.get_settings.cache_clear()
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 409
    assert r.json()["code"] == "buying_disabled"


async def test_bad_trade_link_is_422(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.post(
        ORDERS, json=_body(item, trade_link="https://example.com/x"), headers=_h(token)
    )
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_invalid"


@pytest.mark.parametrize(
    "patch",
    [
        {"max_price_usd": "1.2345"},
        {"client_order_id": "has space"},
        {"client_order_id": ""},
        {"unknown": 1},
    ],
)
async def test_body_errors_are_422(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    patch: dict[str, object],
) -> None:
    item = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.post(ORDERS, json={**_body(item), **patch}, headers=_h(token))
    assert r.status_code == 422


async def test_forged_or_foreign_offer_id_is_offer_gone(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    other = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    [foreign] = await _offer_ids(db_session, other)
    for i, offer in enumerate(("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", foreign)):
        r = await integration_client.post(
            ORDERS, json=_body(item, cid=f"f-{i}", offer_id=offer), headers=_h(token)
        )
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "offer_gone"
    assert await _orders(db_session) == 0


@pytest.mark.parametrize("item_id", ["not-a-uuid", "00000000-0000-4000-8000-0000000000aa"])
async def test_unknown_item_is_404(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    item_id: str,
) -> None:
    item = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.post(ORDERS, json=_body(item, item_id=item_id), headers=_h(token))
    assert r.status_code == 404
    assert r.json()["code"] == "item_not_found"


async def _other_token(db: AsyncSession) -> str:
    user = await make_user(db)
    user.usd_wallet_enabled = True
    _, token = await keys.issue(db, user=user)
    await db.commit()
    return token


async def test_reads_one_order_and_hide_other_keys(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    created = (await integration_client.post(ORDERS, json=_body(item), headers=_h(token))).json()
    r = await integration_client.get(f"{ORDERS}/{created['order_id']}", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == created
    other = await _other_token(db_session)
    r = await integration_client.get(f"{ORDERS}/{created['order_id']}", headers=_h(other))
    assert r.status_code == 404
    r = await integration_client.get(f"{ORDERS}/nonsense", headers=_h(token))
    assert r.status_code == 404
    r = await integration_client.get(ORDERS, headers=_h(other))
    assert r.json() == {"items": [], "next_cursor": None}


async def test_list_filters_by_status(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, (9000, 9100, 9200))
    _, token = await _customer(db_session, customer_headers, profile="cost")
    numbers = []
    for cid in ("a", "b", "c"):
        r = await integration_client.post(ORDERS, json=_body(item, cid=cid), headers=_h(token))
        assert r.status_code == 201, r.text
        numbers.append(r.json()["order_id"])
    refunded, accepted, _ = numbers
    at = datetime.now(UTC)
    await db_session.execute(
        update(Order)
        .where(Order.number == refunded)
        .values(status="failed", refunded_at=at, failure_reason="not_accepted")
    )
    await db_session.execute(
        update(Order).where(Order.number == accepted).values(status="trade_sent")
    )
    order = await db_session.scalar(select(Order).where(Order.number == accepted))
    assert order is not None
    db_session.add(
        SkinslinkPurchase(
            order_id=order.id,
            merchant_tx_id=new_id(),
            asset_id="1",
            paid_units=9100,
            status="hold",
            hold_end_date=at + timedelta(days=7),
        )
    )
    await db_session.commit()

    async def listed(status: str | None) -> list[str]:
        params = {"status": status} if status else {}
        r = await integration_client.get(ORDERS, params=params, headers=_h(token))
        assert r.status_code == 200, r.text
        return [o["order_id"] for o in r.json()["items"]]

    assert await listed(None) == list(reversed(numbers))
    assert await listed("refunded") == [refunded]
    assert await listed("delivered") == [accepted]
    assert await listed("trade_sent") == []
    assert await listed("buying") == [numbers[2]]
    one = (await integration_client.get(f"{ORDERS}/{refunded}", headers=_h(token))).json()
    assert one["status"] == "refunded"
    assert one["refund"] == {"amount_usd": "9.000", "reason": "supplier_refused"}
    two = (await integration_client.get(f"{ORDERS}/{accepted}", headers=_h(token))).json()
    assert two["status"] == "delivered"
    assert two["trade"]["release_at"] is not None
    r = await integration_client.get(ORDERS, params={"status": "lost"}, headers=_h(token))
    assert r.status_code == 422


async def test_list_pages(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from csmarket.modules.orders import public_view

    monkeypatch.setattr(public_view, "PAGE_SIZE", 2)
    item = await _item(db_session, (9000, 9100, 9200))
    _, token = await _customer(db_session, customer_headers, profile="cost")
    for cid in ("a", "b", "c"):
        await integration_client.post(ORDERS, json=_body(item, cid=cid), headers=_h(token))
    page = (await integration_client.get(ORDERS, headers=_h(token))).json()
    assert len(page["items"]) == 2
    rest = (
        await integration_client.get(
            ORDERS, params={"cursor": page["next_cursor"]}, headers=_h(token)
        )
    ).json()
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None


async def test_me(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    user, token = await _customer(db_session, customer_headers, units=12_345)
    key = await keys.live_key(db_session, user.id)
    assert key is not None
    r = await integration_client.get("/api/v1/public/me", headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance_usd"] == "12.345"
    assert body["usd_wallet_enabled"] is True
    assert body["key"]["id"] == key.id
    assert body["key"]["pricing_profile"] == "retail"
    assert body["limits"] == {"read_per_min": 60, "orders_per_min": 10, "feed_per_min": 1}
    assert "token" not in r.text


# --- the status and reason mapping (spec §5), on transient rows ---


def _order(**values: object) -> Order:
    base: dict[str, object] = {
        "number": "ABCDEFGH",
        "client_order_id": "x",
        "skin_item_id": new_id(),
        "slug": "s",
        "market_hash_name": "m",
        "price_usd": Decimal("1.5"),
        "created_at": datetime.now(UTC),
        "status": "paid",
        "source": "skinslink",
    }
    base.update(values)
    return Order(**base)


@pytest.mark.parametrize(
    ("values", "status"),
    [
        ({"status": "paid"}, "buying"),
        ({"status": "buying"}, "buying"),
        ({"status": "trade_sent"}, "trade_sent"),
        ({"status": "delivered"}, "delivered"),
        ({"status": "failed", "refunded_at": datetime.now(UTC)}, "refunded"),
        ({"status": "returned", "refunded_at": datetime.now(UTC)}, "refunded"),
        ({"status": "failed"}, "buying"),  # held for support
        ({"status": "returned"}, "buying"),
    ],
)
def test_status_mapping(values: dict[str, object], status: str) -> None:
    assert public_order(_order(**values), None, None).status == status


@pytest.mark.parametrize(
    ("reason", "public"),
    [
        ("sold_out", "sold_out"),
        ("invalid_trade_link", "invalid_trade_link"),
        ("trade_hold", "trade_hold"),
        ("price_moved", "price_moved"),
        ("source_low_balance", "supplier_refused"),
        ("not_accepted", "supplier_refused"),
        ("admin", "cancelled_by_support"),
    ],
)
def test_reason_mapping(reason: str, public: str) -> None:
    out = public_order(
        _order(status="failed", refunded_at=datetime.now(UTC), failure_reason=reason), None, None
    )
    assert out.refund is not None
    assert out.refund.reason == public
    assert out.refund.amount_usd == "1.500"


def test_offer_sent_at_is_the_trade_sent_stamp() -> None:
    order = _order(status="buying")
    move(order, "trade_sent")
    out = public_order(order, None, None)
    assert out.status == "trade_sent"
    assert out.trade is not None
    assert order.trade_sent_at is not None
    assert out.trade.offer_sent_at == order.trade_sent_at
    assert out.trade.accepted_at is None


@pytest.mark.parametrize(
    ("trade", "status"),
    [
        (
            SkinTrade(status=4, release_date=datetime.now(UTC), accepted_at=datetime.now(UTC)),
            "delivered",
        ),
        (SkinTrade(status=4), "trade_sent"),
        (SkinTrade(status=5, release_date=datetime.now(UTC)), "delivered"),
    ],
)
def test_a_waxpeer_trade_maps_too(trade: SkinTrade, status: str) -> None:
    out = public_order(_order(status="trade_sent", source="waxpeer"), trade, None)
    assert out.status == status
    assert out.trade is not None
    assert out.trade.release_at == trade.release_date
    assert out.trade.accepted_at == trade.accepted_at


@pytest.mark.parametrize(
    ("ls_status", "status"), [("accepted", "delivered"), ("wait_accept", "trade_sent")]
)
def test_a_lisskins_purchase_maps_too(ls_status: str, status: str) -> None:
    purchase = LisskinsPurchase(status=ls_status)
    out = public_order(_order(status="trade_sent", source="lisskins"), None, purchase)
    assert out.status == status
    assert out.trade is not None
    assert out.trade.release_at is None


async def test_no_rate_snapshot_at_all_is_503(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    _, token = await _customer(db_session, customer_headers)
    await db_session.execute(delete(FxSnapshot))
    await db_session.commit()
    r = await integration_client.post(ORDERS, json=_body(item), headers=_h(token))
    assert r.status_code == 503
    assert r.json()["code"] == "rate_unavailable"
    assert await _orders(db_session) == 0


async def test_a_reissued_key_keeps_the_orders_and_their_ids(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session, (9000, 9500))
    user, old = await _customer(db_session, customer_headers, profile="cost")
    first = (await integration_client.post(ORDERS, json=_body(item), headers=_h(old))).json()
    _, new = await keys.issue(db_session, user=user)
    await db_session.commit()
    assert (await integration_client.get(ORDERS, headers=_h(old))).status_code == 401
    r = await integration_client.get(f"{ORDERS}/{first['order_id']}", headers=_h(new))
    assert r.status_code == 200
    assert r.json() == first
    listed = (await integration_client.get(ORDERS, headers=_h(new))).json()["items"]
    assert [o["order_id"] for o in listed] == [first["order_id"]]
    again = await integration_client.post(ORDERS, json=_body(item), headers=_h(new))
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "duplicate_client_order_id"
    assert again.json()["order"]["order_id"] == first["order_id"]
    assert await _orders(db_session) == 1
    assert await user_usd_balance(db_session, user.id) == Decimal(50_000 - 9000)


async def test_two_ids_at_once_on_a_balance_for_one(
    customer_headers: Headers, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item = await _item(db_session, (9000, 9100))
    user, _ = await _customer(db_session, customer_headers, profile="cost", units=12_000)
    key = await keys.live_key(db_session, user.id)
    assert key is not None
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    settings = cfg.get_settings()

    async def one(cid: str) -> str:
        db, caller = await _callers(factory, key.id, user.id)
        async with db:
            body = ApiOrderIn.model_validate(_body(item, cid=cid))
            try:
                await create_api_order(db, caller=caller, body=body, settings=settings)
            except InsufficientBalanceError:
                return "402"
            return "201"

    results = await asyncio.gather(one("two-1"), one("two-2"))
    assert sorted(results) == ["201", "402"]
    assert await _orders(db_session) == 1
    assert await user_usd_balance(db_session, user.id) == Decimal(12_000 - 9000)


def _sample(name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_public_requests_and_orders_are_counted(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    _user, token = await _customer(db_session, customer_headers, profile="cost")
    [offer] = await _offer_ids(db_session, item, "cost")
    req = "csmarket_public_api_requests_total"
    ordc = "csmarket_public_api_orders_total"
    me2 = _sample(req, route="/public/me", status="2xx")
    me4 = _sample(req, route="/public/me", status="4xx")
    o201 = _sample(req, route="/public/orders", status="2xx")
    o422 = _sample(req, route="/public/orders", status="4xx")
    created = _sample(ordc, profile="cost", outcome="created")
    dup = _sample(ordc, profile="cost", outcome="duplicate")

    assert (await integration_client.get("/api/v1/public/me", headers=_h(token))).status_code == 200
    assert (await integration_client.get("/api/v1/public/me")).status_code == 401
    body = _body(item, offer_id=offer, max_price_usd="9")
    assert (await integration_client.post(ORDERS, json=body, headers=_h(token))).status_code == 201
    assert (await integration_client.post(ORDERS, json=body, headers=_h(token))).status_code == 409
    assert (await integration_client.post(ORDERS, json={}, headers=_h(token))).status_code == 422

    assert _sample(req, route="/public/me", status="2xx") == me2 + 1
    assert _sample(req, route="/public/me", status="4xx") == me4 + 1
    assert _sample(req, route="/public/orders", status="2xx") == o201 + 1
    assert _sample(req, route="/public/orders", status="4xx") == o422 + 2
    assert _sample(ordc, profile="cost", outcome="created") == created + 1
    assert _sample(ordc, profile="cost", outcome="duplicate") == dup + 1
