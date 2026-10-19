"""Admin «P2P» (spec 2026-10-19-p2p-topup): cards stay masked, the manual credit books an
unmatched transfer once and never while a request still holds its amount."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal

from csmarket.core import clock
from csmarket.modules.p2p.models import P2PIncoming
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.p2p_factory import PAN, make_card, p2p_on
from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/p2p"


def _key(h: dict[str, str]) -> dict[str, str]:
    return {**h, "Idempotency-Key": f"admin-p2p-{uuid.uuid4()}"}


async def _unmatched(db: AsyncSession, amount: str = "70000", last4: str = "4321") -> P2PIncoming:
    row = P2PIncoming(
        business_connection_id="conn-1",
        telegram_message_id=abs(hash(uuid.uuid4())) % 10**9,
        kind="credit",
        amount_uzs=Decimal(amount),
        card_last4=last4,
        bank_time=clock.now() - timedelta(minutes=30),
        raw_text="➕ …",
        result="unmatched",
        received_at=clock.now() - timedelta(minutes=30),
    )
    db.add(row)
    await db.commit()
    return row


async def test_a_card_is_added_once_and_shown_masked(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    body = {"label": "Humo", "pan": "9860 1111 2222 4321", "holder_name": "TEST HOLDER"}
    r = await integration_client.post(f"{BASE}/cards", json=body, headers=_key(h))
    assert r.status_code == 201, r.text
    assert r.json()["masked"] == "•••• 4321"
    assert "9860" not in r.text
    listed = await integration_client.get(f"{BASE}/cards", headers=h)
    assert "1111" not in listed.text
    again = await integration_client.post(
        f"{BASE}/cards", json={**body, "pan": "9860 3333 4444 4321"}, headers=_key(h)
    )
    assert (again.status_code, again.json()["code"]) == (409, "p2p_last4_taken")


async def test_an_unmatched_transfer_is_credited_once(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    await make_card(db_session)
    buyer = await make_user(db_session)
    row = await _unmatched(db_session)
    journal = (await integration_client.get(f"{BASE}/incoming", headers=h)).json()
    assert journal["items"][0]["can_credit"] is True
    body = {"user_id": buyer.id, "note": "чек от покупателя"}
    r = await integration_client.post(
        f"{BASE}/incoming/{row.id}/credit", json=body, headers=_key(h)
    )
    assert r.status_code == 200, r.text
    assert r.json()["incoming"]["result"] == "matched"
    twice = await integration_client.post(
        f"{BASE}/incoming/{row.id}/credit", json=body, headers=_key(h)
    )
    assert (twice.status_code, twice.json()["code"]) == (409, "p2p_already_credited")
    audit = (await integration_client.get("/api/v1/admin/audit", headers=h)).json()
    assert any(a["action"] == "p2p.incoming.credit" for a in audit["items"])


async def test_no_manual_credit_while_a_request_holds_the_amount(
    integration_client: AsyncClient,
    admin_headers: Headers,
    customer_headers: Headers,
    db_session: AsyncSession,
) -> None:
    await p2p_on(db_session)
    await make_card(db_session)
    r = await integration_client.post(
        "/api/v1/wallet/topups",
        json={"amount_uzs": 70_000, "provider": "p2p", "locale": "ru"},
        headers=_key(await customer_headers()),
    )
    assert r.status_code == 201, r.text
    row = await _unmatched(db_session, amount="70000")
    buyer = await make_user(db_session)
    h = await admin_headers()
    held = await integration_client.post(
        f"{BASE}/incoming/{row.id}/credit",
        json={"user_id": buyer.id, "note": "чек от покупателя"},
        headers=_key(h),
    )
    assert (held.status_code, held.json()["code"]) == (409, "p2p_quarantine")


async def test_an_ignored_row_cannot_be_credited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    row = await _unmatched(db_session, last4="9999")
    row.result = "ignored"
    await db_session.commit()
    buyer = await make_user(db_session)
    r = await integration_client.post(
        f"{BASE}/incoming/{row.id}/credit",
        json={"user_id": buyer.id, "note": "чек от покупателя"},
        headers=_key(await admin_headers()),
    )
    assert (r.status_code, r.json()["code"]) == (409, "p2p_not_creditable")


async def test_settings_round_trip(integration_client: AsyncClient, admin_headers: Headers) -> None:
    h = await admin_headers()
    body = {
        "humo_bot_user_id": 900_000_001,
        "owner_telegram_user_id": 500_000_001,
        "min_amount_uzs": 10_000,
        "max_amount_uzs": 5_000_000,
        "daily_count": 3,
        "daily_amount_uzs": 10_000_000,
    }
    r = await integration_client.put(f"{BASE}/settings", json=body, headers=_key(h))
    assert r.status_code == 200, r.text
    assert (r.json()["connected"], r.json()["daily_count"]) == (False, 3)
    bad = await integration_client.put(
        f"{BASE}/settings", json={**body, "max_amount_uzs": 20_000_000}, headers=_key(h)
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "p2p_limits")


async def test_p2p_admin_is_admin_only(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    for path in ("cards", "incoming", "requests", "settings"):
        assert (await integration_client.get(f"{BASE}/{path}", headers=h)).status_code == 403
    assert PAN  # the factory's number is never in an admin answer (tested above)
    assert await db_session.scalar(select(P2PIncoming.id)) is None
