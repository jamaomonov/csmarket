"""What the revocation blocklist does when Redis cannot answer.

The read runs on **every authenticated request**, so its failure mode is pinned here:
fail open. Refusing would sign every customer out for the length of a Redis blip; a 500
would do that *and* page. The cost is bounded: the blocklist only accelerates an expiry
that happens anyway inside the 15-minute access TTL, and a ban is checked in Postgres.

The writes (rotation, reuse burn-down, logout) fail open too: the ``refresh_tokens``
row is the source of truth and is written either way, so a Redis blip must not turn a
refresh or a sign-out into a 500.
"""

from __future__ import annotations

from typing import Any

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.auth import service as svc
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError


class _Redis:
    """Stand-in for the client, answering however the test needs."""

    def __init__(self, *, answer: str | None = None, raises: Exception | None = None) -> None:
        self._answer = answer
        self._raises = raises

    async def get(self, _key: str) -> str | None:
        if self._raises is not None:
            raise self._raises
        return self._answer

    async def set(self, _key: str, _value: str, *, ex: int) -> None:
        if self._raises is not None:
            raise self._raises


class _Log:
    """Records structlog-style calls: (method, event, kwargs)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def exception(self, event: str, **kw: Any) -> None:
        self.calls.append(("exception", event, kw))

    def error(self, event: str, **kw: Any) -> None:  # pragma: no cover - not expected
        self.calls.append(("error", event, kw))


@pytest.mark.parametrize(
    "boom",
    [RedisTimeoutError("Timeout reading from redis:6379"), RedisError("connection reset")],
)
async def test_an_unreadable_blocklist_does_not_refuse_the_request(
    monkeypatch: pytest.MonkeyPatch, boom: Exception
) -> None:
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(raises=boom))
    monkeypatch.setattr(svc, "log", _Log())

    assert await svc._is_blocklisted("auth:revoked:whatever", kind="access") is False


async def test_a_readable_blocklist_still_revokes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-open must not become always-open — the control still works."""
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(answer="1"))

    assert await svc._is_blocklisted("auth:revoked:whatever", kind="access") is True


async def test_an_absent_key_is_not_a_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(answer=None))

    assert await svc._is_blocklisted("auth:revoked:whatever", kind="access") is False


async def test_the_failure_is_logged_without_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``jti``/``sid`` identifies a live session; only the blocklist's name goes out."""
    secret_key = "auth:revoked_sid:01a0-secret-sid"
    log = _Log()
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(raises=RedisError("down")))
    monkeypatch.setattr(svc, "log", log)

    await svc._is_blocklisted(secret_key, kind="session")

    assert [(m, e) for m, e, _ in log.calls] == [("exception", "auth.blocklist_unreadable")]
    _, _, kwargs = log.calls[0]
    assert kwargs == {"blocklist": "session"}
    assert "01a0-secret-sid" not in repr(log.calls)


async def test_an_unwritable_session_blocklist_does_not_fail_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _Log()
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(raises=RedisError("down")))
    monkeypatch.setattr(svc, "log", log)
    settings = get_settings()

    await svc._blocklist_session_id("01a0-secret-sid", settings=settings)

    assert log.calls == [("exception", "auth.blocklist_unwritable", {"blocklist": "session"})]
    assert "01a0-secret-sid" not in repr(log.calls)


async def test_an_unwritable_access_blocklist_does_not_fail_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from csmarket.modules.auth.jwt import mint_access, verify

    log = _Log()
    settings = get_settings()
    token = mint_access(sub="u", sid="s", settings=settings)
    jti = verify(token, settings=settings).jti
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(raises=RedisTimeoutError("slow")))
    monkeypatch.setattr(svc, "log", log)

    await svc._blocklist_access_token(token, settings=settings)

    assert log.calls == [("exception", "auth.blocklist_unwritable", {"blocklist": "access"})]
    assert jti not in repr(log.calls)
