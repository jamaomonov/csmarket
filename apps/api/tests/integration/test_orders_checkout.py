"""``POST /orders``: re-priced from the live offers, substitution (R4), the trade-link gate
(R10), the buying switch (R12), the rate, idempotency and the ``order-create`` bucket."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.api import FxSnapshot, record_snapshot
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import search_client
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import FAKE_TRADE_LINK, StubListings, saved_trade_link

pytestmark = pytest.mark.asyncio

SLUG = "ak-47-redline-ft"
ORDERS = "/api/v1/orders"
RATE = Decimal("12700")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_SKINS_BUY_ENABLED", "true")
    # A key turns the live read on; every call goes to the stub client.
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "k")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def rate(db_session: AsyncSession) -> FxSnapshot:
    row = await record_snapshot(db_session, rate=RATE, source="cbu")
    await db_session.commit()
    return row


async def _item(db: AsyncSession, slug: str, **over: object) -> SkinItem:
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)" if slug == SLUG else f"Item {slug}",
        phase="",
        slug=slug,
        category="rifles",
        weapon="AK-47",
        search_text=slug,
        count_auto=49,
        active=True,
        cheapest_auto=[],
    )
    for k, v in over.items():
        setattr(row, k, v)
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
async def item(db_session: AsyncSession) -> SkinItem:
    return await _item(db_session, SLUG)


@pytest.fixture
def stub_listings(integration_app: FastAPI, item: SkinItem) -> Iterator[StubListings]:
    stub = StubListings()
    stub.register(item)
    integration_app.dependency_overrides[search_client] = lambda: stub
    yield stub
    integration_app.dependency_overrides.pop(search_client, None)


@pytest.fixture
async def user_headers(integration_client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    """A signed-in buyer whose fake trade link is saved and checked ``ok``."""
    h = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID)
    return h


@pytest.fixture
async def user_with_link(user_headers: dict[str, str], db_session: AsyncSession) -> User:
    user = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


def _key(headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or f"order-{uuid.uuid4()}"}


async def _shown_price(api: AsyncClient, slug: str, listing_id: int | str) -> int:
    """The soʻm price the item page's listings showed for ``listing_id`` (a bare int is
    Waxpeer's: the page lists ``wx:<id>``)."""
    r = await api.get(f"/api/v1/skins/{slug}/listings")
    assert r.status_code == 200, r.text
    wanted = listing_id if isinstance(listing_id, str) else f"wx:{listing_id}"
    row = next(i for i in r.json()["items"] if i["listing_id"] == wanted)
    return int(row["price_uzs"])


async def _order(db: AsyncSession, number: str) -> Order:
    db.expire_all()
    order = await db.scalar(select(Order).where(Order.number == number))
    assert order is not None
    return order


async def _post(
    api: AsyncClient,
    headers: dict[str, str],
    *,
    listing_id: int = 111,
    price_uzs: Any = 139_100,
    slug: str = SLUG,
    key: str | None = None,
) -> Response:
    body = {"slug": slug, "listing_id": listing_id, "price_uzs": price_uzs}
    return await api.post(ORDERS, headers=_key(headers, key), json=body)


async def _orders(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Order)) or 0)


# --- pricing -----------------------------------------------------------------------------


async def test_price_moved_beyond_tolerance_is_409(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])  # $10.00 cost
    shown = await _shown_price(integration_client, SLUG, 111)  # what the panel showed
    await stub_listings.set(SLUG, [(111, 11_000)])  # cost +10 %
    r = await _post(integration_client, user_headers, price_uzs=shown)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "price_changed"
    assert int(r.json()["price_uzs"]) > shown
    assert await _orders(db_session) == 0


async def test_within_tolerance_the_server_price_is_billed(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    await stub_listings.set(SLUG, [(111, 10_100)])  # +1 % cost, inside ±2 %
    server = await _shown_price(integration_client, SLUG, 111)
    assert server != shown
    r = await _post(integration_client, user_headers, price_uzs=shown)
    assert r.status_code == 201, r.text
    assert r.json()["price_uzs"] == str(server)
    order = await _order(db_session, r.json()["number"])
    assert (order.listing_id, order.cost_units, order.price_uzs) == (111, 10_100, Decimal(server))


async def test_the_order_snapshots_offer_price_rate_and_link(
    *,
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    user_with_link: User,
    stub_listings: StubListings,
    item: SkinItem,
    rate: FxSnapshot,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    user_id, item_id, item_name, rate_id = (
        user_with_link.id,
        item.id,
        item.market_hash_name,
        rate.id,
    )
    before = clock.now()
    r = await _post(integration_client, user_headers, price_uzs=shown)
    assert r.status_code == 201, r.text
    body = r.json()
    number = body["number"]
    assert len(number) == 8
    assert not number.startswith("T")
    order = await _order(db_session, number)
    assert order.status == "pending"
    assert (order.user_id, order.skin_item_id) == (user_id, item_id)
    assert (order.market_hash_name, order.slug, order.phase) == (
        item_name,
        SLUG,
        "",
    )
    assert (order.listing_id, order.cost_units, order.cost_usd) == (
        111,
        10_000,
        Decimal("10.000000"),
    )
    assert order.price_uzs == Decimal(shown)
    assert order.price_usd == Decimal(body["price_usd"])
    assert order.price_uzs == Decimal(body["price_uzs"])
    assert order.fx_snapshot_id == rate_id
    assert order.trade_link == FAKE_TRADE_LINK
    window = order.expires_at - before
    assert timedelta(minutes=14, seconds=59) < window <= timedelta(minutes=15, seconds=5)
    assert (body["status"], body["payable"], body["trade"]) == ("pending", True, None)
    assert (body["name"], body["phase"]) == (item_name, None)


# --- substitution (R4) --------------------------------------------------------------------


async def test_gone_offer_substituted_within_ceiling(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000), (112, 10_200)])
    shown = await _shown_price(integration_client, SLUG, 111)
    await stub_listings.set(SLUG, [(112, 10_200), (113, 12_000)])  # 111 sold
    r = await _post(integration_client, user_headers, price_uzs=shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.listing_id, order.cost_units) == (112, 10_200)
    assert Decimal(r.json()["price_uzs"]) <= shown  # never more than shown
    assert order.price_uzs == shown
    assert order.price_usd == (Decimal(shown) / RATE).quantize(Decimal("0.000001"))


async def test_a_cheaper_substitute_is_billed_at_its_own_price(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000), (112, 9_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    cheaper = await _shown_price(integration_client, SLUG, 112)
    await stub_listings.set(SLUG, [(112, 9_000)])
    r = await _post(integration_client, user_headers, price_uzs=shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.listing_id, order.cost_units, order.price_uzs) == (112, 9_000, Decimal(cheaper))
    assert cheaper < shown


async def test_gone_offer_without_substitute_is_409_with_next(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    await stub_listings.set(SLUG, [(113, 12_000)])
    r = await _post(integration_client, user_headers, price_uzs=shown)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "offer_gone"
    assert r.json()["next_offer"]["listing_id"] == 113
    assert int(r.json()["next_offer"]["price_uzs"]) > shown
    assert await _orders(db_session) == 0


async def test_nothing_listed_is_offer_gone_without_next(
    integration_client: AsyncClient, user_headers: dict[str, str], stub_listings: StubListings
) -> None:
    await stub_listings.set(SLUG, [])
    r = await _post(integration_client, user_headers)
    assert r.status_code == 409, r.text
    assert (r.json()["code"], r.json()["next_offer"]) == ("offer_gone", None)


# --- the trade-link gate (R10, ruling C) --------------------------------------------------


async def _create(api: AsyncClient, headers: dict[str, str]) -> Response:
    return await _post(api, headers)


async def test_trade_hold_link_is_refused(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    db_session: AsyncSession,
    user_with_link: User,
    stub_listings: StubListings,
) -> None:
    user_with_link.trade_link_verdict, user_with_link.trade_link_reason = "bad", "hold"
    await db_session.commit()
    r = await _create(integration_client, user_headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "trade_link_bad"
    assert r.json()["reason"] == "hold"
    assert stub_listings.calls == 0


@pytest.mark.parametrize(
    ("verdict", "reason", "expected"),
    [
        ("warn", "hold", "hold"),  # a legacy stored verdict still refuses (ruling C)
        ("warn", None, "hold"),
        ("bad", "private", "private"),
        ("bad", "trade_ban", "trade_ban"),
        ("bad", "invalid", "invalid"),
        ("bad", None, "invalid"),
    ],
)
async def test_a_bad_or_legacy_warn_verdict_is_refused(
    *,
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    db_session: AsyncSession,
    stub_listings: StubListings,
    verdict: str,
    reason: str | None,
    expected: str,
) -> None:
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID, verdict=verdict, reason=reason)
    r = await _create(integration_client, user_headers)
    assert r.status_code == 409, r.text
    assert (r.json()["code"], r.json()["reason"]) == ("trade_link_bad", expected)


async def test_an_unparseable_stored_link_is_refused_as_invalid(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    db_session: AsyncSession,
    stub_listings: StubListings,
) -> None:
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID, link="https://example.com/x")
    r = await _create(integration_client, user_headers)
    assert (r.status_code, r.json()["code"], r.json()["reason"]) == (
        409,
        "trade_link_bad",
        "invalid",
    )


async def test_missing_link_is_409(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    db_session: AsyncSession,
    stub_listings: StubListings,
) -> None:
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID, link=None, verdict=None)
    r = await _create(integration_client, user_headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "trade_link_missing"


@pytest.mark.parametrize(("verdict", "reason"), [(None, None), (None, "unavailable")])
async def test_an_unchecked_or_unavailable_verdict_passes(
    *,
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    db_session: AsyncSession,
    stub_listings: StubListings,
    verdict: str | None,
    reason: str | None,
) -> None:
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID, verdict=verdict, reason=reason)
    await stub_listings.set(SLUG, [(111, 10_000)])
    r = await _create(integration_client, user_headers)
    assert r.status_code == 201, r.text


# --- switches, item, rate -----------------------------------------------------------------


async def test_buying_disabled_is_409(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CSMARKET_SKINS_BUY_ENABLED", "false")
    cfg.get_settings.cache_clear()
    r = await _create(integration_client, user_headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "buying_disabled"
    assert stub_listings.calls == 0


async def test_the_item_page_says_whether_buying_is_on(
    integration_client: AsyncClient, item: SkinItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = await integration_client.get(f"/api/v1/skins/{SLUG}")
    assert on.json()["buy_enabled"] is True
    monkeypatch.setenv("CSMARKET_SKINS_BUY_ENABLED", "false")
    cfg.get_settings.cache_clear()
    off = await integration_client.get(f"/api/v1/skins/{SLUG}")
    assert off.json()["buy_enabled"] is False


async def test_a_hidden_or_unknown_item_is_404(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await _item(db_session, "hidden-one", hidden=True)
    for slug in ("hidden-one", "no-such-skin"):
        r = await _post(integration_client, user_headers, slug=slug)
        assert r.status_code == 404, (slug, r.text)
    assert stub_listings.calls == 0


async def test_a_stale_rate_is_503(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    days = cfg.get_settings().fx_max_age_days + 1
    await db_session.execute(
        update(FxSnapshot).values(fetched_at=clock.now() - timedelta(days=days))
    )
    await db_session.commit()
    r = await _create(integration_client, user_headers)
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "rate_unavailable"


@pytest.mark.parametrize(
    "body",
    [
        {"slug": SLUG, "listing_id": 111, "price_uzs": "139100"},
        {"slug": SLUG, "listing_id": 111, "price_uzs": 139100.5},
        {"slug": SLUG, "listing_id": 111, "price_uzs": 0},
        {"slug": SLUG, "listing_id": 0, "price_uzs": 139100},
        {"slug": "", "listing_id": 111, "price_uzs": 139100},
        {"slug": SLUG, "listing_id": 111, "price_uzs": 139100, "extra": 1},
    ],
)
async def test_a_malformed_body_is_422(
    integration_client: AsyncClient, user_headers: dict[str, str], body: dict[str, Any]
) -> None:
    r = await integration_client.post(ORDERS, headers=_key(user_headers), json=body)
    assert r.status_code == 422, r.text


async def test_signed_out_is_401(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        ORDERS,
        headers={"Idempotency-Key": f"order-{uuid.uuid4()}"},
        json={"slug": SLUG, "listing_id": 111, "price_uzs": 139_100},
    )
    assert r.status_code == 401


# --- idempotency and the bucket ------------------------------------------------------------


async def test_missing_short_or_long_key_is_422(
    integration_client: AsyncClient, user_headers: dict[str, str]
) -> None:
    body = {"slug": SLUG, "listing_id": 111, "price_uzs": 139_100}
    for headers in (
        user_headers,
        {**user_headers, "Idempotency-Key": "short"},
        {**user_headers, "Idempotency-Key": "k" * 161},
    ):
        r = await integration_client.post(ORDERS, headers=headers, json=body)
        assert r.status_code == 422, r.text


async def test_a_replayed_key_returns_the_same_order_whatever_the_body(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    key = f"order-{uuid.uuid4()}"
    first = await _post(integration_client, user_headers, price_uzs=shown, key=key)
    assert first.status_code == 201, first.text
    await stub_listings.set(SLUG, [])  # the offer is gone now: a new order would be a 409
    again = await _post(
        integration_client, user_headers, listing_id=999, price_uzs=1, slug="other", key=key
    )
    assert again.status_code == 200, again.text
    assert again.json()["number"] == first.json()["number"]
    assert again.json()["price_uzs"] == first.json()["price_uzs"]
    assert await _orders(db_session) == 1


async def test_two_concurrent_first_requests_with_one_key_make_one_order(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    await stub_listings.set(SLUG, [(111, 10_000)])  # both requests read the stub...
    stub_listings.barrier = asyncio.Barrier(2)  # ...together, each past the replay check
    key = f"order-{uuid.uuid4()}"
    a, b = await asyncio.gather(
        _post(integration_client, user_headers, price_uzs=shown, key=key),
        _post(integration_client, user_headers, price_uzs=shown, key=key),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 201], (a.text, b.text)
    assert a.json()["number"] == b.json()["number"]
    assert await _orders(db_session) == 1


async def test_the_same_key_from_another_buyer_is_another_order(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    db_session: AsyncSession,
) -> None:
    await stub_listings.set(SLUG, [(111, 10_000)])
    shown = await _shown_price(integration_client, SLUG, 111)
    other_sid = "76561198000000007"
    other = await dev_login_headers(integration_client, steam_id=other_sid, admin=False)
    await saved_trade_link(db_session, other_sid)
    key = f"order-{uuid.uuid4()}"
    a = await _post(integration_client, user_headers, price_uzs=shown, key=key)
    b = await _post(integration_client, other, price_uzs=shown, key=key)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["number"] != b.json()["number"]


async def test_order_create_bucket_answers_429_on_the_11th_call_per_account(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route charges ``order-create`` per IP and account (10 a minute) before any work."""
    monkeypatch.setenv("CSMARKET_SKINS_BUY_ENABLED", "false")  # cheap 409s count too
    cfg.get_settings.cache_clear()
    h = {**user_headers, "X-Forwarded-For": "203.0.113.77"}
    limit = cfg.get_settings().auth_ip_guard_subject_max
    assert limit == 10
    for _ in range(limit):
        assert (await _create(integration_client, h)).status_code == 409
    r = await _create(integration_client, h)
    assert r.status_code == 429, r.text
    assert r.headers["retry-after"] == str(cfg.get_settings().auth_ip_guard_window_seconds)
    other = {**user_headers, "X-Forwarded-For": "198.51.100.77"}
    assert (await _create(integration_client, other)).status_code == 409


async def test_order_create_is_its_own_ip_bucket(
    integration_client: AsyncClient,
    user_headers: dict[str, str],
    stub_listings: StubListings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-IP ceiling set for ``order-create`` trips at 3 (a typo'd bucket would not)."""
    monkeypatch.setenv("CSMARKET_SKINS_BUY_ENABLED", "false")
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"order-create": 3}')
    cfg.get_settings.cache_clear()
    h = {**user_headers, "X-Forwarded-For": "203.0.113.78"}
    for _ in range(3):
        assert (await _create(integration_client, h)).status_code == 409
    assert (await _create(integration_client, h)).status_code == 429


async def test_a_number_collision_is_not_mistaken_for_a_replay(
    user_with_link: User,
    stub_listings: StubListings,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``IntegrityError`` that is not the same key racing us is raised, not swallowed."""
    from csmarket.core.redis import get_redis
    from csmarket.modules.orders import checkout
    from csmarket.modules.orders.schemas import OrderCreateIn
    from sqlalchemy.exc import IntegrityError

    from tests.integration.orders_factory import make_order

    taken = (await make_order(db_session)).number

    async def _taken(*_args: object, **_kwargs: object) -> str:
        return taken

    monkeypatch.setattr(checkout, "allocate", _taken)
    await stub_listings.set(SLUG, [(111, 10_000)])
    with pytest.raises(IntegrityError):
        await checkout.create_order(
            db_session,
            redis=get_redis(),
            user=user_with_link,
            body=OrderCreateIn(slug=SLUG, listing_id=111, price_uzs=137_200),
            idempotency_key=f"order-{uuid.uuid4()}",
            client=stub_listings,
            settings=cfg.get_settings(),
        )
    await db_session.rollback()
    assert await _orders(db_session) == 1
