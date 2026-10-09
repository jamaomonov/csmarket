"""API keys: issue, reissue, revoke, key auth and per-key limits (plan B, Task 2)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.public_api.api import ApiCaller, api_caller, enforce
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_topup
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID

Headers = Callable[[], Awaitable[dict[str, str]]]
KEY_URL = "/api/v1/me/api-key"
PROBE = "/probe"
_n = 0


def _idem() -> dict[str, str]:
    global _n
    _n += 1
    return {"Idempotency-Key": f"api-key-test-{_n:012d}"}


@pytest.fixture(autouse=True)
def _probe(integration_app: FastAPI) -> None:
    """A test-only key-auth route (the public router arrives in Task 4)."""
    router = APIRouter()

    @router.get(PROBE)
    async def probe(caller: ApiCaller = Depends(api_caller)) -> dict[str, str]:  # noqa: B008
        return {"key_id": caller.key.id}

    @router.post(PROBE + "-order")
    async def probe_order(caller: ApiCaller = Depends(api_caller)) -> dict[str, str]:  # noqa: B008
        await enforce(caller, "order")
        return {"ok": "1"}

    @router.get(PROBE + "-check")
    async def probe_check(caller: ApiCaller = Depends(api_caller)) -> dict[str, str]:  # noqa: B008
        await enforce(caller, "check")
        return {"ok": "1"}

    integration_app.include_router(router)


async def _user(db: AsyncSession) -> User:
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


async def _eligible(db: AsyncSession, *, via: str = "usd") -> None:
    user = await _user(db)
    if via == "usd":
        user.usd_wallet_enabled = True
    else:
        await credit_topup(
            db, user_id=user.id, topup_id="t-1", amount=Decimal(50000), provider="click"
        )
    await db.commit()


async def _issue(c: AsyncClient, h: dict[str, str]) -> str:
    r = await c.post(KEY_URL, headers={**h, **_idem()})
    assert r.status_code == 201, r.text
    return str(r.json()["token"])


def _bearer(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


async def test_issue_returns_a_token_and_stores_only_its_hash(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    assert token.startswith("csm_")
    assert len(token) >= 40
    key = (await db_session.execute(select(ApiKey))).scalar_one()
    assert key.token_hash == hashlib.sha256(token.encode()).hexdigest()
    row = await db_session.execute(text("SELECT row_to_json(k)::text FROM api_keys k"))
    assert token not in str(row.scalar_one())


async def test_not_allowed_without_topup_or_usd_wallet(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    r = await integration_client.post(KEY_URL, headers={**h, **_idem()})
    assert r.status_code == 409
    assert r.json()["code"] == "api_key_not_allowed"


async def test_a_booked_topup_is_enough(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session, via="topup")
    assert (await _issue(integration_client, h)).startswith("csm_")


async def test_reissue_revokes_the_old_token_and_keeps_the_tariff(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    old = await _issue(integration_client, h)
    await db_session.execute(text("UPDATE api_keys SET pricing_profile = 'cost'"))
    await db_session.commit()
    new = await _issue(integration_client, h)
    assert new != old
    assert (await integration_client.get(PROBE, headers=_bearer(old))).status_code == 401
    assert (await integration_client.get(PROBE, headers=_bearer(new))).status_code == 200
    live = (
        await db_session.execute(select(ApiKey).where(ApiKey.revoked_at.is_(None)))
    ).scalar_one()
    assert live.pricing_profile == "cost"


async def test_revoke_then_issue_keeps_the_tariff(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    await _issue(integration_client, h)
    await db_session.execute(text("UPDATE api_keys SET pricing_profile = 'cost'"))
    await db_session.commit()
    d = await integration_client.delete(KEY_URL, headers={**h, **_idem()})
    assert d.status_code == 204
    await _issue(integration_client, h)
    live = (
        await db_session.execute(select(ApiKey).where(ApiKey.revoked_at.is_(None)))
    ).scalar_one()
    assert live.pricing_profile == "cost"


async def test_revoke_then_get_is_null(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    got = await integration_client.get(KEY_URL, headers=h)
    assert got.json()["pricing_profile"] == "retail"
    assert "token" not in got.json()
    d = await integration_client.delete(KEY_URL, headers={**h, **_idem()})
    assert d.status_code == 204
    assert (await integration_client.get(PROBE, headers=_bearer(token))).status_code == 401
    assert (await integration_client.get(KEY_URL, headers=h)).json() is None
    again = await integration_client.delete(KEY_URL, headers={**h, **_idem()})
    assert again.status_code == 404
    assert again.json()["code"] == "api_key_missing"


async def test_replayed_idempotency_key_is_409_with_key_id(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    idem = _idem()
    first = await integration_client.post(KEY_URL, headers={**h, **idem})
    again = await integration_client.post(KEY_URL, headers={**h, **idem})
    assert again.status_code == 409
    assert again.json()["code"] == "key_already_issued"
    assert again.json()["key_id"] == first.json()["id"]
    assert "token" not in again.text


async def test_replayed_revoke_answers_204(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    await _issue(integration_client, h)
    idem = _idem()
    assert (await integration_client.delete(KEY_URL, headers={**h, **idem})).status_code == 204
    assert (await integration_client.delete(KEY_URL, headers={**h, **idem})).status_code == 204


async def test_idempotency_key_is_required(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    assert (await integration_client.post(KEY_URL, headers=h)).status_code == 422


async def test_key_auth_rejects_missing_unknown_and_foreign_schemes(
    integration_client: AsyncClient,
) -> None:
    c = integration_client
    assert (await c.get(PROBE)).status_code == 401
    assert (await c.get(PROBE, headers=_bearer("csm_unknown"))).status_code == 401
    assert (await c.get(PROBE, headers={"Authorization": "Bearer abc"})).status_code == 401
    r = await c.get(PROBE, headers={"Authorization": "Basic csm_x"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


async def test_banned_user_is_403(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    await db_session.execute(text("UPDATE users SET banned_at = now()"))
    await db_session.commit()
    r = await integration_client.get(PROBE, headers=_bearer(token))
    assert r.status_code == 403
    assert r.json()["code"] == "account_suspended"


async def test_ip_allowlist(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    await db_session.execute(text("UPDATE api_keys SET ip_allowlist = ARRAY['10.0.0.0/8']"))
    await db_session.commit()
    c = integration_client
    r = await c.get(PROBE, headers=_bearer(token, **{"X-Forwarded-For": "203.0.113.5"}))
    assert r.status_code == 403
    assert r.json()["code"] == "ip_not_allowed"
    junk = await c.get(PROBE, headers=_bearer(token, **{"X-Forwarded-For": "not-an-ip"}))
    assert junk.status_code == 403
    ok = await c.get(PROBE, headers=_bearer(token, **{"X-Forwarded-For": "10.1.2.3"}))
    assert ok.status_code == 200


async def test_last_used_is_stamped(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    await integration_client.get(PROBE, headers=_bearer(token))
    stamped = (await integration_client.get(KEY_URL, headers=h)).json()["last_used_at"]
    assert stamped is not None
    await integration_client.get(PROBE, headers=_bearer(token))
    assert (await integration_client.get(KEY_URL, headers=h)).json()["last_used_at"] == stamped


async def test_the_eleventh_order_hit_is_429_with_retry_after(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    c = integration_client
    for _ in range(10):
        assert (await c.post(PROBE + "-order", headers=_bearer(token))).status_code == 200
    r = await c.post(PROBE + "-order", headers=_bearer(token))
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "60"
    assert r.json()["code"] == "rate_limited"


async def test_failed_auth_counter_key_holds_a_hash_not_the_ip(
    integration_client: AsyncClient,
) -> None:
    from csmarket.core.redis import get_redis

    r = await integration_client.get(PROBE, headers=_bearer("csm_nope"))
    assert r.status_code == 401
    keys = [k async for k in get_redis().scan_iter("public_api:authfail:*")]
    assert keys, "the failed attempt was not counted"
    for k in keys:
        name = k.decode() if isinstance(k, bytes) else k
        assert "." not in name.removeprefix("public_api:authfail:")
        assert ":" not in name.removeprefix("public_api:authfail:")


async def test_key_limit_beats_default(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    await db_session.execute(update(ApiKey).values(orders_per_min=2))
    await db_session.commit()
    c = integration_client
    assert (await c.post(PROBE + "-order", headers=_bearer(token))).status_code == 200
    assert (await c.post(PROBE + "-order", headers=_bearer(token))).status_code == 200
    r = await c.post(PROBE + "-order", headers=_bearer(token))
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"


async def test_check_bucket_counts_apart_from_read(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    token = await _issue(integration_client, h)
    await db_session.execute(update(ApiKey).values(read_per_min=1))
    await db_session.commit()
    c = integration_client
    assert (await c.get(PROBE + "-check", headers=_bearer(token))).status_code == 200
    assert (await c.get(PROBE + "-check", headers=_bearer(token))).status_code == 200


async def test_reissue_carries_limits_and_allowlist(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _eligible(db_session)
    await _issue(integration_client, h)
    await db_session.execute(
        update(ApiKey).values(
            read_per_min=600,
            check_per_min=5,
            ip_allowlist=["10.0.0.0/8"],
            pricing_profile="cost",
        )
    )
    await db_session.commit()
    await _issue(integration_client, h)
    live = (
        await db_session.execute(select(ApiKey).where(ApiKey.revoked_at.is_(None)))
    ).scalar_one()
    assert live.read_per_min == 600
    assert live.check_per_min == 5
    assert live.orders_per_min is None
    assert live.ip_allowlist == ["10.0.0.0/8"]
    assert live.pricing_profile == "cost"
