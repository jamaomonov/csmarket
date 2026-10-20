"""Kassa switches over HTTP (spec 2026-10-19-p2p-topup): a maintenance kassa is listed but
refuses new payments, an off one is hidden and refuses too, an open payment still settles."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from csmarket.modules.payments.api import settle
from csmarket.modules.payments.models import Payment
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.kassa_fee_factory import set_fees

Headers = Callable[[], Awaitable[dict[str, str]]]
TOPUPS = "/api/v1/wallet/topups"


async def _topup(c: AsyncClient, headers: dict[str, str], provider: str = "mock") -> object:
    return await c.post(
        TOPUPS,
        json={"amount_uzs": 50_000, "provider": provider, "locale": "ru"},
        headers={**headers, "Idempotency-Key": f"topup-{uuid.uuid4()}"},
    )


async def test_maintenance_is_listed_with_its_status_and_off_is_hidden(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await set_fees(db_session, statuses={"mock": "maintenance"})
    body = (await integration_client.get("/api/v1/payments/providers")).json()
    mock = next(p for p in body["providers"] if p["slug"] == "mock")
    assert (mock["status"], mock["topup_only"]) == ("maintenance", False)
    await set_fees(db_session, statuses={"mock": "off"})
    body = (await integration_client.get("/api/v1/payments/providers")).json()
    assert all(p["slug"] != "mock" for p in body["providers"])


async def test_a_new_topup_is_refused_in_maintenance_and_when_off(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    h = await customer_headers()
    await set_fees(db_session, statuses={"mock": "maintenance"})
    r = await _topup(integration_client, h)
    assert (r.status_code, r.json()["code"]) == (409, "provider_maintenance")  # type: ignore[attr-defined]
    await set_fees(db_session, statuses={"mock": "off"})
    r = await _topup(integration_client, h)
    assert (r.status_code, r.json()["code"]) == (409, "provider_disabled")  # type: ignore[attr-defined]


async def test_an_open_payment_still_settles_after_the_switch(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    h = await customer_headers()
    r = await _topup(integration_client, h)
    number = r.json()["number"]  # type: ignore[attr-defined]
    await set_fees(db_session, statuses={"mock": "off"})
    payment = await db_session.scalar(select(Payment).where(Payment.number == number))
    assert payment is not None
    await settle(db_session, payment=payment, event_id="late-1")
    await db_session.commit()
    seen = (await integration_client.get(f"{TOPUPS}/{number}", headers=h)).json()
    assert seen["status"] == "succeeded"


async def test_a_kassa_without_credentials_is_shown_only_in_maintenance(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    """Owner 2026-10-20: Uzum's tile shows greyed «Технические работы» before its keys exist.
    «on» without keys still hides it — the kassa cannot take money — and a top-up through it
    is refused (422: no keys, not a payable kassa)."""
    await set_fees(db_session, statuses={"uzum": "on"})
    body = (await integration_client.get("/api/v1/payments/providers")).json()
    assert all(p["slug"] != "uzum" for p in body["providers"])
    await set_fees(db_session, statuses={"uzum": "maintenance"})
    body = (await integration_client.get("/api/v1/payments/providers")).json()
    uzum = next(p for p in body["providers"] if p["slug"] == "uzum")
    assert uzum["status"] == "maintenance"
    r = await _topup(integration_client, await customer_headers(), provider="uzum")
    assert r.status_code == 422  # type: ignore[attr-defined]  # no keys: not a payable kassa
