"""``/api/v1/wallet`` — the dollar block, conversion and dollar history (plan A, Task 4)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.fx.service import record_snapshot
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import admin_adjust, user_balance, user_usd_balance
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID

Headers = Callable[[], Awaitable[dict[str, str]]]
ADMIN = "00000000-0000-4000-8000-000000000001"
KEY = "web-convert-000000000001"
EXPECTED = {
    "amount_uzs": "100000",
    "amount_usd": "7.826",
    "rate_uzs": "12777.01",
    "balance_uzs": "50000",
    "balance_usd": "7.826",
}


@pytest.fixture
async def uplift_one(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """The uplift pinned to 1 % whatever the default is."""
    monkeypatch.setenv("CSMARKET_FX_UPLIFT_PCT", "1")
    cfg.get_settings.cache_clear()
    yield
    monkeypatch.delenv("CSMARKET_FX_UPLIFT_PCT")
    cfg.get_settings.cache_clear()


async def _customer(db: AsyncSession) -> User:
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


async def _setup(
    db: AsyncSession, *, usd: bool = True, soum: int = 150_000, rate: bool = True
) -> str:
    """Sign-in row exists (the caller logged in); switch the wallet, fund, seed the rate."""
    user = await _customer(db)
    user.usd_wallet_enabled = usd
    if soum:
        await admin_adjust(
            db,
            user_id=user.id,
            amount=Decimal(soum),
            reason="seed",
            admin_id=ADMIN,
            idempotency_key=f"seed-{user.id}",
        )
    if rate:
        snap: FxSnapshot = await record_snapshot(db, rate=Decimal("12650.5"), source="cbu")
        assert snap.id
    await db.commit()
    return user.id


async def _convert(
    c: AsyncClient, h: dict[str, str], amount: int = 100_000, key: str = KEY
) -> object:
    return await c.post(
        "/api/v1/wallet/convert",
        json={"amount_uzs": amount},
        headers={**h, "Idempotency-Key": key},
    )


async def test_balance_has_no_usd_block_until_an_admin_switches_it_on(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    body = (await integration_client.get("/api/v1/wallet", headers=h)).json()
    assert body == {"balance_uzs": "0", "usd": None}


async def test_the_usd_block_without_a_rate_has_a_null_rate(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session, soum=0, rate=False)
    body = (await integration_client.get("/api/v1/wallet", headers=h)).json()
    assert body["usd"] == {"balance_usd": "0.000", "rate_uzs": None}


@pytest.mark.usefixtures("uplift_one")
async def test_convert_moves_soum_into_dollars(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    uid = await _setup(db_session)
    r = await _convert(integration_client, h)
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    assert r.json() == EXPECTED  # type: ignore[attr-defined]
    again = await _convert(integration_client, h)
    assert again.status_code == 200  # type: ignore[attr-defined]
    assert again.json() == r.json()  # type: ignore[attr-defined]
    db_session.expire_all()
    assert await user_balance(db_session, uid) == Decimal(50_000)
    assert await user_usd_balance(db_session, uid) == Decimal(7826)
    usd = (await integration_client.get("/api/v1/wallet", headers=h)).json()["usd"]
    assert usd == {"balance_usd": "7.826", "rate_uzs": "12777.01"}
    lines = (await integration_client.get("/api/v1/wallet/entries?currency=usd", headers=h)).json()[
        "items"
    ]
    assert [(e["kind"], e["amount_usd"], e["currency"], e["amount_uzs"]) for e in lines] == [
        ("fx_convert", "+7.826", "USD", "0")
    ]
    soum = (await integration_client.get("/api/v1/wallet/entries", headers=h)).json()["items"]
    assert [(e["kind"], e["amount_uzs"], e["amount_usd"]) for e in soum] == [
        ("fx_convert", "-100000", None),
        ("admin_adjust", "+150000", None),
    ]


async def test_convert_without_the_usd_wallet_is_403(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session, usd=False)
    r = await _convert(integration_client, h)
    assert r.status_code == 403  # type: ignore[attr-defined]
    assert r.json()["code"] == "usd_wallet_disabled"  # type: ignore[attr-defined]


async def test_convert_without_a_rate_is_503(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session, rate=False)
    r = await _convert(integration_client, h)
    assert r.status_code == 503  # type: ignore[attr-defined]
    assert r.json()["code"] == "rate_unavailable"  # type: ignore[attr-defined]


@pytest.mark.usefixtures("uplift_one")
async def test_convert_more_than_the_balance_is_409(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session, soum=50_000)
    r = await _convert(integration_client, h, 50_001)
    assert r.status_code == 409  # type: ignore[attr-defined]
    assert r.json()["code"] == "balance_too_low"  # type: ignore[attr-defined]


@pytest.mark.usefixtures("uplift_one")
async def test_the_same_key_with_another_amount_is_409(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session)
    assert (await _convert(integration_client, h)).status_code == 201  # type: ignore[attr-defined]
    r = await _convert(integration_client, h, 20_000)
    assert r.status_code == 409  # type: ignore[attr-defined]
    assert r.json()["code"] == "idempotency_mismatch"  # type: ignore[attr-defined]


@pytest.mark.parametrize("amount", [999, 100_000_001, 0, -5])
async def test_convert_amount_out_of_range_is_422(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    amount: int,
) -> None:
    h = await customer_headers()
    await _setup(db_session)
    r = await _convert(integration_client, h, amount)
    assert r.status_code == 422  # type: ignore[attr-defined]


async def test_convert_needs_an_idempotency_key(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session)
    r = await integration_client.post(
        "/api/v1/wallet/convert", json={"amount_uzs": 100_000}, headers=h
    )
    assert r.status_code == 422


@pytest.mark.usefixtures("uplift_one")
async def test_a_160_character_key_converts_and_replays(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _setup(db_session)
    key = "k" * 160
    first = await _convert(integration_client, h, key=key)
    assert first.status_code == 201, first.text  # type: ignore[attr-defined]
    again = await _convert(integration_client, h, key=key)
    assert again.status_code == 200  # type: ignore[attr-defined]
    assert again.json() == first.json()  # type: ignore[attr-defined]
