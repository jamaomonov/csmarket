"""The dev Waxpeer fake (ruling R13): trades in Redis that send their offer by themselves,
the dev routes that accept / decline / roll a trade back, and the process clients that pick
the fake under ``CSMARKET_WAXPEER_FAKE``. Task 9's sweeps run against it unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from csmarket.core import clock as core_clock
from csmarket.core import config as cfg
from csmarket.core.redis import get_redis
from csmarket.modules.orders.api import attempt_buy, drain_paid
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.sweeps import reconcile, watch_protected
from csmarket.modules.skins.api import (
    LOOKUP_MAX_IDS,
    FakeTradeClient,
    WaxpeerTradeClient,
    WaxpeerUnavailableError,
    search_client,
    trade_client,
)
from csmarket.modules.skins.waxpeer import WaxpeerClient
from csmarket.modules.skins.waxpeer_fake import FakeUnavailableError, fake_client
from csmarket.modules.users.models import User
from csmarket.modules.users.routes import tradelink_checkers
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.trade_sweeps_kit import (  # noqa: F401 -- fixtures by name
    PRICE,
    Clock,
    attentions,
    balance,
    clock_fixture,
    factory,
    load,
    sweep_settings,
)

pytestmark = pytest.mark.asyncio

TRADE_KEY = "skins:waxpeer:fake:trade:{}"
BALANCE_KEY = "skins:waxpeer:fake:balance"


# --- fixtures and helpers ------------------------------------------------------------------


@pytest.fixture
def wax() -> FakeTradeClient:
    """The fake on this test's Redis."""
    return FakeTradeClient(get_redis())


@pytest.fixture
def fake_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``CSMARKET_WAXPEER_FAKE=true`` for the process settings."""
    monkeypatch.setenv("CSMARKET_WAXPEER_FAKE", "true")
    cfg.get_settings.cache_clear()
    yield
    monkeypatch.undo()
    cfg.get_settings.cache_clear()


@pytest.fixture
async def headers(integration_client: AsyncClient, fake_on: None) -> dict[str, str]:
    """The buyer's Bearer header (dev login), with the fake on."""
    return await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)


@pytest.fixture
async def buyer(headers: dict[str, str], db_session: AsyncSession) -> User:
    user = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


@pytest.fixture
async def to_buy(db_session: AsyncSession, buyer: User) -> Order:
    """The buyer's kassa-paid order in ``buying``, its trade waiting to be bought."""
    order = await make_order(
        db_session,
        user=buyer,
        status="buying",
        paid_with="payme",
        paid_at=core_clock.now(),
        price_uzs=PRICE,
    )
    await make_trade(db_session, order, buy_pending=True)
    return order


async def tick(db: AsyncSession, wax: FakeTradeClient, clock: Clock, seconds: float = 11) -> None:
    """Move the clock past the reconcile interval and run one reconcile tick."""
    clock.advance(seconds=seconds)
    await reconcile(factory(db), wax, settings=sweep_settings())


async def act(api: AsyncClient, headers: dict[str, str], order: Order, action: str) -> Any:
    """``POST /dev/orders/{number}/trade``; the JSON answer (asserted 200)."""
    r = await api.post(
        f"/api/v1/dev/orders/{order.number}/trade", headers=headers, json={"action": action}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def bought(db: AsyncSession, wax: FakeTradeClient, order: Order) -> None:
    """Buy ``order`` through the real worker step against the fake."""
    assert await attempt_buy(db, wax, order_id=order.id) == "bought"


# --- the fake on its own -------------------------------------------------------------------


async def test_a_buy_sends_its_offer_by_itself(wax: FakeTradeClient, clock: Clock) -> None:
    buy = await wax.buy_one_p2p(
        item_id=9_100_200_300, price_units=12_345, partner=1, token="FAKEFAKE", project_id="o-1"
    )
    assert buy.id > 0
    assert buy.price_units == 12_345

    [fresh] = await wax.check_project_ids(["o-1"])
    assert (fresh.id, fresh.project_id, fresh.status) == (buy.id, "o-1", 0)
    assert (fresh.trade_id, fresh.send_until, fresh.release_date) == (None, None, None)
    assert fresh.price_units == 12_345

    clock.advance(seconds=3)
    [sending] = await wax.check_project_ids(["o-1"])
    assert sending.status == 2
    assert sending.trade_id is not None
    assert sending.trade_id.isdigit()
    assert len(sending.trade_id) == 10

    clock.advance(seconds=3)
    sent_at = clock.now()
    [sent] = await wax.check_project_ids(["o-1"])
    assert (sent.status, sent.trade_id, sent.release_date) == (4, sending.trade_id, None)
    assert sent.send_until is not None
    assert sent_at + timedelta(minutes=30) - sent.send_until < timedelta(seconds=1)
    assert sent.done is False

    clock.advance(minutes=5)
    [later] = await wax.check_project_ids(["o-1"])
    assert later == sent


async def test_the_trades_live_in_redis_for_seven_days(wax: FakeTradeClient) -> None:
    await wax.buy_one_p2p(item_id=1, price_units=100, partner=1, token="FAKEFAKE", project_id="o-7")
    ttl = await get_redis().ttl(TRADE_KEY.format("o-7"))
    assert 7 * 86_400 - 60 < ttl <= 7 * 86_400
    # No trade link travels into Redis.
    stored = await get_redis().hgetall(TRADE_KEY.format("o-7"))
    assert "FAKEFAKE" not in str(stored)


async def test_a_second_buy_under_one_project_id_is_a_second_trade(
    wax: FakeTradeClient,
) -> None:
    first = await wax.buy_one_p2p(
        item_id=1, price_units=100, partner=1, token="FAKEFAKE", project_id="o-2"
    )
    second = await wax.buy_one_p2p(
        item_id=2, price_units=200, partner=1, token="FAKEFAKE", project_id="o-2"
    )
    assert first.id != second.id
    trades = await wax.check_project_ids(["o-2", "o-unknown"])
    assert sorted((t.id, t.price_units) for t in trades) == sorted(
        [(first.id, 100), (second.id, 200)]
    )
    assert {t.project_id for t in trades} == {"o-2"}


async def test_the_lookup_keeps_the_real_contract(wax: FakeTradeClient) -> None:
    assert await wax.check_project_ids([]) == []
    assert await wax.check_project_ids(["never-bought"]) == []
    with pytest.raises(ValueError, match="at most"):
        await wax.check_project_ids([str(i) for i in range(LOOKUP_MAX_IDS + 1)])
    with pytest.raises(TypeError):
        await wax.check_project_ids("o-1")


async def test_an_unreadable_stored_trade_is_an_outage(wax: FakeTradeClient) -> None:
    await get_redis().hset(TRADE_KEY.format("o-3"), "123", "not json")
    with pytest.raises(WaxpeerUnavailableError):
        await wax.check_project_ids(["o-3"])


class _DeadRedis:
    """Every command fails as a lost Redis connection."""

    def __getattr__(self, _name: str) -> Any:
        async def _fail(*_args: object, **_kwargs: object) -> None:
            raise RedisConnectionError("down")

        return _fail

    def pipeline(self, *_args: object, **_kwargs: object) -> Any:
        raise RedisConnectionError("down")


async def test_redis_down_reads_as_a_waxpeer_outage() -> None:
    dead = FakeTradeClient(_DeadRedis())  # type: ignore[arg-type]  # a stand-in that only fails
    with pytest.raises(WaxpeerUnavailableError):
        await dead.buy_one_p2p(item_id=1, price_units=1, partner=1, token="x", project_id="o")
    with pytest.raises(WaxpeerUnavailableError):
        await dead.check_project_ids(["o"])
    with pytest.raises(WaxpeerUnavailableError):
        await dead.balance_units()


async def test_redis_down_under_a_dev_route_is_a_503_not_a_500() -> None:
    dead = FakeTradeClient(_DeadRedis())  # type: ignore[arg-type]  # a stand-in that only fails
    with pytest.raises(FakeUnavailableError) as setting:
        await dead.set_balance(1)
    with pytest.raises(FakeUnavailableError) as acting:
        await dead.act("o", "accept", waxpeer_id=None)
    assert setting.value.status_code == acting.value.status_code == 503


async def test_a_failed_write_of_an_action_is_a_503(
    wax: FakeTradeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await wax.buy_one_p2p(item_id=1, price_units=1, partner=1, token="x", project_id="o-503")

    async def down(*_args: object, **_kwargs: object) -> None:
        raise RedisConnectionError("down")

    monkeypatch.setattr(get_redis(), "hset", down)
    with pytest.raises(FakeUnavailableError):
        await wax.act("o-503", "decline", waxpeer_id=None)


async def test_the_dev_routes_answer_503_when_the_fake_is_down(
    integration_client: AsyncClient,
    integration_app: Any,
    headers: dict[str, str],
    to_buy: Order,
) -> None:
    dead = FakeTradeClient(_DeadRedis())  # type: ignore[arg-type]  # a stand-in that only fails
    integration_app.dependency_overrides[fake_client] = lambda: dead
    try:
        r = await integration_client.post(
            "/api/v1/dev/waxpeer/balance", headers=headers, json={"units": 1}
        )
        assert r.status_code == 503, r.text
        r = await integration_client.post(
            f"/api/v1/dev/orders/{to_buy.number}/trade", headers=headers, json={"action": "accept"}
        )
        assert r.status_code == 503, r.text
    finally:
        integration_app.dependency_overrides.pop(fake_client, None)


async def test_the_balance_is_ten_thousand_dollars_until_set(wax: FakeTradeClient) -> None:
    assert await wax.balance_units() == 10_000_000
    await wax.set_balance(42_000)
    assert await wax.balance_units() == 42_000
    assert await get_redis().get(BALANCE_KEY) == "42000"


async def test_listings_are_unavailable_and_every_trade_link_works(
    wax: FakeTradeClient,
) -> None:
    with pytest.raises(WaxpeerUnavailableError):
        await wax.search_listings(["AK-47 | Redline (Field-Tested)"])
    assert await wax.check_tradelink("https://steamcommunity.com/tradeoffer/new/?partner=1") is None


# --- which client the processes build ------------------------------------------------------


async def test_the_process_clients_are_the_fake_under_the_flag(fake_on: None) -> None:
    settings = cfg.get_settings()
    assert isinstance(trade_client(settings), FakeTradeClient)
    assert isinstance(search_client(), FakeTradeClient)
    checker, _hold = tradelink_checkers()
    assert isinstance(checker, FakeTradeClient)
    # A copied Settings skips the prod validator; the factory still never fakes prod.
    prod = settings.model_copy(update={"environment": "prod"})
    assert isinstance(trade_client(prod), WaxpeerTradeClient)


async def test_the_real_clients_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_WAXPEER_FAKE", "false")
    cfg.get_settings.cache_clear()
    try:
        assert isinstance(trade_client(), WaxpeerTradeClient)
        assert type(search_client()) is WaxpeerClient
        checker, _hold = tradelink_checkers()
        assert type(checker) is WaxpeerClient
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_the_worker_drain_buys_through_the_fake(
    db_session: AsyncSession, buyer: User
) -> None:
    paid = await make_order(
        db_session, user=buyer, status="paid", paid_with="payme", paid_at=core_clock.now()
    )
    settings = cfg.get_settings()
    assert settings.waxpeer_fake is True
    assert await drain_paid(db_session, settings=settings) == 1
    _, trade = await load(db_session, paid)
    assert trade.waxpeer_id is not None
    assert trade.buy_pending is False
    [found] = await FakeTradeClient(get_redis()).check_project_ids([paid.id])
    assert (found.id, found.price_units) == (trade.waxpeer_id, paid.cost_units)


# --- dev routes drive the sweeps -----------------------------------------------------------


async def test_accept_then_reconcile_delivers(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    to_buy: Order,
    clock: Clock,
) -> None:
    wax = FakeTradeClient(get_redis())
    await bought(db_session, wax, to_buy)
    await tick(db_session, wax, clock, seconds=6)
    order, trade = await load(db_session, to_buy)
    assert (order.status, trade.status) == ("trade_sent", 4)

    accepted = await act(integration_client, headers, to_buy, "accept")
    assert accepted["status"] == 4
    assert accepted["release_date"] is not None
    assert (await act(integration_client, headers, to_buy, "accept")) == accepted  # a no-op

    await tick(db_session, wax, clock)
    order, trade = await load(db_session, to_buy)
    assert order.status == "delivered"
    assert trade.release_date is not None
    assert trade.release_date - clock.now() > timedelta(days=6, hours=23)
    assert trade.attention_reason is None


async def test_decline_then_reconcile_returns_the_money(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    to_buy: Order,
    clock: Clock,
) -> None:
    wax = FakeTradeClient(get_redis())
    await bought(db_session, wax, to_buy)
    await tick(db_session, wax, clock, seconds=6)
    before = await balance(db_session, to_buy)

    declined = await act(integration_client, headers, to_buy, "decline")
    assert (declined["status"], declined["reason"]) == (6, "Buyer failed to accept")
    assert (await act(integration_client, headers, to_buy, "decline")) == declined  # a no-op

    await tick(db_session, wax, clock)
    order, trade = await load(db_session, to_buy)
    assert order.status == "returned"
    assert order.refunded_at is not None
    assert trade.status == 6
    assert await balance(db_session, to_buy) == before + PRICE


async def test_rollback_after_accept_is_seen_by_the_watch_and_refunds_nothing(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    to_buy: Order,
    clock: Clock,
) -> None:
    wax = FakeTradeClient(get_redis())
    await bought(db_session, wax, to_buy)
    await tick(db_session, wax, clock, seconds=6)
    await act(integration_client, headers, to_buy, "accept")
    await tick(db_session, wax, clock)
    before, flagged = await balance(db_session, to_buy), attentions("rolled_back")

    rolled = await act(integration_client, headers, to_buy, "rollback")
    assert rolled["status"] == 6
    assert rolled["penalties"] == {"rollback_fee": to_buy.cost_units}

    # A delivered order is the protection watch's, not reconcile's.
    async with factory(db_session)() as session:
        assert await watch_protected(session, wax) == 1
    order, trade = await load(db_session, to_buy)
    assert order.status == "delivered"
    assert order.refunded_at is None
    assert (trade.status, trade.attention_reason) == (6, "rolled_back")
    assert await balance(db_session, to_buy) == before
    assert attentions("rolled_back") == flagged + 1


async def test_a_double_buy_reads_as_ambiguous(
    db_session: AsyncSession, buyer: User, clock: Clock
) -> None:
    order = await make_order(
        db_session, user=buyer, status="buying", paid_with="payme", paid_at=core_clock.now()
    )
    # Our buy answer was lost; Waxpeer has two live trades under the order.
    await make_trade(db_session, order, buy_unconfirmed_at=core_clock.now())
    wax = FakeTradeClient(get_redis())
    for listing in (1, 2):
        await wax.buy_one_p2p(
            item_id=listing, price_units=100, partner=1, token="FAKEFAKE", project_id=order.id
        )
    flagged = attentions("ambiguous_trade")
    await tick(db_session, wax, clock)
    order_row, trade = await load(db_session, order)
    assert order_row.status == "buying"
    assert trade.attention_reason == "ambiguous_trade"
    assert attentions("ambiguous_trade") == flagged + 1


# --- dev routes: refusals and gates --------------------------------------------------------


async def test_actions_out_of_order_are_409(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    to_buy: Order,
    clock: Clock,
) -> None:
    url = f"/api/v1/dev/orders/{to_buy.number}/trade"
    r = await integration_client.post(url, headers=headers, json={"action": "accept"})
    assert (r.status_code, r.json()["code"]) == (409, "fake_trade_missing")

    await bought(db_session, FakeTradeClient(get_redis()), to_buy)
    for action in ("accept", "rollback"):  # the offer is not out yet / nothing accepted
        r = await integration_client.post(url, headers=headers, json={"action": action})
        assert (r.status_code, r.json()["code"]) == (409, "fake_trade_state"), action

    clock.advance(seconds=6)
    await act(integration_client, headers, to_buy, "decline")
    r = await integration_client.post(url, headers=headers, json={"action": "accept"})
    assert r.status_code == 409
    r = await integration_client.post(url, headers=headers, json={"action": "explode"})
    assert r.status_code == 422


async def test_a_rollback_is_a_no_op_when_repeated(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    to_buy: Order,
    clock: Clock,
) -> None:
    await bought(db_session, FakeTradeClient(get_redis()), to_buy)
    clock.advance(seconds=6)
    await act(integration_client, headers, to_buy, "accept")
    first = await act(integration_client, headers, to_buy, "rollback")
    assert await act(integration_client, headers, to_buy, "rollback") == first
    r = await integration_client.post(
        f"/api/v1/dev/orders/{to_buy.number}/trade", headers=headers, json={"action": "decline"}
    )
    assert r.status_code == 409


async def test_only_the_buyer_drives_their_trade(
    integration_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    theirs = await make_order(db_session, status="buying")
    for number in (theirs.number, "nope"):
        r = await integration_client.post(
            f"/api/v1/dev/orders/{number}/trade", headers=headers, json={"action": "accept"}
        )
        assert r.status_code == 404
    r = await integration_client.post(
        f"/api/v1/dev/orders/{theirs.number}/trade", json={"action": "accept"}
    )
    assert r.status_code == 401


async def test_the_balance_route_sets_the_fake_balance(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/dev/waxpeer/balance", headers=headers, json={"units": 25_000}
    )
    assert (r.status_code, r.json()) == (200, {"units": 25_000})
    assert await trade_client(cfg.get_settings()).balance_units() == 25_000
    r = await integration_client.post(
        "/api/v1/dev/waxpeer/balance", headers=headers, json={"units": -1}
    )
    assert r.status_code == 422
    r = await integration_client.post("/api/v1/dev/waxpeer/balance", json={"units": 1})
    assert r.status_code == 401


async def test_the_dev_routes_are_404_with_the_fake_off(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    monkeypatch.setenv("CSMARKET_WAXPEER_FAKE", "false")
    cfg.get_settings.cache_clear()
    try:
        r = await integration_client.post(
            "/api/v1/dev/waxpeer/balance", headers=headers, json={"units": 1}
        )
        assert r.status_code == 404
        r = await integration_client.post(
            "/api/v1/dev/orders/AAAAAAAA/trade", headers=headers, json={"action": "accept"}
        )
        assert r.status_code == 404
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_the_dev_routes_are_404_in_prod(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine
) -> None:
    from csmarket.bootstrap import create_app

    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "true")
    monkeypatch.setenv("CSMARKET_WAXPEER_FAKE", "false")
    cfg.get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for path, body in (
                ("/api/v1/dev/orders/AAAAAAAA/trade", {"action": "accept"}),
                ("/api/v1/dev/waxpeer/balance", {"units": 1}),
            ):
                r = await c.post(path, json=body)
                assert r.status_code == 404, path
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_the_dev_routes_are_not_in_the_openapi_schema(
    integration_client: AsyncClient,
) -> None:
    paths = (await integration_client.get("/openapi.json")).json()["paths"]
    assert "/api/v1/dev/orders/{number}/trade" not in paths
    assert "/api/v1/dev/waxpeer/balance" not in paths
