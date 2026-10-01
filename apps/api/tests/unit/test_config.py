"""Settings: CSMARKET_-prefixed env, sane dev defaults, prod/test flags."""

from __future__ import annotations

import pytest
from csmarket.core.config import Settings, get_settings


def test_defaults_point_at_the_local_dev_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermetic: integration fixtures export CSMARKET_DATABASE_URL / CSMARKET_REDIS_URL for
    # the whole session, so any CSMARKET_* var that feeds an asserted field is cleared.
    for name in (
        "CSMARKET_DATABASE_URL",
        "CSMARKET_REDIS_URL",
        "CSMARKET_SERVICE_NAME",
        "CSMARKET_RATE_LIMIT_DEFAULT",
        "CSMARKET_CORS_ALLOW_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    s = Settings(environment="dev")
    assert s.database_url.startswith("postgresql+asyncpg://csmarket_app:")
    assert s.database_url.endswith("/csmarket")
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.service_name == "csmarket-api"
    assert s.rate_limit_default == "600/minute"
    assert s.cors_allow_origins == ["http://localhost:3000", "http://localhost:3002"]
    assert s.is_prod is False


def test_prefixed_env_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_REDIS_URL", "redis://:pw@redis:6379/3")
    monkeypatch.setenv("CSMARKET_LOG_JSON", "true")
    s = Settings()
    assert s.redis_url == "redis://:pw@redis:6379/3"
    assert s.log_json is True


def test_unprefixed_env_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare ``DATABASE_URL`` (a YuPay habit) must NOT be honoured — see Review Focus 1."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@wrong-host/other")
    monkeypatch.setenv("REDIS_URL", "redis://wrong-host:6379/9")
    s = Settings()
    assert "wrong-host" not in s.database_url
    assert "wrong-host" not in s.redis_url


def test_environment_flags() -> None:
    assert Settings(environment="prod").is_prod is True
    assert Settings(environment="test").is_test is True
    assert Settings(environment="dev").is_test is False


def test_cors_origins_accept_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CSMARKET_CORS_ALLOW_ORIGINS", '["https://csmarket.uz","https://admin.csmarket.uz"]'
    )
    assert Settings().cors_allow_origins == ["https://csmarket.uz", "https://admin.csmarket.uz"]


def test_get_settings_is_cached_and_clearable(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    first = get_settings()
    assert get_settings() is first
    monkeypatch.setenv("CSMARKET_SERVICE_NAME", "csmarket-api-2")
    assert get_settings().service_name == "csmarket-api"  # still cached
    get_settings.cache_clear()
    assert get_settings().service_name == "csmarket-api-2"
    get_settings.cache_clear()
