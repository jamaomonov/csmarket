"""Customer top-ups over HTTP: create, replay, read, dev pay, providers (Task 4)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import user_balance
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.payments_factory import make_topup

Headers = Callable[[], Awaitable[dict[str, str]]]

TOPUPS = "/api/v1/wallet/topups"


def _key() -> str:
    return f"topup-{uuid.uuid4()}"


async def _create(
    c: AsyncClient,
    headers: dict[str, str],
    *,
    amount: Any = 50000,
    provider: str = "mock",
    locale: str = "ru",
    key: str | None = None,
) -> Any:
    return await c.post(
        TOPUPS,
        json={"amount_uzs": amount, "provider": provider, "locale": locale},
        headers={**headers, "Idempotency-Key": key or _key()},
    )


async def test_create_topup_returns_number_and_intent(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    r = await _create(integration_client, h)
    assert r.status_code == 201, r.text
    body = r.json()
    number = body["number"]
    assert number.startswith("T")
    assert len(number) == 8
    assert body["status"] == "pending"
    assert body["amount_uzs"] == "50000"
    assert body["provider"] == "mock"
    assert body["intent_url"] == (f"http://localhost:3100/account/balance/topups/{number}?mock=1")
    assert body["expires_at"]
    uz = (await _create(integration_client, h, locale="uz")).json()
    assert uz["intent_url"] == (
        f"http://localhost:3100/uz/account/balance/topups/{uz['number']}?mock=1"
    )


async def test_create_topup_opens_one_created_attempt(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    number = (await _create(integration_client, h)).json()["number"]
    topup = await db_session.scalar(select(WalletTopup).where(WalletTopup.number == number))
    assert topup is not None
    attempts = (
        (await db_session.execute(select(Payment).where(Payment.topup_id == topup.id)))
        .scalars()
        .all()
    )
    assert [(a.provider, a.status, a.amount_uzs) for a in attempts] == [
        ("mock", "created", Decimal(50000))
    ]
    window = topup.expires_at - clock.now()
    assert timedelta(minutes=29) < window <= timedelta(minutes=30)


async def test_limits(integration_client: AsyncClient, customer_headers: Headers) -> None:
    h = await customer_headers()
    for bad in (999, 10_000_001, 0, -5):
        r = await _create(integration_client, h, amount=bad)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["code"] == "topup_amount"
    for ok in (1000, 10_000_000):
        r = await _create(integration_client, h, amount=ok)
        assert r.status_code == 201, (ok, r.text)
        assert r.json()["amount_uzs"] == str(ok)


@pytest.mark.parametrize("amount", ["1000.5", 1000.5, "1000", True, None])
async def test_a_non_integer_amount_is_422(
    integration_client: AsyncClient, customer_headers: Headers, amount: Any
) -> None:
    r = await _create(integration_client, await customer_headers(), amount=amount)
    assert r.status_code == 422, r.text


async def test_unknown_or_unavailable_provider_is_422(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    for provider in ("paynet", "wallet", "click", "payme", "uzum"):
        r = await _create(integration_client, h, provider=provider)
        assert r.status_code == 422, (provider, r.text)
        assert r.json()["code"] == "topup_provider"


async def test_a_bad_locale_is_422(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    r = await _create(integration_client, await customer_headers(), locale="de")
    assert r.status_code == 422


async def test_replay_same_body_returns_same_topup(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    key = _key()
    first = await _create(integration_client, h, key=key)
    again = await _create(integration_client, h, key=key)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json() == again.json()
    assert await db_session.scalar(select(func.count()).select_from(WalletTopup)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Payment)) == 1


async def test_replay_different_amount_is_409(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    key = _key()
    assert (await _create(integration_client, h, key=key)).status_code == 201
    r = await _create(integration_client, h, key=key, amount=60000)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "idempotency_mismatch"


async def test_replay_different_provider_is_409(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
) -> None:
    """The key's top-up was opened in ``mock``; the same key for another kassa is not a replay.

    Only ``mock`` is available in tests, so the original attempt is re-labelled ``payme``.
    """
    h = await customer_headers()
    key = _key()
    number = (await _create(integration_client, h, key=key)).json()["number"]
    attempt = await db_session.scalar(select(Payment).where(Payment.number == number))
    assert attempt is not None
    attempt.provider = "payme"
    await db_session.commit()
    r = await _create(integration_client, h, key=key)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "idempotency_mismatch"


async def test_replay_after_the_kassa_became_unavailable_returns_the_topup(
    integration_client: AsyncClient, customer_headers: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kassa lost its credentials between the first call and the retry: the replay
    still answers the stored top-up (without a pay URL); a new key is refused."""
    from csmarket.modules.payments import topups

    h = await customer_headers()
    key = _key()
    first = await _create(integration_client, h, key=key)
    assert first.status_code == 201
    monkeypatch.setattr(topups, "available_providers", list)
    again = await _create(integration_client, h, key=key)
    assert again.status_code == 201, again.text
    assert again.json() == {**first.json(), "intent_url": None}
    fresh = await _create(integration_client, h)
    assert (fresh.status_code, fresh.json()["code"]) == (422, "topup_provider")


async def test_awaiting_kassa_tells_a_held_topup_from_an_expired_one(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    """Past ``expires_at`` both answer ``pending`` without a pay URL; only the one a kassa
    holds (an attempt in ``pending``) may still settle, and says so."""
    h = await customer_headers()
    created = [(await _create(integration_client, h)).json() for _ in range(2)]
    assert [c["awaiting_kassa"] for c in created] == [False, False]
    held, idle = (c["number"] for c in created)
    payable = await resolve(db_session, held, lock=True)
    attempt = await ensure_attempt(db_session, payable=payable, provider="mock")
    await mark_pending(db_session, payment=attempt)
    for topup in (await db_session.execute(select(WalletTopup))).scalars():
        topup.expires_at = clock.now() - timedelta(minutes=5)
    await db_session.commit()

    shown = {
        n: (await integration_client.get(f"{TOPUPS}/{n}", headers=h)).json() for n in (held, idle)
    }
    assert [
        (shown[n]["status"], shown[n]["intent_url"], shown[n]["awaiting_kassa"])
        for n in (held, idle)
    ] == [
        ("pending", None, True),
        ("pending", None, False),
    ]
    await settle(db_session, payment=attempt, event_id="held-then-paid")
    await db_session.commit()
    paid = (await integration_client.get(f"{TOPUPS}/{held}", headers=h)).json()
    assert (paid["status"], paid["awaiting_kassa"]) == ("succeeded", False)


async def test_the_same_key_from_another_user_is_a_new_topup(
    integration_client: AsyncClient, customer_headers: Headers, admin_headers: Headers
) -> None:
    key = _key()
    a = await _create(integration_client, await customer_headers(), key=key)
    b = await _create(integration_client, await admin_headers(), key=key)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["number"] != b.json()["number"]


async def test_missing_or_short_key_is_422(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    body = {"amount_uzs": 50000, "provider": "mock", "locale": "ru"}
    missing = await integration_client.post(TOPUPS, json=body, headers=h)
    assert missing.status_code == 422, missing.text
    short = await integration_client.post(
        TOPUPS, json=body, headers={**h, "Idempotency-Key": "short"}
    )
    assert short.status_code == 422, short.text
    long = await integration_client.post(
        TOPUPS, json=body, headers={**h, "Idempotency-Key": "k" * 161}
    )
    assert long.status_code == 422, long.text


async def test_anonymous_cannot_create_or_read(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        TOPUPS,
        json={"amount_uzs": 50000, "provider": "mock", "locale": "ru"},
        headers={"Idempotency-Key": _key()},
    )
    assert r.status_code == 401
    assert (await integration_client.get(f"{TOPUPS}/TAAAAAAA")).status_code == 401


async def test_owner_reads_the_topup(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    created = (await _create(integration_client, h)).json()
    r = await integration_client.get(f"{TOPUPS}/{created['number']}", headers=h)
    assert r.status_code == 200
    assert r.json() == created
    en = await integration_client.get(
        f"{TOPUPS}/{created['number']}", params={"locale": "en"}, headers=h
    )
    assert en.json()["intent_url"].startswith("http://localhost:3100/en/account/balance/topups/")


async def test_someone_elses_topup_is_404(
    integration_client: AsyncClient,
    customer_headers: Headers,
    admin_headers: Headers,
    db_session: AsyncSession,
) -> None:
    created = (await _create(integration_client, await customer_headers())).json()
    other = await admin_headers()
    r = await integration_client.get(f"{TOPUPS}/{created['number']}", headers=other)
    assert r.status_code == 404
    # A well-formed number nobody holds and a malformed one answer the same.
    assert (await integration_client.get(f"{TOPUPS}/TZZZZZZZ", headers=other)).status_code == 404
    assert (await integration_client.get(f"{TOPUPS}/nope", headers=other)).status_code == 404
    pay = await integration_client.post(
        f"/api/v1/dev/topups/{created['number']}/pay", headers=other
    )
    assert pay.status_code == 404


async def test_dev_pay_credits_once(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    number = (await _create(integration_client, h)).json()["number"]
    first = await integration_client.post(f"/api/v1/dev/topups/{number}/pay", headers=h)
    second = await integration_client.post(f"/api/v1/dev/topups/{number}/pay", headers=h)
    assert (first.status_code, second.status_code) == (200, 200), second.text
    assert first.json()["status"] == "succeeded"
    assert first.json()["intent_url"] is None
    assert second.json() == first.json()
    balance = await integration_client.get("/api/v1/wallet", headers=h)
    assert balance.json() == {"balance_uzs": "50000"}
    topup = await db_session.scalar(select(WalletTopup).where(WalletTopup.number == number))
    assert topup is not None
    assert await user_balance(db_session, topup.user_id) == Decimal(50000)
    attempt = await db_session.scalar(select(Payment).where(Payment.topup_id == topup.id))
    assert attempt is not None
    assert (attempt.status, topup.payment_id) == ("succeeded", attempt.id)


async def test_dev_pay_refuses_an_expired_topup(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    number = (await _create(integration_client, h)).json()["number"]
    topup = await db_session.scalar(select(WalletTopup).where(WalletTopup.number == number))
    assert topup is not None
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    r = await integration_client.post(f"/api/v1/dev/topups/{number}/pay", headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "topup_not_payable"
    shown = (await integration_client.get(f"{TOPUPS}/{number}", headers=h)).json()
    assert shown["intent_url"] is None


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
            r = await c.post("/api/v1/dev/topups/TAAAAAAA/pay")
        assert r.status_code == 404
        assert r.json()["type"] == "https://csmarket.uz/errors/not-found"
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_dev_pay_is_404_when_dev_login_is_off(
    integration_client: AsyncClient,
    customer_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = await customer_headers()
    number = (await _create(integration_client, h)).json()["number"]
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "false")
    cfg.get_settings.cache_clear()
    try:
        r = await integration_client.post(f"/api/v1/dev/topups/{number}/pay", headers=h)
        assert r.status_code == 404
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_dev_pay_is_not_in_the_openapi_schema(integration_client: AsyncClient) -> None:
    paths = (await integration_client.get("/openapi.json")).json()["paths"]
    assert "/api/v1/dev/topups/{number}/pay" not in paths
    assert "/api/v1/wallet/topups" in paths


async def test_a_late_settle_on_a_held_attempt_still_credits(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    """The kassa held the attempt before the window closed; its money still lands."""
    h = await customer_headers()
    number = (await _create(integration_client, h)).json()["number"]
    payable = await resolve(db_session, number, lock=True)
    attempt = await ensure_attempt(db_session, payable=payable, provider="mock")
    await mark_pending(db_session, payment=attempt)
    assert payable.topup is not None
    payable.topup.expires_at = clock.now() - timedelta(minutes=5)
    await db_session.commit()
    await settle(db_session, payment=attempt, event_id="late")
    await db_session.commit()
    shown = (await integration_client.get(f"{TOPUPS}/{number}", headers=h)).json()
    assert shown["status"] == "succeeded"
    assert (await integration_client.get("/api/v1/wallet", headers=h)).json() == {
        "balance_uzs": "50000"
    }


async def test_providers_endpoint_lists_mock_in_dev_only(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine
) -> None:
    r = await integration_client.get("/api/v1/payments/providers")
    assert r.status_code == 200
    assert r.json() == {"providers": [{"slug": "mock"}]}
    from csmarket.bootstrap import create_app

    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    cfg.get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            prod = await c.get("/api/v1/payments/providers")
        assert prod.json() == {"providers": []}
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_a_created_topup_for_someone_else_is_not_reachable_by_number(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    """A factory top-up (another user) is 404 for the signed-in customer."""
    t = await make_topup(db_session)
    r = await integration_client.get(f"{TOPUPS}/{t.number}", headers=await customer_headers())
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("amount", "outcome"), [(50000, "replayed"), (60000, "idempotency_mismatch")]
)
async def test_a_racing_request_with_the_same_key_is_matched_too(
    db_engine: AsyncEngine, amount: int, outcome: str
) -> None:
    """Both requests miss the pre-check; the loser's insert waits for the winner's commit,
    fails on the unique key, and is held to the same replay rule (YuPay's race path)."""
    import asyncio

    from csmarket.core.errors import ConflictError
    from csmarket.modules.payments.topups import create_topup
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from tests.integration.payments_factory import make_user

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        user = await make_user(setup)
    key = _key()
    kw: dict[str, Any] = {
        "user_id": user.id,
        "provider": "mock",
        "idempotency_key": key,
        "locale": "ru",
    }
    async with factory() as winner_db, factory() as loser_db:
        winner, _, _ = await create_topup(winner_db, amount_uzs=Decimal(50000), **kw)

        async def _loser() -> str:
            try:
                topup, _, _ = await create_topup(loser_db, amount_uzs=Decimal(amount), **kw)
            except ConflictError as exc:
                return str(exc.extra["code"])
            return "replayed" if topup.id == winner.id else "another top-up"

        task = asyncio.create_task(_loser())
        await asyncio.sleep(0.3)  # the loser now waits on the unique key
        assert not task.done()
        await winner_db.commit()
        assert await asyncio.wait_for(task, timeout=10) == outcome
        await loser_db.commit()
    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(WalletTopup)) == 1
        assert await check.scalar(select(func.count()).select_from(Payment)) == 1
