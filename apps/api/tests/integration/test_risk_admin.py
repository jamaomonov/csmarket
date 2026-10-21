"""Admin API for kassa limits and a user's risk policy (spec 2026-10-21, «Admin»)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.risk_factory import set_kassa_limit, succeeded_payment

pytestmark = pytest.mark.asyncio
Headers = Callable[[], Awaitable[dict[str, str]]]
LIMITS = "/api/v1/admin/payments/review-limits"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-risk-{uuid.uuid4()}"}


async def _seed(db: AsyncSession) -> None:
    for p in ("payme", "click", "uzum", "p2p"):
        await set_kassa_limit(db, p, 2_000_000)


async def test_read_seeded_limits(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed(db_session)
    r = await integration_client.get(LIMITS, headers=await admin_headers())
    assert r.status_code == 200
    got = {x["provider"]: x for x in r.json()["limits"]}
    assert set(got) == {"payme", "click", "uzum", "p2p"}
    assert got["click"] == {
        "provider": "click",
        "enabled": True,
        "max_amount_uzs": "2000000",
        "window_hours": 24,
    }


async def test_save_limits_audits_the_change(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed(db_session)
    h = await admin_headers()
    version = (await integration_client.get(LIMITS, headers=h)).json()["updated_at"]
    body = {
        "limits": [
            {"provider": "click", "enabled": False, "max_amount_uzs": 500000, "window_hours": 12}
        ]
    }
    r = await integration_client.put(
        LIMITS, json=body, headers={**h, **_key(), "If-Match": version or "none"}
    )
    assert r.status_code == 200, r.text
    click = next(x for x in r.json()["limits"] if x["provider"] == "click")
    assert click == {
        "provider": "click",
        "enabled": False,
        "max_amount_uzs": "500000",
        "window_hours": 12,
    }
    audit = await db_session.scalar(
        select(AdminAuditLog)
        .where(AdminAuditLog.action == "payments.review_limits.update")
        .order_by(AdminAuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.payload["click.max_amount_uzs"] == "2000000 -> 500000"


async def test_stale_version_is_refused(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed(db_session)
    body = {
        "limits": [{"provider": "payme", "enabled": True, "max_amount_uzs": 1, "window_hours": 1}]
    }
    r = await integration_client.put(
        LIMITS,
        json=body,
        headers={**await admin_headers(), **_key(), "If-Match": "2000-01-01T00:00:00+00:00"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "settings_stale"


async def test_duplicate_provider_is_422(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    row = {"provider": "payme", "enabled": True, "max_amount_uzs": 1, "window_hours": 1}
    r = await integration_client.put(
        LIMITS,
        json={"limits": [row, row]},
        headers={**await admin_headers(), **_key(), "If-Match": "none"},
    )
    assert r.status_code == 422


async def test_user_policy_defaults_and_money_in(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=300_000, hours_ago=2)
    r = await integration_client.get(
        f"/api/v1/admin/users/{user.id}/risk", headers=await admin_headers()
    )
    body = r.json()
    assert (
        body["trusted"],
        body["kassa_blocked"],
        body["max_amount_uzs"],
        body["window_hours"],
    ) == (
        False,
        False,
        None,
        24,
    )
    assert body["money_in_24h_uzs"] == "300000"
    assert body["open_holds"] == 0


async def test_user_policy_save_audits(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    body = {
        "trusted": False,
        "kassa_blocked": True,
        "max_amount_uzs": 1_000_000,
        "window_hours": 72,
        "note": "chargeback 2026-10-21",
    }
    r = await integration_client.put(
        f"/api/v1/admin/users/{user.id}/risk",
        json=body,
        headers={**await admin_headers(), **_key()},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["kassa_blocked"], r.json()["max_amount_uzs"]) == (True, "1000000")
    audit = await db_session.scalar(
        select(AdminAuditLog).where(
            AdminAuditLog.action == "users.risk.update", AdminAuditLog.target_id == user.id
        )
    )
    assert audit is not None


async def test_customer_is_refused(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    assert (await integration_client.get(LIMITS, headers=h)).status_code == 403
    user = await make_user(db_session)
    r = await integration_client.get(f"/api/v1/admin/users/{user.id}/risk", headers=h)
    assert r.status_code == 403
