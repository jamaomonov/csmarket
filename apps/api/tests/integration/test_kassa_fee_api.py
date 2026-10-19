"""The kassa fee over HTTP: the providers list, a top-up's fee and total, and the admin's
«Настройки оплаты» (spec 2026-10-14-kassa-fee)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from csmarket.core import config as cfg
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.kassa_fee_factory import set_fees

Headers = Callable[[], Awaitable[dict[str, str]]]
URL = "/api/v1/admin/payments/settings"


async def test_providers_carry_their_fee(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_PAYME_MERCHANT_ID", "m" * 24)
    monkeypatch.setenv("CSMARKET_PAYME_KEY", "k" * 36)
    cfg.get_settings.cache_clear()
    try:
        await set_fees(db_session, payme="1.5")
        body = (await integration_client.get("/api/v1/payments/providers")).json()
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
    assert {p["slug"]: p["fee_pct"] for p in body["providers"]} == {"payme": "1.5", "mock": "0"}


async def test_admin_reads_and_saves_the_fees_with_audit(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    empty = (await integration_client.get(URL, headers=h)).json()
    assert empty["updated_at"] is None
    assert empty["settings"] == {"click": "0", "payme": "0", "uzum": "0", "statuses": {}}
    r = await integration_client.put(
        URL,
        json={"click": "1", "payme": "1.5", "uzum": "2"},
        headers={**h, "Idempotency-Key": "k" * 20, "If-Match": "none"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["payme"] == "1.5"
    assert r.json()["updated_by"] is not None
    stale = await integration_client.put(
        URL,
        json={"click": "0", "payme": "0", "uzum": "0"},
        headers={**h, "Idempotency-Key": "m" * 20, "If-Match": "none"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "settings_stale"
    audit = (await integration_client.get("/api/v1/admin/audit", headers=h)).json()
    assert any(row["action"] == "payments.settings.save" for row in audit["items"])


async def test_a_rate_above_ten_is_refused(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    r = await integration_client.put(
        URL,
        json={"click": "10.5", "payme": "0", "uzum": "0"},
        headers={**h, "Idempotency-Key": "z" * 20},
    )
    assert r.status_code == 422


async def test_a_customer_cannot_touch_the_settings(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    assert (await integration_client.get(URL, headers=h)).status_code == 403


async def test_a_replayed_save_answers_the_same_and_a_bad_version_is_422(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    body = {"click": "1", "payme": "0", "uzum": "0"}
    headers = {**h, "Idempotency-Key": "r" * 20, "If-Match": "none"}
    first = await integration_client.put(URL, json=body, headers=headers)
    again = await integration_client.put(URL, json=body, headers=headers)
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    bad = await integration_client.put(
        URL, json=body, headers={**h, "Idempotency-Key": "b" * 20, "If-Match": "yesterday"}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "if_match"
