"""Integration-test fixtures.

A session-scoped Postgres and a session-scoped Redis testcontainer are started once per
test session (so once per xdist worker). The Alembic migrations are applied against the
Postgres one. Each test starts from emptied tables and a flushed Redis — much faster than
rebuilding the containers.
"""

from __future__ import annotations

import os

# Ryuk (testcontainers' GC sidecar) is finicky on Docker Desktop; we don't need it for
# unit-shaped integration tests. Disable before importing the testcontainers package.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from alembic import command
from alembic.config import Config
from csmarket.core import config as cfg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer


@pytest.fixture(scope="session")
def _pg_container() -> Iterator[PostgresContainer]:
    container = PostgresContainer(image="postgres:16-alpine", driver=None).with_bind_ports(
        5432, None
    )
    try:
        container.start()
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _redis_container() -> Iterator[RedisContainer]:
    """A private Redis per session/worker, so the per-test ``flushdb`` is always safe."""
    container = RedisContainer(image="redis:7-alpine").with_bind_ports(6379, None)
    try:
        container.start()
        yield container
    finally:
        container.stop()


def _make_async_url(container: PostgresContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    user = container.username
    password = container.password
    db = container.dbname
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(
    _pg_container: PostgresContainer, _redis_container: RedisContainer
) -> Iterator[None]:
    """Point Settings + Alembic at the containers and run migrations once.

    The env vars live for the whole session (integration tests need them) and are
    restored at teardown, with the settings cache cleared both ways.
    """
    url = _make_async_url(_pg_container)
    redis_host = _redis_container.get_container_host_ip()
    redis_port = _redis_container.get_exposed_port(6379)
    overrides = {
        "CSMARKET_DATABASE_URL": url,
        "CSMARKET_REDIS_URL": f"redis://{redis_host}:{redis_port}/0",
    }
    previous = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    cfg.get_settings.cache_clear()
    try:
        _upgrade_to_head(url)
        yield
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg.get_settings.cache_clear()


def _upgrade_to_head(url: str) -> None:
    """Run ``alembic upgrade head`` against ``url``."""
    api_dir = Path(__file__).resolve().parents[2]
    ini = api_dir / "alembic.ini"
    alembic_cfg = Config(str(ini))
    alembic_cfg.set_main_option("script_location", str(api_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(autouse=True)
async def _reset_realtime_redis() -> AsyncIterator[None]:
    """Reset the ``get_redis()`` singleton and flush Redis around every integration test.

    Each pytest-asyncio test runs on its own event loop; a client cached from a previous
    test would be bound to a closed loop and blow up with "Future attached to a different
    loop" / "Event loop is closed". Resetting here makes every test start from, and leave,
    a clean singleton regardless of which fixtures it requests.
    """
    import contextlib

    from csmarket.core import redis as core_redis

    core_redis._client = None  # type: ignore[attr-defined]
    # Flush leftover Redis DATA (the singleton reset only drops the client object): rate-limit
    # counters and the like would otherwise accumulate across the run from the shared
    # test-client IP. The Redis is this worker's own container, so flushing is safe.
    # Close the flush client immediately: ``integration_client`` resets the
    # singleton on its own setup, which would otherwise orphan this client's
    # connection — a leak that exhausts the pool and hangs the run mid-suite.
    with contextlib.suppress(Exception):
        await core_redis.get_redis().flushdb()
        await core_redis.close_redis()
    yield
    await core_redis.close_redis()


#: Every table a test may write, **children before parents**. `db_engine` empties them
#: with plain `DELETE` (fast on empty tables); a wrong order raises and falls back to
#: `TRUNCATE … CASCADE`. A new table goes in front of whatever it references.
_EMPTY_IN_ORDER: tuple[str, ...] = (
    "admin_audit_log",
    "idempotent_responses",
    "refresh_tokens",
    "click_transactions",
    "payme_transactions",
    "uzum_transactions",
    "skin_trades",
    "payments",
    "orders",
    "fx_snapshots",
    "skin_pricing_rules",
    "skin_search_aliases",
    "skin_items",
    "wallet_topups",
    "wallet_postings",
    "wallet_transactions",
    "wallet_accounts",
    "users",
)


@pytest.fixture
async def db_engine():
    """A fresh async engine per test, with the database emptied first.

    Emptied with ``DELETE``, not ``TRUNCATE``: ``TRUNCATE`` pays a fixed per-table price
    (ACCESS EXCLUSIVE lock, catalogue work) while ``DELETE`` on an already-empty table is
    nearly free, and after a worker's first test they all are. ``TRUNCATE ... CASCADE``
    stays as a fallback: the order in ``_EMPTY_IN_ORDER`` is children-before-parents, which
    is what makes plain ``DELETE`` legal against ``ON DELETE RESTRICT``; if a table is
    listed in the wrong place the ``DELETE`` raises and the sledgehammer runs instead, so
    CI stays green and the next person sees a slow suite rather than a red one.

    Sequences are not restarted by ``DELETE``; no test may assert a generated value.
    """
    settings = cfg.get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    try:
        try:
            async with engine.begin() as conn:
                for table in _EMPTY_IN_ORDER:
                    await conn.execute(text(f"DELETE FROM {table}"))
        except SQLAlchemyError:
            # A foreign key the order above does not satisfy. Fall back to the
            # sledgehammer so the suite runs; the speed is a bonus, not a
            # correctness requirement.
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "TRUNCATE TABLE " + ", ".join(_EMPTY_IN_ORDER) + " RESTART IDENTITY CASCADE"
                    )
                )
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    """A session bound to the truncated engine."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def integration_app() -> FastAPI:
    """The FastAPI app ``integration_client`` talks to (for ``dependency_overrides``)."""
    from csmarket.bootstrap import create_app

    return create_app()


@pytest.fixture
async def integration_client(db_engine, integration_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An ASGI HTTP client wired to a fresh FastAPI app + truncated DB."""
    from csmarket.core import db as core_db
    from csmarket.core import redis as core_redis

    # Swap the global engine so the app's session dependency uses the test engine.
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    core_db._engine = db_engine  # type: ignore[attr-defined]
    core_db._session_factory = factory  # type: ignore[attr-defined]

    # Reset the Redis singleton so it is re-created on the current event loop.
    # Each pytest-asyncio function test runs in its own loop; a cached client from
    # a previous test would be bound to a closed loop, causing "Future attached to
    # a different loop" errors for the second Redis-using test in a session.
    core_redis._client = None  # type: ignore[attr-defined]

    transport = ASGITransport(app=integration_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    core_db._engine = None  # type: ignore[attr-defined]
    core_db._session_factory = None  # type: ignore[attr-defined]
    # Close the Redis client so its connection pool doesn't linger on this loop.
    await core_redis.close_redis()


class _FakeWaxpeer:
    """Stands in for ``WaxpeerClient.check_tradelink``."""

    def __init__(self, info: str | None) -> None:
        self.info = info

    async def check_tradelink(self, url: str) -> str | None:
        return self.info


class _FakeHold:
    """Stands in for Steam's ``GetTradeHoldDurations``."""

    def __init__(self, days: int | None) -> None:
        self.days = days

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        return self.days


@pytest.fixture
def app_overrides(integration_app: FastAPI) -> Iterator[Callable[..., None]]:
    """Swap the trade-link checkers for fakes: ``app_overrides(hold_days=7)``."""
    from csmarket.modules.users.routes import tradelink_checkers

    def _set(hold_days: int | None = 0, waxpeer_info: str | None = None) -> None:
        integration_app.dependency_overrides[tradelink_checkers] = lambda: (
            _FakeWaxpeer(waxpeer_info),
            _FakeHold(hold_days),
        )

    yield _set
    integration_app.dependency_overrides.clear()


#: The fields Steam really signs on a sign-in (``openid.signed``).
STEAM_SIGNED = "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle"


def _steam_assertion(return_to: str, sid: str = "76561198000000001") -> dict[str, str]:
    """A Steam-shaped ``id_res`` assertion for ``return_to`` (fake id, fake signature)."""
    identity = f"https://steamcommunity.com/openid/id/{sid}"
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.op_endpoint": "https://steamcommunity.com/openid/login",
        "openid.claimed_id": identity,
        "openid.identity": identity,
        "openid.return_to": return_to,
        "openid.response_nonce": "2026-10-01T00:00:00Zfake",
        "openid.assoc_handle": "1234567890",
        "openid.signed": STEAM_SIGNED,
        "openid.sig": "ZmFrZS1zaWduYXR1cmU=",
    }


@pytest.fixture
def steam_assertion() -> Callable[..., dict[str, str]]:
    """Build a Steam-shaped assertion: ``steam_assertion(return_to, sid=...)``."""
    return _steam_assertion


@pytest.fixture
def begin_steam(integration_client: AsyncClient) -> Callable[..., Awaitable[str]]:
    """Run ``GET /auth/steam/start`` like the browser does; return the minted ``return_to``.

    The client keeps the ``csmarket_oid`` cookie the start sets, so a following
    ``POST /auth/steam`` carrying an assertion for this ``return_to`` is bound to it.
    """

    async def _begin(app: str = "web", locale: str = "ru") -> str:
        r = await integration_client.get(
            "/api/v1/auth/steam/start", params={"app": app, "locale": locale}
        )
        assert r.status_code == 302, r.text
        return dict(parse_qsl(urlsplit(r.headers["location"]).query))["openid.return_to"]

    return _begin


#: The steamid64s the two header fixtures sign in as (fake, never a real account).
ADMIN_STEAM_ID = "76561198000000009"
CUSTOMER_STEAM_ID = "76561198000000008"


async def dev_login_headers(c: AsyncClient, *, steam_id: str, admin: bool) -> dict[str, str]:
    """Sign in through the dev-login route; the ``Authorization`` header for that account."""
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": steam_id, "admin": admin})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_headers(integration_client: AsyncClient) -> Callable[[], Awaitable[dict[str, str]]]:
    """``await admin_headers()`` — a Bearer header for a fresh admin sign-in."""

    async def _headers() -> dict[str, str]:
        return await dev_login_headers(integration_client, steam_id=ADMIN_STEAM_ID, admin=True)

    return _headers


@pytest.fixture
def customer_headers(integration_client: AsyncClient) -> Callable[[], Awaitable[dict[str, str]]]:
    """``await customer_headers()`` — a Bearer header for a signed-in non-admin."""

    async def _headers() -> dict[str, str]:
        return await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)

    return _headers
