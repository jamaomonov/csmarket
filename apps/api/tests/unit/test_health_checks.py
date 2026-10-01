"""Readiness is the AND of real dependency checks, each bounded in time."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from csmarket.core import health

pytestmark = pytest.mark.asyncio


async def test_readiness_is_ok_when_every_check_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> bool:
        return True

    monkeypatch.setattr(health, "check_postgres", ok)
    monkeypatch.setattr(health, "check_redis", ok)
    r = await health.readiness()
    assert r.ok is True
    assert r.checks == {"postgres": "ok", "redis": "ok"}


async def test_one_failing_check_degrades_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> bool:
        return True

    async def bad() -> bool:
        return False

    monkeypatch.setattr(health, "check_postgres", ok)
    monkeypatch.setattr(health, "check_redis", bad)
    r = await health.readiness()
    assert r.ok is False
    assert r.checks == {"postgres": "ok", "redis": "fail"}


async def test_a_hanging_dependency_counts_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hang() -> bool:
        await asyncio.sleep(10)
        return True

    monkeypatch.setattr(health, "check_postgres", hang)
    monkeypatch.setattr(health, "check_redis", hang)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)
    r = await health.readiness()
    assert r.ok is False


async def test_an_exception_inside_a_check_counts_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom() -> bool:
        raise ConnectionError("refused")

    async def ok() -> bool:
        return True

    monkeypatch.setattr(health, "check_postgres", boom)
    monkeypatch.setattr(health, "check_redis", ok)
    assert (await health.readiness()).checks["postgres"] == "fail"


async def test_check_postgres_runs_select_1(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []

    class _Conn:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def execute(self, stmt: Any) -> None:
            executed.append(str(stmt))

    class _Engine:
        def connect(self) -> _Conn:
            return _Conn()

    monkeypatch.setattr(health, "get_engine", _Engine)
    assert await health.check_postgres() is True
    assert executed == ["SELECT 1"]
