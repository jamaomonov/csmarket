"""Admin users API: switch the USD wallet, credit / claw back dollars (plan A, Task 5)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/users"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-usd-{uuid.uuid4()}"}


async def _audit(db: AsyncSession, action: str) -> list[AdminAuditLog]:
    return list(await db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == action)))


async def test_the_card_starts_with_the_usd_wallet_off_and_empty(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    card = (await integration_client.get(f"{BASE}/{target.id}", headers=h)).json()
    assert (card["usd_wallet_enabled"], card["balance_usd"], card["usd_entries"]) == (
        False,
        "0.000",
        [],
    )


async def test_switch_on_and_off_is_audited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/usd-wallet"
    r = await integration_client.put(
        url, json={"enabled": True, "reason": "pilot partner"}, headers={**h, **_key()}
    )
    assert r.status_code == 200, r.text
    assert r.json()["usd_wallet_enabled"] is True
    r = await integration_client.put(
        url, json={"enabled": False, "reason": "pilot over"}, headers={**h, **_key()}
    )
    assert r.json()["usd_wallet_enabled"] is False
    rows = await _audit(db_session, "wallet.usd_switch")
    assert sorted((r.payload["enabled"], r.payload["reason"]) for r in rows) == [
        (False, "pilot over"),
        (True, "pilot partner"),
    ]
    assert {(r.target_type, r.target_id) for r in rows} == {("user", target.id)}
    stored = await db_session.scalar(select(User.usd_wallet_enabled).where(User.id == target.id))
    assert stored is False


async def test_a_replayed_switch_audits_once(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = {**(await admin_headers()), **_key()}
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/usd-wallet"
    body = {"enabled": True, "reason": "pilot partner"}
    first = await integration_client.put(url, json=body, headers=h)
    again = await integration_client.put(url, json=body, headers=h)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(await _audit(db_session, "wallet.usd_switch")) == 1
    other = await integration_client.put(
        url, json={"enabled": False, "reason": "pilot partner"}, headers=h
    )
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_mismatch")


async def test_credit_shows_in_the_usd_lines_and_is_audited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/wallet/adjust-usd"
    r = await integration_client.post(
        url, json={"amount_usd": "250.000", "reason": "pilot float"}, headers={**h, **_key()}
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["balance_usd"] == "250.000"
    assert card["balance_uzs"] == "0"
    (line,) = card["usd_entries"]
    assert (line["kind"], line["currency"], line["amount_usd"]) == (
        "admin_adjust_usd",
        "USD",
        "+250.000",
    )
    assert line["reason"] == "pilot float"
    assert card["entries"] == []
    (row,) = await _audit(db_session, "wallet.adjust_usd")
    assert (row.payload["amount_usd"], row.payload["reason"]) == ("250.000", "pilot float")


async def test_a_clawback_below_zero_is_409_and_writes_nothing(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/wallet/adjust-usd"
    await integration_client.post(
        url, json={"amount_usd": "250.000", "reason": "pilot float"}, headers={**h, **_key()}
    )
    r = await integration_client.post(
        url, json={"amount_usd": "-300.000", "reason": "too much"}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (409, "balance_too_low")
    assert len(await _audit(db_session, "wallet.adjust_usd")) == 1


async def test_a_replayed_adjust_posts_once(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = {**(await admin_headers()), **_key()}
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/wallet/adjust-usd"
    body = {"amount_usd": "10.500", "reason": "goodwill"}
    first = await integration_client.post(url, json=body, headers=h)
    again = await integration_client.post(url, json=body, headers=h)
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    assert again.json()["balance_usd"] == "10.500"
    assert len(await _audit(db_session, "wallet.adjust_usd")) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"amount_usd": "1.2345", "reason": "goodwill"},
        {"amount_usd": "0", "reason": "goodwill"},
        {"amount_usd": "0.000", "reason": "goodwill"},
        {"amount_usd": "100000.001", "reason": "goodwill"},
        {"amount_usd": "-100000.001", "reason": "goodwill"},
        {"amount_usd": "abc", "reason": "goodwill"},
        {"amount_usd": 5, "reason": "goodwill"},
        {"amount_usd": "5.000", "reason": "abc"},
    ],
)
async def test_adjust_usd_refuses_a_bad_body(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    body: dict[str, object],
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    r = await integration_client.post(
        f"{BASE}/{target.id}/wallet/adjust-usd", json=body, headers={**h, **_key()}
    )
    assert r.status_code == 422, r.text
    assert await db_session.scalar(select(func.count()).select_from(AdminAuditLog)) == 0


async def test_a_customer_is_403_on_the_usd_routes(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    target = await make_user(db_session)
    r = await integration_client.put(
        f"{BASE}/{target.id}/usd-wallet",
        json={"enabled": True, "reason": "sneaky"},
        headers={**h, **_key()},
    )
    assert r.status_code == 403, r.text
    r = await integration_client.post(
        f"{BASE}/{target.id}/wallet/adjust-usd",
        json={"amount_usd": "5.000", "reason": "sneaky"},
        headers={**h, **_key()},
    )
    assert r.status_code == 403, r.text
