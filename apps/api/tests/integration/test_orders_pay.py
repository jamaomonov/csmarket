"""``POST /orders/{number}/pay``: from the balance in one transaction (ruling R8) or through a
kassa; the replay, the races, the refusals; and the dev-only mock pay route."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import pytest
from csmarket.core import clock as core_clock
from csmarket.core import config as cfg
from csmarket.core.errors import AppError
from csmarket.core.ids import new_id
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.paying import pay_order
from csmarket.modules.payments.hooks import ensure_attempt, settle
from csmarket.modules.payments.models import Payment
from csmarket.modules.payments.payable import resolve
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_topup, user_balance
from csmarket.modules.wallet.models import WalletTransaction
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import listen_orders, make_order
from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio

PRICE = Decimal(171_800)


# --- fixtures and helpers ------------------------------------------------------------------


@pytest.fixture
async def headers(integration_client: AsyncClient) -> dict[str, str]:
    """The buyer's Bearer header (signed in through dev login)."""
    return await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)


@pytest.fixture
async def buyer(headers: dict[str, str], db_session: AsyncSession) -> User:
    user = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


@pytest.fixture
async def pending_order(db_session: AsyncSession, buyer: User) -> Order:
    return await make_order(db_session, user=buyer, price_uzs=PRICE)


class _Clock:
    """``core.clock`` moved forward by :meth:`advance`."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def advance(self, **delta: float) -> None:
        self.offset += timedelta(**delta)

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset


@pytest.fixture
def clock() -> Iterator[_Clock]:
    fake = _Clock()
    core_clock.set_clock(fake.now)
    yield fake
    core_clock.reset_clock()


def _key(headers: dict[str, str] | None = None, key: str | None = None) -> dict[str, str]:
    return {**(headers or {}), "Idempotency-Key": key or f"pay-{uuid.uuid4()}"}


async def _pay(
    api: AsyncClient,
    headers: dict[str, str],
    number: str,
    *,
    provider: str = "wallet",
    locale: str = "ru",
    key: str | None = None,
) -> Response:
    return await api.post(
        f"/api/v1/orders/{number}/pay",
        headers=_key(headers, key),
        json={"provider": provider, "locale": locale},
    )


async def credit(db: AsyncSession, user: User, amount: int) -> None:
    await credit_topup(
        db, user_id=user.id, topup_id=new_id(), amount=Decimal(amount), provider="mock"
    )
    await db.commit()


async def purchase_count(db: AsyncSession, order_id: str) -> int:
    stmt = (
        select(func.count())
        .select_from(WalletTransaction)
        .where(WalletTransaction.kind == "purchase", WalletTransaction.reference_id == order_id)
    )
    return int(await db.scalar(stmt) or 0)


async def _payments(db: AsyncSession, order_id: str) -> list[Payment]:
    stmt = (
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at)
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(stmt)).scalars())


async def _order(db: AsyncSession, order_id: str) -> Order:
    stmt = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


# --- from the balance ----------------------------------------------------------------------


async def test_wallet_pay_twice_debits_once(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    await credit(db_session, buyer, 500_000)
    key = f"pay-{uuid.uuid4()}"
    first = await _pay(integration_client, headers, pending_order.number, key=key)
    second = await _pay(integration_client, headers, pending_order.number, key=key)
    assert first.status_code == second.status_code == 200, first.text
    assert second.json() == first.json()
    body = first.json()
    assert body["intent_url"] is None
    assert (body["order"]["number"], body["order"]["status"]) == (pending_order.number, "paid")
    assert (body["order"]["paid_with"], body["order"]["payable"]) == ("wallet", False)
    assert body["order"]["paid_at"] is not None
    assert await purchase_count(db_session, pending_order.id) == 1
    assert await user_balance(db_session, buyer.id) == 500_000 - pending_order.price_uzs
    [payment] = await _payments(db_session, pending_order.id)
    assert (payment.provider, payment.status, payment.provider_ref) == (
        "wallet",
        "succeeded",
        f"wallet:{pending_order.number}",
    )
    assert (payment.purpose, payment.amount_uzs, payment.user_id) == ("order", PRICE, buyer.id)
    assert payment.succeeded_at is not None
    order = await _order(db_session, pending_order.id)
    assert (order.status, order.paid_with) == ("paid", "wallet")


async def test_wallet_pay_notifies_the_worker_once(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    await credit(db_session, buyer, 500_000)
    key = f"pay-{uuid.uuid4()}"
    async with listen_orders() as listener:
        for _ in range(2):
            r = await _pay(integration_client, headers, pending_order.number, key=key)
            assert r.status_code == 200, r.text
        assert await listener.drain() == [pending_order.number]


async def test_the_same_key_with_another_body_is_a_mismatch(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    await credit(db_session, buyer, 500_000)
    key = f"pay-{uuid.uuid4()}"
    assert (await _pay(integration_client, headers, pending_order.number, key=key)).is_success
    r = await _pay(integration_client, headers, pending_order.number, key=key, provider="mock")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "idempotency_mismatch"
    r = await _pay(integration_client, headers, pending_order.number, key=key, locale="uz")
    assert r.json()["code"] == "idempotency_mismatch"


async def test_a_short_balance_is_409_and_changes_nothing(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    await credit(db_session, buyer, int(PRICE) - 1)
    async with listen_orders() as listener:
        r = await _pay(integration_client, headers, pending_order.number)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "balance_too_low"
        assert await listener.drain() == []
    assert await _payments(db_session, pending_order.id) == []
    assert await purchase_count(db_session, pending_order.id) == 0
    assert (await _order(db_session, pending_order.id)).status == "pending"
    assert await user_balance(db_session, buyer.id) == PRICE - 1


async def test_a_refused_key_can_pay_once_the_balance_covers_it(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    key = f"pay-{uuid.uuid4()}"
    r = await _pay(integration_client, headers, pending_order.number, key=key)
    assert r.json()["code"] == "balance_too_low"  # a refusal stores no replay
    await credit(db_session, buyer, int(PRICE))
    r = await _pay(integration_client, headers, pending_order.number, key=key)
    assert r.status_code == 200, r.text
    assert await user_balance(db_session, buyer.id) == 0


async def test_pay_after_expiry_is_409(
    *,
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
    clock: _Clock,
) -> None:
    await credit(db_session, buyer, 500_000)
    clock.advance(minutes=16)
    r = await _pay(integration_client, headers, pending_order.number)
    assert r.status_code == 409
    assert r.json()["code"] == "order_not_payable"
    assert r.json()["reason"] == "expired"
    assert await purchase_count(db_session, pending_order.id) == 0


@pytest.mark.parametrize("provider", ["wallet", "mock"])
async def test_a_cancelled_order_is_not_payable(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    provider: str,
) -> None:
    await credit(db_session, buyer, 500_000)
    order = await make_order(db_session, user=buyer, status="cancelled")
    r = await _pay(integration_client, headers, order.number, provider=provider)
    assert r.status_code == 409, r.text
    assert (r.json()["code"], r.json()["reason"]) == ("order_not_payable", "expired")
    assert await _payments(db_session, order.id) == []


@pytest.mark.parametrize("second", ["wallet", "mock"])
async def test_a_paid_order_refuses_another_payment(
    *,
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
    second: str,
) -> None:
    await credit(db_session, buyer, 1_000_000)
    assert (await _pay(integration_client, headers, pending_order.number)).status_code == 200
    r = await _pay(integration_client, headers, pending_order.number, provider=second)
    assert r.status_code == 409, r.text
    assert (r.json()["code"], r.json()["reason"]) == ("order_not_payable", "paid")
    assert await purchase_count(db_session, pending_order.id) == 1
    assert len(await _payments(db_session, pending_order.id)) == 1


async def test_a_kassa_paid_order_refuses_the_balance(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    await credit(db_session, buyer, 1_000_000)
    attempt = await ensure_attempt(
        db_session,
        payable=await resolve(db_session, pending_order.number, lock=True),
        provider="mock",
    )
    await settle(db_session, payment=attempt, event_id="e1")
    await db_session.commit()
    r = await _pay(integration_client, headers, pending_order.number)
    assert (r.status_code, r.json()["reason"]) == (409, "paid")
    assert await user_balance(db_session, buyer.id) == 1_000_000


# --- races ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    kind: str  # "ok" | "conflict"
    code: str


async def _one(
    factory: async_sessionmaker[AsyncSession], call: Callable[[AsyncSession], Awaitable[Any]]
) -> Outcome:
    async with factory() as db:
        try:
            await call(db)
        except AppError as err:
            await db.rollback()
            status, code = err.status_code, str(err.extra.get("code"))
        else:
            return Outcome("ok", "ok")
    assert status == 409, code
    return Outcome("conflict", code)


async def race(engine: AsyncEngine, buyer: User, numbers: list[str]) -> list[Outcome]:
    """Pay each of ``numbers`` from the balance in its own session, with its own key, at once."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    barrier = asyncio.Barrier(len(numbers))

    async def _call(number: str) -> Outcome:
        async def _pay_it(db: AsyncSession) -> None:
            await barrier.wait()
            await pay_order(
                db,
                user_id=buyer.id,
                number=number,
                provider="wallet",
                locale="ru",
                idempotency_key=f"pay-{uuid.uuid4()}",
            )

        return await _one(factory, _pay_it)

    return list(await asyncio.wait_for(asyncio.gather(*map(_call, numbers)), timeout=15))


async def test_concurrent_wallet_pay_one_payment(
    db_engine: AsyncEngine, db_session: AsyncSession, buyer: User, pending_order: Order
) -> None:
    """Two sessions, two keys, released together: one pays, the other gets 409."""
    await credit(db_session, buyer, 1_000_000)
    results = await race(db_engine, buyer, [pending_order.number, pending_order.number])
    assert sorted(r.kind for r in results) == ["conflict", "ok"]
    assert [r.code for r in results if r.kind == "conflict"] == ["order_not_payable"]
    assert len(await _payments(db_session, pending_order.id)) == 1
    assert await purchase_count(db_session, pending_order.id) == 1
    assert await user_balance(db_session, buyer.id) == 1_000_000 - PRICE


async def test_the_same_key_racing_replays_instead_of_refusing(
    db_engine: AsyncEngine, db_session: AsyncSession, buyer: User, pending_order: Order
) -> None:
    """A double-click: one key, two requests at once — both answer 200 with one payment."""
    await credit(db_session, buyer, 1_000_000)
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    barrier = asyncio.Barrier(2)
    key = f"pay-{uuid.uuid4()}"

    async def _pay_it(db: AsyncSession) -> None:
        await barrier.wait()
        await pay_order(
            db,
            user_id=buyer.id,
            number=pending_order.number,
            provider="wallet",
            locale="ru",
            idempotency_key=key,
        )

    results = await asyncio.wait_for(
        asyncio.gather(_one(factory, _pay_it), _one(factory, _pay_it)), timeout=15
    )
    assert [r.kind for r in results] == ["ok", "ok"]
    assert await purchase_count(db_session, pending_order.id) == 1


async def test_two_orders_racing_for_one_balance_never_overdraw(
    db_engine: AsyncEngine, db_session: AsyncSession, buyer: User
) -> None:
    """The wallet lock serialises two different orders: the second sees the spent balance."""
    await credit(db_session, buyer, int(PRICE))
    a = await make_order(db_session, user=buyer, price_uzs=PRICE)
    b = await make_order(db_session, user=buyer, price_uzs=PRICE)
    results = await race(db_engine, buyer, [a.number, b.number])
    assert sorted(r.code for r in results) == ["balance_too_low", "ok"]
    assert await user_balance(db_session, buyer.id) == 0


# --- through a kassa -----------------------------------------------------------------------


async def test_a_kassa_pay_returns_the_intent_and_reuses_the_live_attempt(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    pending_order: Order,
) -> None:
    first = await _pay(integration_client, headers, pending_order.number, provider="mock")
    assert first.status_code == 200, first.text
    body = first.json()
    url = urlsplit(body["intent_url"])
    assert url.path == f"/orders/{pending_order.number}"
    assert url.query == "mock=1"
    assert (body["order"]["status"], body["order"]["payable"]) == ("pending", True)
    second = await _pay(
        integration_client, headers, pending_order.number, provider="mock", locale="en"
    )
    assert second.status_code == 200, second.text
    assert urlsplit(second.json()["intent_url"]).path == f"/en/orders/{pending_order.number}"
    [attempt] = await _payments(db_session, pending_order.id)
    assert (attempt.provider, attempt.status, attempt.amount_uzs) == ("mock", "created", PRICE)
    assert await purchase_count(db_session, pending_order.id) == 0


async def test_a_kassa_pay_replays_its_stored_answer(
    integration_client: AsyncClient, headers: dict[str, str], pending_order: Order
) -> None:
    key = f"pay-{uuid.uuid4()}"
    a = await _pay(integration_client, headers, pending_order.number, provider="mock", key=key)
    b = await _pay(integration_client, headers, pending_order.number, provider="mock", key=key)
    assert (a.status_code, b.status_code) == (200, 200)
    assert a.json() == b.json()


async def test_a_kassa_that_is_not_available_is_422(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    pending_order: Order,
) -> None:
    """Click without credentials is not offered here."""
    r = await _pay(integration_client, headers, pending_order.number, provider="click")
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "order_provider"
    assert await _payments(db_session, pending_order.id) == []


async def test_the_balance_pays_an_order_a_kassa_attempt_was_opened_for(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
    pending_order: Order,
) -> None:
    await credit(db_session, buyer, 500_000)
    assert (
        await _pay(integration_client, headers, pending_order.number, provider="mock")
    ).is_success
    r = await _pay(integration_client, headers, pending_order.number)
    assert r.status_code == 200, r.text
    assert r.json()["order"]["paid_with"] == "wallet"
    providers = sorted(p.provider for p in await _payments(db_session, pending_order.id))
    assert providers == ["mock", "wallet"]


# --- who and what --------------------------------------------------------------------------


async def test_another_users_order_is_404(
    integration_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession, buyer: User
) -> None:
    await credit(db_session, buyer, 500_000)
    theirs = await make_order(db_session, user=await make_user(db_session))
    r = await _pay(integration_client, headers, theirs.number)
    assert r.status_code == 404, r.text
    assert await _payments(db_session, theirs.id) == []
    assert (await _order(db_session, theirs.id)).status == "pending"


@pytest.mark.parametrize("number", ["ZZZZZZZZ", "TAAAAAAA", "nope"])
async def test_unknown_or_malformed_numbers_are_404(
    integration_client: AsyncClient, headers: dict[str, str], number: str
) -> None:
    assert (await _pay(integration_client, headers, number)).status_code == 404


async def test_pay_needs_a_key_a_known_provider_and_a_session(
    integration_client: AsyncClient, headers: dict[str, str], pending_order: Order
) -> None:
    url = f"/api/v1/orders/{pending_order.number}/pay"
    body = {"provider": "wallet", "locale": "ru"}
    r = await integration_client.post(url, headers=headers, json=body)
    assert (r.status_code, r.json()["header"]) == (422, "Idempotency-Key")
    for bad in ({"provider": "cash", "locale": "ru"}, {"provider": "wallet", "locale": "de"}, {}):
        assert (
            await integration_client.post(url, headers=_key(headers), json=bad)
        ).status_code == 422
    extra = {**body, "amount": 1}
    assert (
        await integration_client.post(url, headers=_key(headers), json=extra)
    ).status_code == 422
    assert (await integration_client.post(url, headers=_key(), json=body)).status_code == 401


async def test_order_pay_bucket_is_charged_per_ip_and_account(
    integration_client: AsyncClient,
    headers: dict[str, str],
    pending_order: Order,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``order-pay`` trips at its own per-IP ceiling (a typo'd bucket would not)."""
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"order-pay": 3}')
    cfg.get_settings.cache_clear()
    try:
        h = {**headers, "X-Forwarded-For": "203.0.113.79"}
        for _ in range(3):
            assert (await _pay(integration_client, h, pending_order.number)).status_code == 409
        r = await _pay(integration_client, h, pending_order.number)
        assert r.status_code == 429, r.text
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_the_pay_route_is_in_the_openapi_schema(integration_client: AsyncClient) -> None:
    paths = (await integration_client.get("/openapi.json")).json()["paths"]
    assert "post" in paths["/api/v1/orders/{number}/pay"]
    assert "/api/v1/dev/orders/{number}/pay" not in paths


# --- dev: pay through the mock kassa -------------------------------------------------------


async def test_dev_pay_settles_through_the_mock_kassa(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    pending_order: Order,
) -> None:
    url = f"/api/v1/dev/orders/{pending_order.number}/pay"
    async with listen_orders() as listener:
        first = await integration_client.post(url, headers=headers)
        second = await integration_client.post(url, headers=headers)
        assert await listener.drain() == [pending_order.number]
    assert (first.status_code, second.status_code) == (200, 200), first.text
    assert (first.json()["status"], first.json()["paid_with"]) == ("paid", "mock")
    assert second.json()["status"] == "paid"
    [attempt] = await _payments(db_session, pending_order.id)
    assert (attempt.provider, attempt.status) == ("mock", "succeeded")
    assert attempt.extra_metadata["settle_event_id"] == f"mock:{attempt.id}"
    assert await purchase_count(db_session, pending_order.id) == 0


async def test_dev_pay_settles_the_attempt_the_pay_route_opened(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    pending_order: Order,
) -> None:
    assert (
        await _pay(integration_client, headers, pending_order.number, provider="mock")
    ).is_success
    r = await integration_client.post(
        f"/api/v1/dev/orders/{pending_order.number}/pay", headers=headers
    )
    assert r.status_code == 200, r.text
    [attempt] = await _payments(db_session, pending_order.id)
    assert attempt.status == "succeeded"


async def test_dev_pay_refuses_an_expired_order_and_others_orders(
    integration_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    buyer: User,
) -> None:
    expired = await make_order(
        db_session, user=buyer, expires_at=core_clock.now() - timedelta(minutes=1)
    )
    r = await integration_client.post(f"/api/v1/dev/orders/{expired.number}/pay", headers=headers)
    assert (r.status_code, r.json()["code"], r.json()["reason"]) == (
        409,
        "order_not_payable",
        "expired",
    )
    theirs = await make_order(db_session)
    r = await integration_client.post(f"/api/v1/dev/orders/{theirs.number}/pay", headers=headers)
    assert r.status_code == 404
    assert (
        await integration_client.post("/api/v1/dev/orders/nope/pay", headers=headers)
    ).status_code == 404
    assert (await _order(db_session, theirs.id)).status == "pending"


async def test_dev_pay_is_404_in_prod(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine
) -> None:
    from csmarket.bootstrap import create_app

    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "true")
    cfg.get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/v1/dev/orders/AAAAAAAA/pay")
        assert r.status_code == 404
        assert r.json()["type"] == "https://csmarket.uz/errors/not-found"
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_dev_pay_is_404_when_dev_login_is_off(
    integration_client: AsyncClient,
    headers: dict[str, str],
    pending_order: Order,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "false")
    cfg.get_settings.cache_clear()
    try:
        r = await integration_client.post(
            f"/api/v1/dev/orders/{pending_order.number}/pay", headers=headers
        )
        assert r.status_code == 404
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
