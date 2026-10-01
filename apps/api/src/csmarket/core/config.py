"""Application configuration.

Read from environment variables (and from ``.env`` in development) via
``pydantic-settings``. **Every variable carries the ``CSMARKET_`` prefix** (spec
§4.2): ``CSMARKET_DATABASE_URL``, ``CSMARKET_REDIS_URL`` and so on. A bare
``DATABASE_URL`` is ignored — that is the point of the prefix, not an accident.

The settings object is cached for the process lifetime via ``functools.lru_cache``;
tests call ``get_settings.cache_clear()``.

Only what M0 needs lives here. Later milestones add their own groups (auth keys
in M1, Waxpeer in M2, acquirers in M3) — each with a comment saying what breaks
when it is empty.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level application settings. Names are case-insensitive after the prefix."""

    model_config = SettingsConfigDict(
        env_prefix="CSMARKET_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- runtime ---
    environment: Literal["dev", "staging", "prod", "test"] = Field(default="dev")
    debug: bool = Field(default=False)
    service_name: str = Field(default="csmarket-api")
    base_url: str = Field(default="http://localhost:8000", description="Public API origin.")
    web_base_url: str = Field(
        default="http://localhost:3000",
        description="Public storefront origin (links in emails, redirects).",
    )

    # --- data ---
    database_url: str = Field(
        default="postgresql+asyncpg://csmarket_app:csmarket_app@localhost:5432/csmarket",
        description="Async SQLAlchemy URL (postgresql+asyncpg://...).",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- rate limiting (coarse per-IP tier; ADR-0028 shape) ---
    rate_limit_enabled: bool | None = Field(
        default=None,
        description=(
            "Force the global per-IP limiter on/off. "
            "Unset means on everywhere except ENVIRONMENT=test."
        ),
    )
    rate_limit_default: str = Field(
        default="600/minute",
        description=(
            "Default per-IP, per-route limit (slowapi syntax). A flood-stopper, not a policy."
        ),
    )

    # --- CORS ---
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:3002"]
    )

    # --- at-rest encryption (core.crypto) ---
    app_enc_key: str = Field(
        default="",
        description=(
            "32-byte base64 key every purpose-specific key is HKDF-derived from. "
            "Dev/test derive a deterministic key when empty; prod refuses at first use."
        ),
    )

    # --- worker ---
    worker_poll_seconds: int = Field(
        default=5,
        description=(
            "Worker poll tick. LISTEN/NOTIFY does the real-time work; "
            "the tick catches lost notifications."
        ),
    )

    # --- observability ---
    sentry_dsn: str | None = Field(default=None)
    sentry_traces_sample_rate: float = Field(default=0.1)
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    @property
    def is_prod(self) -> bool:
        """Whether we are running in production."""
        return self.environment == "prod"

    @property
    def is_test(self) -> bool:
        """Whether we are running under pytest."""
        return self.environment == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings; tests call ``cache_clear()``."""
    return Settings()
