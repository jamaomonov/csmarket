"""Composition root for the FastAPI app.

Each module that exposes HTTP routes provides a router; they are mounted here
under ``/api/v1``. Acquirer webhooks (M3) mount under the same prefix on their
module's router and are exempted from the coarse limiter by name, in
:func:`_exempt_self_authenticating_routes` — one audited list.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from csmarket.api.v1.router import router as v1_router
from csmarket.core import health
from csmarket.core.cache_headers import NoStoreByDefault
from csmarket.core.client_ip import client_ip as _client_ip
from csmarket.core.config import Settings, get_settings
from csmarket.core.db import dispose_engine
from csmarket.core.errors import AppError, app_error_handler
from csmarket.core.logging import configure_logging, get_logger
from csmarket.core.observability import init_sentry
from csmarket.core.redis import close_redis
from csmarket.modules.realtime.listener import OrderEventsListener

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: Latency histogram bounds, in seconds. Dense below 250 ms because most traffic
#: is fast; reaching 10 s because the Waxpeer-touching endpoints (M2) genuinely go
#: there, and that range has to be visible during an incident.
_LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

#: Settings a production deploy is broken without, mapped to what silently stops
#: working when they are empty: ``(ENV_NAME, settings_field, impact)``. M1 added
#: the JWT keys, the Steam Web API key and the Waxpeer key; M3 adds the acquirers.
_REQUIRED_IN_PROD: tuple[tuple[str, str, str], ...] = (
    (
        "CSMARKET_JWT_PRIVATE_KEY",
        "jwt_private_key",
        "no session can be minted: every sign-in fails",
    ),
    ("CSMARKET_JWT_PUBLIC_KEY", "jwt_public_key", "no access token verifies: every request is 401"),
    (
        "CSMARKET_STEAM_API_KEY",
        "steam_api_key",
        "accounts sign in nameless; trade-hold check skipped",
    ),
    ("CSMARKET_WAXPEER_API_KEY", "waxpeer_api_key", "trade-link check always 'unavailable'"),
    ("CSMARKET_RESEND_API_KEY", "resend_api_key", "no letter is sent: every email fails"),
)


def missing_prod_settings(settings: Settings) -> list[str]:
    """Env var names a prod deploy is missing; empty outside prod.

    Args:
        settings: The resolved application settings.

    Returns:
        Names that are empty but required in production, in declaration order.
    """
    if not settings.is_prod:
        return []
    return [
        name
        for name, field, _ in _REQUIRED_IN_PROD
        if not str(getattr(settings, field, "")).strip()
    ]


def warn_if_kassa_sandbox_in_prod(settings: Settings) -> bool:
    """Log a startup warning when prod accepts the kassas' sandbox credentials.

    ``CSMARKET_KASSA_SANDBOX_ENABLED`` is for the R14 sandbox pass only: while it is on, the
    Payme test key and the Uzum sandbox pair credit real balances. The line names the flag,
    never a credential.

    Args:
        settings: The resolved application settings.

    Returns:
        Whether the warning was logged.
    """
    if not (settings.is_prod and settings.kassa_sandbox_enabled):
        return False
    get_logger("csmarket.bootstrap").warning(
        "kassa.sandbox_enabled_in_prod",
        hint="sandbox credentials credit real balances; unset CSMARKET_KASSA_SANDBOX_ENABLED "
        "after the sandbox pass (docs/runbooks/kassa-setup.md)",
    )
    return True


def _build_limiter(settings: Settings) -> Limiter:
    """Coarse per-IP, per-route limiter (the ADR-0028 shape from the source project).

    Memory storage on purpose: ``limits``' Redis backend is synchronous and would
    block the event loop. With one uvicorn process the approximation is exact;
    credential endpoints add their own Redis-backed ``ip_guard`` in M1.
    """
    enabled = (
        settings.rate_limit_enabled
        if settings.rate_limit_enabled is not None
        else not settings.is_test
    )
    return Limiter(
        key_func=_client_ip,
        default_limits=[settings.rate_limit_default],
        storage_uri="memory://",
        enabled=enabled,
        headers_enabled=True,
        # Bucket by route, not URL: ``/orders/aaa`` and ``/orders/bbb`` share one budget.
        key_style="endpoint",
    )


def _exempt_self_authenticating_routes(limiter: Limiter) -> None:
    """Take machine-to-machine surfaces out of the coarse limiter.

    The acquirer callbacks authenticate their own caller, and a 429 to an acquirer costs
    money and buys nothing: it reads as a transport failure, retries, and the top-up sits
    unpaid. One audited list, not decorators spread over modules; ``exempt()`` keys off the
    handler's ``module.name``, which is what the middleware resolves per request.
    """
    from csmarket.modules.click.routes import click_complete, click_prepare
    from csmarket.modules.payme.routes import payme_merchant
    from csmarket.modules.public_api.routes import (
        catalog,
        delete_webhook,
        get_order,
        get_webhook,
        item_offers,
        list_orders,
        me,
        place_order,
        put_webhook,
    )
    from csmarket.modules.skinslink.routes import skinslink_webhook
    from csmarket.modules.uzum.routes import (
        uzum_check,
        uzum_confirm,
        uzum_create,
        uzum_reverse,
        uzum_status,
    )

    for endpoint in (
        # Click Shop API: MD5 ``sign_string`` over the raw form fields, per service secret.
        click_prepare,
        click_complete,
        # Payme Merchant API: HTTP Basic ``Paycom:<key>`` (production or sandbox key).
        payme_merchant,
        # Uzum Merchant API: HTTP Basic login/password (production or sandbox pair).
        uzum_check,
        uzum_create,
        uzum_confirm,
        uzum_reverse,
        uzum_status,
        # Skinslink: ``sign = sha256(id + secret)``; the body is not trusted, a check is queued.
        skinslink_webhook,
        # Public API: bearer key, limited per key (``public_api.limits``) and per IP on failures.
        catalog,
        item_offers,
        place_order,
        get_order,
        list_orders,
        me,
        get_webhook,
        put_webhook,
        delete_webhook,
    ):
        # slowapi ships no types for this decorator; the side effect on the exempt set is
        # the point, the returned wrapper is discarded.
        limiter.exempt(endpoint)  # type: ignore[no-untyped-call]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Wire startup and shutdown side effects."""
    configure_logging()
    logger = get_logger("csmarket.bootstrap")
    settings = get_settings()
    logger.info("startup", environment=settings.environment)
    missing = missing_prod_settings(settings)
    if missing:
        reasons = {name: why for name, _, why in _REQUIRED_IN_PROD if name in missing}
        logger.warning(
            "prod_config_incomplete",
            missing=missing,
            impact=reasons,
            hint="apply secrets with `docker compose up -d`, not `restart` — restart keeps the old env_file values",
        )
    warn_if_kassa_sandbox_in_prod(settings)
    listener = OrderEventsListener(settings.database_url) if settings.realtime_enabled else None
    if listener is not None:
        await listener.start()
    try:
        yield
    finally:
        if listener is not None:
            await listener.stop()
        await close_redis()
        await dispose_engine()
        logger.info("shutdown")


def create_app() -> FastAPI:
    """Build a fresh FastAPI app with routers, middleware and exception handlers."""
    settings = get_settings()
    init_sentry(settings)
    app = FastAPI(
        title="csmarket API",
        version="0.0.1",
        # Off in production along with Swagger: the schema maps every path, admin
        # included, and a public map of the admin surface is reconnaissance.
        # ``app.openapi()`` still works for ``make gen-api``.
        openapi_url="/openapi.json" if not settings.is_prod else None,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    limiter = _build_limiter(settings)
    _exempt_self_authenticating_routes(limiter)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # CORS is registered AFTER the limiter so it is the OUTER layer: the limiter
    # short-circuits with a 429, and without CORS headers on it the browser reads
    # a network error and retries — multiplying the traffic that tripped it.
    # ``*`` with credentials is rejected by browsers; reflect the Origin instead,
    # and never in prod (that is the misconfiguration that lets any site ride a
    # victim's session).
    if "*" in settings.cors_allow_origins and not settings.is_prod:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=".*",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        if "*" in settings.cors_allow_origins:
            get_logger("csmarket.bootstrap").warning(
                "cors_wildcard_ignored_in_prod",
                hint="CSMARKET_CORS_ALLOW_ORIGINS=* is dev-only; set an explicit origin list for prod.",
            )
        origins = [origin for origin in settings.cors_allow_origins if origin != "*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Outermost of all: nothing the API answers is cacheable unless a route says so.
    app.add_middleware(NoStoreByDefault)
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's 422 shape without ``input`` and ``ctx``: bodies carry PII (card numbers,
        trade links) and pydantic would echo them back."""
        detail = [{"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/healthz", tags=["meta"], summary="Liveness probe")
    @limiter.exempt  # type: ignore[untyped-decorator]
    async def healthz() -> dict[str, str]:
        """Return ``{"status": "ok"}`` if the process is alive."""
        return {"status": "ok"}

    @app.get(
        "/readyz",
        tags=["meta"],
        summary="Readiness probe",
        responses={503: {"description": "A dependency is down"}},
    )
    @limiter.exempt  # type: ignore[untyped-decorator]
    async def readyz() -> JSONResponse:
        """200 when Postgres and Redis answer; 503 with the failing check named otherwise."""
        result = await health.readiness()
        return JSONResponse(
            status_code=200 if result.ok else 503,
            content={"status": "ready" if result.ok else "degraded", "checks": result.checks},
        )

    app.include_router(v1_router, prefix="/api/v1")

    # Explicit buckets: the library default tops out at 1 s, which made p95
    # unmeasurable above it and the latency alert dead code.
    Instrumentator().add(metrics.default(latency_lowr_buckets=_LATENCY_BUCKETS)).instrument(
        app
    ).expose(app, endpoint="/metrics", include_in_schema=False)
    return app
