"""Structured logging via structlog.

In production we emit JSON; in development we emit human-readable key-value.
Sensitive fields are blocklisted by the redactor.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from csmarket.core.config import get_settings


def hash_short(value: str) -> str:
    """Stable, opaque hash of an identifier that must not be logged in the clear.

    Twelve hex characters is enough to follow one subject through an audit feed
    without exposing the identifier — a Steam ID, or the partner id inside a
    trade link.

    Args:
        value: the raw identifier. Not logged anywhere by this function.

    Returns:
        The first 12 hex characters of the value's SHA-256 digest.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


REDACTED_KEYS = frozenset(
    {
        # Spec §11: never log Steam ID, email, IP, trade-link token.
        "steam_id",
        "steamid",
        "steamid64",
        "email",
        "ip",
        "user_agent",
        "user_id",
        # A trade link carries a token that lets anyone send that account offers
        # — a credential, never a log value. ``partner`` is the account id inside it.
        "tradelink",
        "trade_link",
        "trade_url",
        "partner",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "api_key",
        "authorization",
        "cookie",
        "set-cookie",
        # Acquirer and Waxpeer secrets (M2–M3 settings names, blocked ahead of time).
        "click_secret_key",
        "payme_key",
        "payme_test_key",
        "uzum_password",
        "uzum_test_password",
        # Uzum's /confirm extras: they hold the payer's phone (never logged, masked in admin).
        "payment_source",
        "waxpeer_api_key",
        "steam_api_key",
        # Generic terms worth blocking wherever they appear as a literal key —
        # e.g. an acquirer's raw webhook JSON replayed into the admin audit feed.
        "card",
        "pan",
        "cvv",
        "cvc",
        "secret",
        "signature",
        "key",
    },
)


#: Traceback renderer for JSON (prod) mode. ``structlog.processors.
#: dict_tracebacks`` — what this replaces — is the same renderer with
#: structlog 25.x's ``show_locals=True`` default, which serialises every
#: frame's local variables into the log event. That is a credential leak on
#: exactly the paths that log exceptions the most: ``log.exception`` around
#: an asyncpg connect (the worker's ``listen_failed``, once per poll tick for
#: as long as Postgres is down) carries the DSN — password included — in the
#: connect frame's locals, straight into stdout and Loki. Locals are worth
#: little for our exceptions and cost too much here, so they're off.
_TRACEBACK_RENDERER = structlog.processors.ExceptionRenderer(
    structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
)


def _redact_pii(
    _logger: Any,
    _name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Replace values for any blocklisted key with ``"<redacted>"``.

    Matches the exact blocklist plus PII and credential *stems* — any key containing
    ``email``, ``phone``, ``secret``, ``password`` or ``authorization``, or an IP field
    (``ip`` / ``*_ip``) — so aliases like ``customer_email`` / ``client_ip`` /
    ``click_secret_key`` are caught without a reviewer having to add each variant. The stems
    are deliberately narrow so safe keys the app logs on purpose (``order_id``, ``amount``,
    ``language_code``) are untouched.
    """
    for key in list(event_dict):
        k = key.lower()
        if k in REDACTED_KEYS or _is_pii_stem(k):
            event_dict[key] = "<redacted>"
    return event_dict


def _is_pii_stem(key: str) -> bool:
    """Whether a lowercased key looks like a PII field by stem, not exact name."""
    return (
        "email" in key
        or "phone" in key
        or "steamid" in key
        or key == "ip"
        # Acquirer and API credentials under any alias (``click_secret_key``,
        # ``uzum_test_password``, ``authorization_header``…).
        or "secret" in key
        or "password" in key
        or "authorization" in key
        or key.endswith(("_ip", "_token"))
    )


def configure_logging() -> None:
    """Configure the standard library + structlog. Idempotent."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    # Silence third-party request loggers that log the full URL at INFO. httpx
    # in particular writes ``GET https://host/path?api=<key>`` — the Waxpeer
    # client passes its API key as a query param, so the key would land in the
    # logs (and Loki) verbatim. Our own structured ``*.request`` logs redact to
    # path-only; the stdlib redactor (``_redact_pii``) only covers structlog
    # events, not these. Cap them at WARNING so a real transport error still
    # surfaces without leaking credentials on every call.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_pii,
    ]

    if settings.log_json:
        processors.append(_TRACEBACK_RENDERER)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger.

    Typed as ``Any`` because structlog's actual return type depends on the processor
    chain and is not statically known.
    """
    return structlog.get_logger(name)
