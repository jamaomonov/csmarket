"""Opening a P2P top-up (spec 2026-10-19-p2p-topup): limits, the card, the exact amount."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.p2p_factory import PAN, make_card, p2p_on

Headers = Callable[[], Awaitable[dict[str, str]]]
TOPUPS = "/api/v1/wallet/topups"


async def _open(
    c: AsyncClient, headers: dict[str, str], amount: int = 100_000, key: str | None = None
) -> Response:
    return await c.post(
        TOPUPS,
        json={"amount_uzs": amount, "provider": "p2p", "locale": "ru"},
        headers={**headers, "Idempotency-Key": key or f"p2p-{uuid.uuid4()}"},
    )


def _p2p(r: Response) -> Any:
    assert r.status_code == 201, r.text
    return r.json()["p2p"]


async def test_p2p_is_off_until_switched_on(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await make_card(db_session)
    r = await _open(integration_client, await customer_headers())
    assert (r.status_code, r.json()["code"]) == (409, "provider_disabled")


async def test_a_request_shows_the_whole_card_and_the_exact_amount(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await p2p_on(db_session)
    await make_card(db_session)
    r = await _open(integration_client, await customer_headers())
    p2p = _p2p(r)
    assert (p2p["card_number"], p2p["holder"], p2p["amount_uzs"]) == (PAN, "TEST HOLDER", "100000")
    assert p2p["status"] == "pending"
    assert r.json()["intent_url"] is None
    assert r.json()["amount_uzs"] == "100000"


async def test_the_same_amount_open_on_the_card_is_bumped_and_credited_whole(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    customer_headers: Headers,
    admin_headers: Headers,
) -> None:
    await p2p_on(db_session)
    await make_card(db_session)
    first = _p2p(await _open(integration_client, await customer_headers()))
    second = await _open(integration_client, await admin_headers())
    assert first["amount_uzs"] == "100000"
    assert _p2p(second)["amount_uzs"] == "100001"
    assert second.json()["amount_uzs"] == "100001"  # the whole transfer reaches the balance


async def test_a_replayed_key_returns_the_same_request(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await p2p_on(db_session)
    await make_card(db_session)
    h = await customer_headers()
    key = f"p2p-{uuid.uuid4()}"
    first = await _open(integration_client, h, key=key)
    again = await _open(integration_client, h, key=key)
    assert again.status_code == 201, again.text
    assert again.json()["number"] == first.json()["number"]


async def test_limits(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await p2p_on(db_session)
    await make_card(db_session)
    h = await customer_headers()
    low = await _open(integration_client, h, amount=5_000)
    assert (low.status_code, low.json()["code"]) == (422, "p2p_amount")
    assert _p2p(await _open(integration_client, h))
    second = await _open(integration_client, h)
    assert (second.status_code, second.json()["code"]) == (409, "p2p_open_request")


async def test_no_card_fits(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await p2p_on(db_session)
    await make_card(db_session, max_uzs=50_000)
    r = await _open(integration_client, await customer_headers(), amount=100_000)
    assert (r.status_code, r.json()["code"]) == (409, "p2p_unavailable")


async def test_a_card_daily_limit_counts_open_holds(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    customer_headers: Headers,
    admin_headers: Headers,
) -> None:
    await p2p_on(db_session)
    await make_card(db_session, daily_limit_uzs=150_000)
    assert _p2p(await _open(integration_client, await customer_headers()))
    r = await _open(integration_client, await admin_headers())
    assert (r.status_code, r.json()["code"]) == (409, "p2p_unavailable")


async def test_p2p_is_never_offered_at_checkout(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await p2p_on(db_session)
    body = (await integration_client.get("/api/v1/payments/providers")).json()
    p2p = next(p for p in body["providers"] if p["slug"] == "p2p")
    assert (p2p["status"], p2p["topup_only"]) == ("on", True)
