"""PUT /me/trade-link and POST /me/trade-link/check (Review Focus 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

OWNER = "76561198000000001"
#: Redrawn fake links — never a real partner/token in tests.
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"
OTHER = "https://steamcommunity.com/tradeoffer/new/?partner=39734274&token=AbCdEf12"


async def _auth(c: AsyncClient, steam_id: str = OWNER) -> dict[str, str]:
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": steam_id})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_save_own_link(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"trade_link": LINK, "verdict": None, "reason": None, "checked_at": None}
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["trade_link"] == LINK


async def test_someone_elses_link_is_refused(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": OTHER}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_not_yours"
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["trade_link"] is None


async def test_garbage_is_refused(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": "hello"}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_invalid"


async def test_saving_a_new_link_clears_the_old_verdict(
    integration_client: AsyncClient, app_overrides: Callable[..., None]
) -> None:
    h = await _auth(integration_client)
    await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    app_overrides(hold_days=7)
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert r.json()["verdict"] == "warn"
    assert r.json()["reason"] == "hold"
    assert r.json()["checked_at"] is not None
    link2 = LINK.replace("AbCdEf12", "ZyXwVu98")
    r2 = await integration_client.put("/api/v1/me/trade-link", json={"url": link2}, headers=h)
    assert r2.json()["verdict"] is None
    assert r2.json()["checked_at"] is None


async def test_check_verdict_survives_a_reload(
    integration_client: AsyncClient, app_overrides: Callable[..., None]
) -> None:
    h = await _auth(integration_client)
    await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    app_overrides(waxpeer_info="Inventory is private")
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert (r.json()["verdict"], r.json()["reason"]) == ("bad", "private")
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert (me["trade_link_verdict"], me["trade_link_reason"]) == ("bad", "private")
    assert me["trade_link_checked_at"] is not None


async def test_check_without_keys_is_unavailable_but_link_stays(
    integration_client: AsyncClient,
) -> None:
    h = await _auth(integration_client)
    await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert r.status_code == 200
    assert r.json() == {
        "trade_link": LINK,
        "verdict": None,
        "reason": "unavailable",
        "checked_at": None,
    }


async def test_check_without_a_saved_link_is_422(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_missing"


async def test_put_replays_by_idempotency_key(integration_client: AsyncClient) -> None:
    h = {**(await _auth(integration_client)), "Idempotency-Key": "k" * 20}
    first = await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    second = await integration_client.put(
        "/api/v1/me/trade-link", json={"url": LINK.replace("AbCdEf12", "ZyXwVu98")}, headers=h
    )
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert second.json()["trade_link"] == LINK


async def test_requires_sign_in(integration_client: AsyncClient) -> None:
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": LINK})
    assert r.status_code == 401
    assert (await integration_client.post("/api/v1/me/trade-link/check")).status_code == 401


async def test_no_transaction_is_held_across_the_upstream_calls(
    integration_client: AsyncClient, integration_app: FastAPI
) -> None:
    """AGENTS §11: a pooled connection must not idle in a transaction while Waxpeer and
    Steam take up to 4 s each — 20 slow checks would starve the whole API."""
    from csmarket.api.v1.deps import db_session
    from csmarket.modules.users.routes import tradelink_checkers

    sessions: list[AsyncSession] = []
    seen: list[bool] = []

    async def _recording_session() -> AsyncIterator[AsyncSession]:
        async for s in db_session():
            sessions.append(s)
            yield s

    class _Wax:
        async def check_tradelink(self, url: str) -> str | None:
            seen.append(sessions[-1].in_transaction())
            return None

    class _Hold:
        async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
            seen.append(sessions[-1].in_transaction())
            return 0

    h = await _auth(integration_client)
    await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    integration_app.dependency_overrides[db_session] = _recording_session
    integration_app.dependency_overrides[tradelink_checkers] = lambda: (_Wax(), _Hold())
    try:
        r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    finally:
        integration_app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == "ok"
    assert seen == [False, False]
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["trade_link_verdict"] == "ok"  # the verdict written after still lands
