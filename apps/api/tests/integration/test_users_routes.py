"""GET / PATCH /api/v1/me."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _auth(c: AsyncClient, **extra: object) -> dict[str, str]:
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": "76561198000000001", **extra})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_me_requires_a_token(integration_client: AsyncClient) -> None:
    assert (await integration_client.get("/api/v1/me")).status_code == 401


async def test_me_shape(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client, display_name="Player", admin=True)
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["steam_id"] == "76561198000000001"
    assert me["display_name"] == "Player"
    assert me["locale"] == "ru"
    assert me["roles"] == ["admin"]
    assert me["email"] is None
    assert me["email_verified"] is False
    assert set(me) == {
        "id",
        "steam_id",
        "display_name",
        "avatar_url",
        "email",
        "email_verified",
        "email_verification_sent_at",
        "locale",
        "trade_link",
        "trade_link_verdict",
        "trade_link_reason",
        "trade_link_checked_at",
        "roles",
        "created_at",
    }


async def test_patch_locale_and_email(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.patch(
        "/api/v1/me", json={"locale": "uz", "email": "A@Example.uz"}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["locale"] == "uz"
    assert r.json()["email"] == "A@example.uz"  # EmailStr lower-cases the domain
    assert r.json()["email_verified"] is False
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert (me["locale"], me["email"]) == ("uz", "A@example.uz")


async def test_patch_omitted_fields_stay(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    await integration_client.patch("/api/v1/me", json={"email": "a@b.uz"}, headers=h)
    r = await integration_client.patch("/api/v1/me", json={"locale": "en"}, headers=h)
    assert (r.json()["locale"], r.json()["email"]) == ("en", "a@b.uz")


async def test_patch_rejects_bad_values(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    bad = [{"locale": "de"}, {"email": "nope"}, {"steam_id": "1"}]
    for body in bad:
        r = await integration_client.patch("/api/v1/me", json=body, headers=h)
        assert r.status_code == 422, body


async def test_patch_email_null_clears_it(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    await integration_client.patch("/api/v1/me", json={"email": "a@b.uz"}, headers=h)
    r = await integration_client.patch("/api/v1/me", json={"email": None}, headers=h)
    assert r.json()["email"] is None


async def test_patch_replays_by_idempotency_key(integration_client: AsyncClient) -> None:
    h = {**(await _auth(integration_client)), "Idempotency-Key": "p" * 20}
    first = await integration_client.patch("/api/v1/me", json={"locale": "uz"}, headers=h)
    second = await integration_client.patch("/api/v1/me", json={"locale": "en"}, headers=h)
    assert second.json() == first.json()
    assert second.json()["locale"] == "uz"


async def test_patch_rejects_a_short_idempotency_key(integration_client: AsyncClient) -> None:
    h = {**(await _auth(integration_client)), "Idempotency-Key": "short"}
    r = await integration_client.patch("/api/v1/me", json={"locale": "uz"}, headers=h)
    assert r.status_code == 422


async def test_banned_account_gets_403_not_401(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from csmarket.core.clock import now
    from csmarket.modules.users.service import get_user_by_steam_id

    h = await _auth(integration_client)
    user = await get_user_by_steam_id(db_session, "76561198000000001")
    assert user is not None
    user.banned_at = now()
    await db_session.commit()
    r = await integration_client.get("/api/v1/me", headers=h)
    assert r.status_code == 403
    assert r.json()["type"].endswith("/account-suspended")
