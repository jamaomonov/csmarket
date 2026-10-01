"""Pytest fixtures shared across the api test suite."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> Iterator[None]:
    """Pin the environment before anything imports the config.

    Every setting carries the ``CSMARKET_`` prefix (spec §4.2). ``env_file`` is
    switched off for the whole suite so a developer's ``.env`` cannot change what
    the assertions see — `pytest` from the repo root would otherwise load it, and
    CI (no .env) would disagree with the laptop.
    """
    env = {"CSMARKET_ENVIRONMENT": "test", "CSMARKET_SENTRY_DSN": ""}
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    from csmarket.core import config as cfg

    previous_env_file = cfg.Settings.model_config.get("env_file")
    cfg.Settings.model_config["env_file"] = None
    cfg.get_settings.cache_clear()
    try:
        yield
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg.Settings.model_config["env_file"] = previous_env_file
        cfg.get_settings.cache_clear()


@pytest.fixture
async def app() -> Any:
    """A fresh FastAPI app per test."""
    # importlib, not ``from csmarket.bootstrap import ...``: mypy cannot resolve a
    # module that does not exist yet (it lands in Task 6) and a type-ignore would turn
    # into an unused-ignore error the day it does.
    import importlib

    return importlib.import_module("csmarket.bootstrap").create_app()


@pytest.fixture
async def client(app: object) -> AsyncIterator[AsyncClient]:
    """An ``httpx.AsyncClient`` bound to the app via ASGI transport."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
