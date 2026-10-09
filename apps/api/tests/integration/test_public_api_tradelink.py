"""``POST /api/v1/public/tradelink/check`` (v1.1 spec §6): the site's checker behind a key."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator

import httpx
import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.public_api import keys
from csmarket.modules.users.models import User
from csmarket.modules.users.tradelink import BREAKER_KEY
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID

Headers = Callable[[], Awaitable[dict[str, str]]]
URL = "/api/v1/public/tradelink/check"
#: Fake token -- never a real one.
FAKE = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE"


class _Wax:
    def __init__(self, info: str | None = None, error: Exception | None = None) -> None:
        self.info, self.error, self.calls = info, error, 0

    async def check_tradelink(self, url: str) -> str | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.info


class _Hold:
    def __init__(self, days: int | None = 0) -> None:
        self.days = days

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        return self.days


@pytest.fixture
def fakes(integration_app: FastAPI) -> Iterator[Callable[..., _Wax]]:
    from csmarket.modules.users.api import tradelink_checkers

    def _set(info: str | None = None, days: int | None = 0, error: Exception | None = None) -> _Wax:
        wax = _Wax(info, error)
        integration_app.dependency_overrides[tradelink_checkers] = lambda: (wax, _Hold(days))
        return wax

    yield _set
    integration_app.dependency_overrides.clear()


async def _token(db: AsyncSession, customer_headers: Headers, **limits: int) -> str:
    await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    user.usd_wallet_enabled = True
    key, token = await keys.issue(db, user=user)
    for column, value in limits.items():
        setattr(key, column, value)
    await db.commit()
    return token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _post(c: AsyncClient, token: str, link: str = FAKE) -> httpx.Response:
    return await c.post(URL, json={"trade_link": link}, headers=_h(token))


async def test_ok(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    fakes()
    token = await _token(db_session, customer_headers)
    r = await _post(integration_client, token)
    assert r.status_code == 200, r.text
    assert r.json() == {"verdict": "ok", "reason": None}


@pytest.mark.parametrize(
    ("info", "days", "reason"),
    [
        ("Inventory is private", 0, "private_inventory"),
        ("User has trade ban", 0, "trade_ban"),
        ("user not found", 0, "not_found"),
        ("bad link", 0, "invalid_link"),
        (None, 7, "hold"),
    ],
)
async def test_bad_reasons(
    *,
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    fakes,
    info: str | None,
    days: int,
    reason: str,
) -> None:
    fakes(info=info, days=days)
    token = await _token(db_session, customer_headers)
    r = await _post(integration_client, token)
    assert r.status_code == 200, r.text
    assert r.json() == {"verdict": "bad", "reason": reason}


async def test_unparsable_link_makes_no_call(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    wax = fakes()
    token = await _token(db_session, customer_headers)
    r = await _post(integration_client, token, "https://example.com/not-a-trade-link")
    assert r.json() == {"verdict": "bad", "reason": "invalid_link"}
    assert wax.calls == 0


async def test_upstream_failure_is_unavailable(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    fakes(error=httpx.ConnectError("down"))
    token = await _token(db_session, customer_headers)
    r = await _post(integration_client, token)
    assert r.status_code == 200
    assert r.json() == {"verdict": "unavailable", "reason": None}


async def test_open_breaker_is_unavailable_without_a_call(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    wax = fakes()
    token = await _token(db_session, customer_headers)
    await get_redis().set(BREAKER_KEY, "1", ex=60)
    r = await _post(integration_client, token)
    assert r.json() == {"verdict": "unavailable", "reason": None}
    assert wax.calls == 0


async def test_cache_hit_makes_no_call(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    wax = fakes()
    token = await _token(db_session, customer_headers)
    first = await _post(integration_client, token)
    second = await _post(integration_client, token)
    assert first.json() == second.json() == {"verdict": "ok", "reason": None}
    assert wax.calls == 1


async def test_check_bucket_429(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    fakes()
    token = await _token(db_session, customer_headers, check_per_min=1)
    assert (await _post(integration_client, token)).status_code == 200
    r = await _post(integration_client, token)
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"


async def test_exhausted_read_bucket_leaves_check_open(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    fakes()
    token = await _token(db_session, customer_headers, read_per_min=1)
    me = "/api/v1/public/me"
    assert (await integration_client.get(me, headers=_h(token))).status_code == 200
    assert (await integration_client.get(me, headers=_h(token))).status_code == 429
    assert (await _post(integration_client, token)).status_code == 200


async def test_requires_a_key(integration_client: AsyncClient) -> None:
    r = await integration_client.post(URL, json={"trade_link": FAKE})
    assert r.status_code == 401


async def test_no_idempotency_key_needed(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, fakes
) -> None:
    fakes()
    token = await _token(db_session, customer_headers)
    r = await integration_client.post(URL, json={"trade_link": FAKE}, headers=_h(token))
    assert r.status_code == 200


async def test_token_never_logged(
    *,
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    fakes,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fakes(error=httpx.ConnectError(f"boom {FAKE}"))
    token = await _token(db_session, customer_headers)
    await _post(integration_client, token)
    await _post(integration_client, token, FAKE + "&x=1")
    out = capsys.readouterr()
    assert "FAKEFAKE" not in out.out + out.err + caplog.text
