"""Application configuration.

Read from environment variables (and from ``.env`` in development) via
``pydantic-settings``. **Every variable carries the ``CSMARKET_`` prefix** (spec
§4.2): ``CSMARKET_DATABASE_URL``, ``CSMARKET_REDIS_URL`` and so on. A bare
``DATABASE_URL`` is ignored — that is the point of the prefix, not an accident.

The settings object is cached for the process lifetime via ``functools.lru_cache``;
tests call ``get_settings.cache_clear()``.

Later milestones add their own groups (acquirers in M3) — each with a comment
saying what breaks when it is empty.
"""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _maybe_decode_pem(value: str) -> str:
    """Accept either a raw PEM string or its base64-encoded form.

    ``.env`` files don't handle multi-line values well; operators paste a base64
    blob and it is decoded back to PEM on load.
    """
    if not value:
        return value
    if value.startswith("-----"):
        return value
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return value
    if decoded.startswith("-----"):
        return decoded
    return value


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

    # --- auth (M1) ---
    admin_base_url: str = Field(
        default="http://localhost:3102", description="Public admin SPA origin (Steam return_to)."
    )
    jwt_private_key: str = Field(
        default="",
        description=(
            "Ed25519 private key, PEM or base64(PEM). Empty outside prod → an in-process "
            "ephemeral key (auth.jwt); empty in prod → minting refuses."
        ),
    )
    jwt_public_key: str = Field(default="")
    jwt_kid: str = Field(default="v1")
    jwt_issuer: str = Field(default="csmarket")
    jwt_access_ttl_seconds: int = Field(default=900)
    jwt_refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)
    steam_api_key: str = Field(
        default="",
        description=(
            "Steam Web API key, issued per domain. Used for persona (name, avatar) at sign-in "
            "and the trade-hold check. Empty → nameless sign-in, hold check skipped."
        ),
    )
    waxpeer_api_key: str = Field(
        default="",
        description="Waxpeer API key (IP-whitelisted). Empty → trade-link check unavailable.",
    )
    waxpeer_base_url: str = Field(default="https://api.waxpeer.com/v1")
    dev_login_enabled: bool = Field(
        default=False,
        description="POST /auth/dev-login for local work and e2e. Ignored when environment=prod.",
    )
    auth_ip_guard_max: int = Field(default=10)
    auth_ip_guard_window_seconds: int = Field(default=60)
    auth_ip_guard_subject_max: int = Field(default=10)
    auth_ip_guard_bucket_max: dict[str, int] = Field(
        default_factory=lambda: {
            "steam-login": 60,
            "trade-link-check": 60,
            "dev-login": 60,
            "skins-listings": 60,
        },
        description=(
            "Per-bucket per-IP ceilings. Uzbek mobile carriers put many subscribers behind "
            "one address, so these are crowd-sized; values <= 0 fall back to auth_ip_guard_max."
        ),
    )

    @field_validator("jwt_private_key", "jwt_public_key", mode="after")
    @classmethod
    def _decode_pem(cls, v: str) -> str:
        """Accept base64-encoded PEM blobs (single-line, .env-friendly)."""
        return _maybe_decode_pem(v)

    # --- skins (M2) ---
    skins_sync_enabled: bool = Field(
        default=False,
        description="Scheduler runs the ByMykel import and the Waxpeer price sync (prod only).",
    )
    skins_categories: str = Field(
        default="rifles,pistols,smgs,heavy,knives,gloves,agents,cases,keys,music-kits,charms",
        description="Comma-separated allow-list of categories visible in the catalogue.",
    )
    skins_image_host: str = Field(
        default="community.fastly.steamstatic.com",
        description="Host that Steam image URLs are rewritten to on the way out.",
    )
    bymykel_base_url: str = Field(
        default="https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en",
        description="Base URL of the ByMykel/CSGO-API English JSON files.",
    )
    skins_import_interval_hours: int = Field(
        default=24, ge=1, description="Hours between catalogue imports."
    )
    skins_snapshot_interval_minutes: int = Field(
        default=5, ge=1, description="Minutes between Waxpeer price snapshots."
    )
    skins_listings_budget_per_minute: int = Field(
        default=18,
        ge=0,
        description="Process-wide Waxpeer search-by-name calls per minute (limit is 20).",
    )
    skins_listings_timeout_seconds: float = Field(
        default=4.0, description="Timeout of the live-listings Waxpeer call."
    )
    waxpeer_request_timeout_seconds: float = Field(
        default=20.0, description="Timeout of bulk Waxpeer calls (price sync)."
    )

    # --- fx (M2) ---
    fx_cbu_url: str = Field(
        default="https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/",
        description="Central Bank of Uzbekistan USD rate endpoint.",
    )
    fx_timeout_seconds: float = Field(default=5.0, description="Timeout of the CBU request.")
    fx_refresh_interval_minutes: int = Field(
        default=60, ge=5, description="Minutes between CBU rate refreshes."
    )
    fx_max_age_days: int = Field(
        default=7, ge=1, description="A rate snapshot older than this counts as no rate."
    )

    # --- money (M3) ---
    # Kassa credentials are prod-only; tests and dev use the mock provider. An empty
    # credential means that kassa is unavailable: its webhook refuses and its tile is hidden.
    topup_min_uzs: int = Field(default=1000, ge=1, description="Smallest top-up, whole soʻm.")
    topup_max_uzs: int = Field(default=10_000_000, ge=1, description="Largest top-up, whole soʻm.")
    topup_expiry_minutes: int = Field(
        default=30,
        ge=1,
        description="A top-up no kassa has touched expires after this many minutes.",
    )
    click_merchant_id: int | None = Field(
        default=None, description="Click merchant id. Empty → Click unavailable."
    )
    click_service_id: int | None = Field(
        default=None, description="Click service id. Empty → Click unavailable."
    )
    click_secret_key: str = Field(
        default="", description="Click SECRET_KEY of the service (signs every webhook)."
    )
    click_pay_url: str = Field(default="https://my.click.uz/services/pay")
    payme_merchant_id: str = Field(
        default="", description="Payme cabinet merchant id. Empty → Payme unavailable."
    )
    payme_key: str = Field(default="", description="Payme cabinet «Ключ» (production Basic auth).")
    payme_test_key: str = Field(
        default="", description="Payme cabinet «Тестовый ключ» (sandbox Basic auth)."
    )
    payme_login: str = Field(default="Paycom", description="Basic-auth login Payme sends.")
    payme_checkout_url: str = Field(default="https://checkout.paycom.uz")
    uzum_service_id: int | None = Field(
        default=None, description="Uzum service id. Empty → Uzum unavailable."
    )
    uzum_login: str = Field(default="", description="Basic-auth login Uzum sends.")
    uzum_password: str = Field(default="", description="Basic-auth password Uzum sends.")
    uzum_test_login: str = Field(default="", description="Sandbox Basic-auth login.")
    uzum_test_password: str = Field(default="", description="Sandbox Basic-auth password.")
    uzum_open_service_url: str = Field(default="https://uzumbank.uz/open-service")

    @field_validator("click_merchant_id", "click_service_id", "uzum_service_id", mode="before")
    @classmethod
    def _blank_int_to_none(cls, v: object) -> object:
        """Treat an empty or whitespace-only numeric env var as "not set".

        Compose passes unset variables as ``""``; without this the documented "leave empty to
        disable" convention would raise a ``ValidationError`` at startup. ``v`` is ``object``
        (raw pre-coercion input); integers, numeric strings and ``None`` pass through.
        """
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

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

    @property
    def dev_login_active(self) -> bool:
        """Dev login is reachable only when flagged on and never in prod."""
        return self.dev_login_enabled and not self.is_prod


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings; tests call ``cache_clear()``."""
    return Settings()
