"""Domain Prometheus counters, and the two rules every one of them obeys.

``prometheus_fastapi_instrumentator`` (registered in ``bootstrap.create_app``)
answers "how often was this route called and how fast" and nothing else. A route
can answer 200 in 30 ms while quietly spending a shared third-party quota — the
Steam Web API key has a 100k/day ceiling and both sign-in (M1) and the trade-link
check (M1) charge it — so domain counters live here, in one file, where the whole
label vocabulary is reviewable at once. ``docs/architecture/metrics.md`` is the
prose counterpart (written in M1 with the first increment).

**Rule 1: a label value is bounded, and is never about a person.** One time
series per label combination, in memory, forever, with no redactor and no TTL —
a Steam ID or an IP as a label is unbounded growth and PII parked where it can
never be taken back. Label types are ``Literal`` so mypy stops a caller passing
an identifier where a verdict goes.

**Rule 2: recording never fails a request.** Every increment is wrapped: a broken
registry degrades to one warning log and a missing data point, never a 500.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from prometheus_client import Counter, Gauge, start_http_server

from csmarket.core.logging import get_logger

log = get_logger("csmarket.metrics")

#: Keyed Steam Web API methods. The OpenID ``check_authentication`` round trip
#: is NOT here — it carries no key and costs no quota.
SteamApiEndpoint = Literal["get_player_summaries", "get_trade_hold_durations"]

#: Which feature spent the quota. Sum across it for "are we near the ceiling".
SteamApiConsumer = Literal["auth_signin", "trade_link"]

#: About the *call*, not the body: a 200 we could not parse still spent quota.
SteamApiOutcome = Literal["ok", "error"]

STEAM_WEB_API_CALLS = Counter(
    "csmarket_steam_web_api_calls_total",
    "Calls charged against the Steam Web API key (100k/day ceiling).",
    ("endpoint", "consumer", "outcome"),
)

#: The acquirer whose webhook was refused.
KassaProvider = Literal["click", "payme", "uzum"]

#: Why: ``auth`` = Basic credentials wrong (Payme -32504, Uzum 10001); ``signature`` = the
#: Click MD5 ``sign_string`` or service id wrong (-1); ``malformed`` = not a body the
#: protocol allows (Click -8, Payme -32700 / -32600, Uzum 10002 / 10005).
KassaRejectionReason = Literal["auth", "signature", "malformed"]

_KASSA_PROVIDERS = frozenset(("click", "payme", "uzum"))
_KASSA_REASONS = frozenset(("auth", "signature", "malformed"))

KASSA_REJECTIONS = Counter(
    "csmarket_kassa_rejections_total",
    "Acquirer webhooks refused before any business logic ran (alert: KassaRejectionsSpike).",
    ("provider", "reason"),
)

#: The Waxpeer purchase-side call: ``buy-one-p2p``, ``check-many-project-id``, ``user``.
WaxpeerEndpoint = Literal["buy", "lookup", "balance"]

#: How the call ended: ``refused`` = a 200 with ``success: false``; ``forbidden`` = HTTP
#: 403 (the key's IP whitelist); ``unavailable`` = network failure or an unreadable 200;
#: ``error`` = any other HTTP error status.
WaxpeerOutcome = Literal["ok", "refused", "forbidden", "rate_limited", "unavailable", "error"]

_WAXPEER_ENDPOINTS = frozenset(("buy", "lookup", "balance"))
_WAXPEER_OUTCOMES = frozenset(
    ("ok", "refused", "forbidden", "rate_limited", "unavailable", "error")
)

WAXPEER_CALLS = Counter(
    "csmarket_waxpeer_calls_total",
    "Waxpeer purchase-side calls by endpoint and outcome (alert: WaxpeerForbidden).",
    ("endpoint", "outcome"),
)

#: A Skinslink merchant API call (spec 2026-10-06).
SkinslinkEndpoint = Literal["available", "events", "purchase", "status", "balance"]
#: ``refused`` = a 4xx or ``success: false``; ``not_found`` = 404 (a status lookup of an
#: unknown purchase); ``unavailable`` = transport, 408/5xx or an unreadable body.
SkinslinkOutcome = Literal["ok", "refused", "forbidden", "rate_limited", "unavailable", "not_found"]

_SKINSLINK_ENDPOINTS = frozenset(("available", "events", "purchase", "status", "balance"))
_SKINSLINK_OUTCOMES = frozenset(
    ("ok", "refused", "forbidden", "rate_limited", "unavailable", "not_found")
)

SKINSLINK_CALLS = Counter(
    "csmarket_skinslink_calls_total",
    "Skinslink API calls by endpoint and outcome (alert: SkinslinkBuyFailures).",
    ("endpoint", "outcome"),
)


#: Why an order's money went back to the balance (``orders.failure_reason``).
OrderRefundReason = Literal[
    "sold_out", "source_low_balance", "invalid_trade_link", "not_accepted", "admin"
]

_ORDER_REFUND_REASONS = frozenset(
    ("sold_out", "source_low_balance", "invalid_trade_link", "not_accepted", "admin")
)

ORDER_REFUNDS = Counter(
    "csmarket_order_refunds_total",
    "Orders refunded to the balance, by reason (each order at most once).",
    ("reason",),
)


#: Why a trade waits for an admin (``skin_trades.attention_reason``, ruling R3).
TradeAttentionReason = Literal[
    "buy_unconfirmed", "ambiguous_trade", "rolled_back", "source_forbidden", "audit_divergence"
]

_TRADE_ATTENTION_REASONS = frozenset(
    ("buy_unconfirmed", "ambiguous_trade", "rolled_back", "source_forbidden", "audit_divergence")
)

TRADE_ATTENTIONS = Counter(
    "csmarket_trade_attention_total",
    "Trades flagged for an admin, by reason (each attention once; each audit verdict once).",
    ("reason",),
)


def _inc(counter: Counter, name: str, labels: dict[str, str]) -> None:
    """Increment one labelled counter, swallowing anything the registry throws."""
    try:
        counter.labels(**labels).inc()
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning("metrics.increment_failed", metric=name, error=type(exc).__name__)


#: How one buy attempt of an order ended (``orders.buying.attempt_buy``). ``forbidden`` =
#: HTTP 403 from Waxpeer (the key's IP whitelist) — the alert ``WaxpeerForbidden``;
#: ``stale_bought`` = a buy that may have gone through landed on rows someone else moved
#: (attention ``ambiguous_trade``).
OrderBuyOutcome = Literal[
    "bought",
    "adopted",
    "sold_out",
    "low_balance",
    "forbidden",
    "rate_limited",
    "unconfirmed",
    "invalid_link",
    "ambiguous",
    "stale_bought",
    "unrecorded",
]

_ORDER_BUY_OUTCOMES = frozenset(
    (
        "bought",
        "adopted",
        "sold_out",
        "low_balance",
        "forbidden",
        "rate_limited",
        "unconfirmed",
        "invalid_link",
        "ambiguous",
        "stale_bought",
        "unrecorded",
    )
)

ORDER_BUYS = Counter(
    "csmarket_order_buys_total",
    "Order buy attempts at Waxpeer, by outcome (alert: WaxpeerForbidden).",
    ("outcome",),
)


def _precreate(counter: Counter, **label_sets: frozenset[str]) -> None:
    """Expose every enumerated label combination of ``counter`` at 0 from import.

    A labelled child that is created on its first increment appears already at 1, and
    Prometheus' ``increase()`` of a series that starts at 1 is 0: the first refund, buy
    refusal or audit divergence after each restart would never alert. Pre-creating the
    closed label sets makes that first increment a 0 -> 1 step the rules can see.
    """
    names = list(label_sets)
    for combo in itertools.product(*(sorted(label_sets[name]) for name in names)):
        counter.labels(**dict(zip(names, combo, strict=True)))


_precreate(ORDER_REFUNDS, reason=_ORDER_REFUND_REASONS)
_precreate(TRADE_ATTENTIONS, reason=_TRADE_ATTENTION_REASONS)
_precreate(ORDER_BUYS, outcome=_ORDER_BUY_OUTCOMES)
_precreate(WAXPEER_CALLS, endpoint=_WAXPEER_ENDPOINTS, outcome=_WAXPEER_OUTCOMES)
_precreate(SKINSLINK_CALLS, endpoint=_SKINSLINK_ENDPOINTS, outcome=_SKINSLINK_OUTCOMES)
_precreate(KASSA_REJECTIONS, provider=_KASSA_PROVIDERS, reason=_KASSA_REASONS)


#: Which stuck-order check a ``csmarket_orders_stuck`` sample is for.
OrderStuckState = Literal["paid", "buying", "trade_sent_unpolled"]

#: Gauges below are set by the scheduler's ``orders.health`` job only; the API and the worker
#: expose them too (same module) but never set them. The two balance gauges start as NaN so
#: that process cannot read as "balance 0" -- a comparison against NaN is never true.
ORDERS_STUCK = Gauge(
    "csmarket_orders_stuck",
    "Orders waiting longer than they should, by state (alerts: OrdersPaidStuck and friends).",
    ("state",),
)
TRADES_ATTENTION = Gauge(
    "csmarket_trades_attention",
    "Trades waiting for an admin right now (alert: TradesNeedAttention).",
)
WAXPEER_BALANCE_USD = Gauge(
    "csmarket_waxpeer_balance_usd",
    "Our Waxpeer balance in USD, as of the last successful read (alert: WaxpeerBalanceLow).",
)
WAXPEER_BALANCE_THRESHOLD_USD = Gauge(
    "csmarket_waxpeer_balance_threshold_usd",
    "The balance below which WaxpeerBalanceLow fires (setting waxpeer_balance_alert_usd).",
)
SKINSLINK_MIRROR_SYNCED_TIMESTAMP = Gauge(
    "csmarket_skinslink_mirror_synced_timestamp_seconds",
    "Unix time of the last good Skinslink mirror tick (alert: SkinslinkMirrorStale).",
)
WAXPEER_BALANCE_READ_TIMESTAMP = Gauge(
    "csmarket_waxpeer_balance_read_timestamp_seconds",
    "Unix time of the last successful Waxpeer balance read (alert: WaxpeerBalanceUnknown).",
)
ORDERS_HEALTH_LAST_SUCCESS_TIMESTAMP = Gauge(
    "csmarket_orders_health_last_success_timestamp_seconds",
    "Unix time the orders.health job last finished a tick (alert: OrdersHealthStale).",
)
WAXPEER_BALANCE_USD.set(float("nan"))
WAXPEER_BALANCE_THRESHOLD_USD.set(float("nan"))
# Start at process start, not 0: "never succeeded" then reads as stale only after the alert's
# own window, instead of at once. The API and the worker keep these values; the alerts are
# pinned to job="scheduler".
WAXPEER_BALANCE_READ_TIMESTAMP.set(time.time())
SKINSLINK_MIRROR_SYNCED_TIMESTAMP.set(time.time())
ORDERS_HEALTH_LAST_SUCCESS_TIMESTAMP.set(time.time())


WS_CONNECTIONS = Gauge(
    "csmarket_ws_connections",
    "Order-update WebSockets open in this API process (M4b, realtime).",
)
WS_NUDGES = Counter(
    "csmarket_ws_nudges_total",
    "Order nudges delivered to open sockets (one per socket reached).",
)


def ws_connected(delta: int) -> None:
    """Move the open-socket gauge by ``delta`` (+1 on register, -1 on close). Never raises."""
    try:
        WS_CONNECTIONS.inc(delta)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed", metric="csmarket_ws_connections", error=type(exc).__name__
        )


#: Which letter (``notifications`` outbox kinds) and how one send attempt of it ended:
#: ``sent``; ``skipped`` (no verified address to send to); ``retry`` (rescheduled);
#: ``failed`` (rejected, or out of attempts — the alert ``EmailsFailing``).
EmailKind = Literal["receipt", "trade_sent", "refunded", "verify"]
EmailOutcome = Literal["sent", "skipped", "retry", "failed"]
_EMAIL_KINDS = frozenset(("receipt", "trade_sent", "refunded", "verify", "other"))
_EMAIL_OUTCOMES = frozenset(("sent", "skipped", "retry", "failed"))

EMAILS = Counter(
    "csmarket_emails_total",
    "Outbox letters by kind and send outcome (alert: EmailsFailing).",
    ("kind", "outcome"),
)
_precreate(EMAILS, kind=_EMAIL_KINDS, outcome=_EMAIL_OUTCOMES)


def record_email(kind: str, outcome: EmailOutcome) -> None:
    """Count one send attempt of an outbox letter. An unknown kind becomes ``"other"``.

    Never raises.
    """
    _inc(
        EMAILS,
        "csmarket_emails_total",
        {"kind": kind if kind in _EMAIL_KINDS else "other", "outcome": outcome},
    )


def record_ws_nudges(count: int) -> None:
    """Count ``count`` nudges sent to sockets. Never raises."""
    if count <= 0:
        return
    try:
        WS_NUDGES.inc(count)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.inc_failed", metric="csmarket_ws_nudges_total", error=type(exc).__name__
        )


def set_orders_stuck(state: OrderStuckState, count: int) -> None:
    """Set the stuck-orders gauge of one state. Never raises."""
    try:
        ORDERS_STUCK.labels(state=state).set(count)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning("metrics.set_failed", metric="csmarket_orders_stuck", error=type(exc).__name__)


def set_trades_attention(count: int) -> None:
    """Set how many trades wait for an admin. Never raises."""
    try:
        TRADES_ATTENTION.set(count)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed", metric="csmarket_trades_attention", error=type(exc).__name__
        )


def set_waxpeer_balance(balance_usd: float, threshold_usd: float) -> None:
    """Set the Waxpeer balance and the alert threshold beside it. Never raises."""
    try:
        WAXPEER_BALANCE_USD.set(balance_usd)
        WAXPEER_BALANCE_THRESHOLD_USD.set(threshold_usd)
        WAXPEER_BALANCE_READ_TIMESTAMP.set(time.time())  # only a successful read gets here
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed", metric="csmarket_waxpeer_balance", error=type(exc).__name__
        )


def set_skinslink_mirror_synced() -> None:
    """Stamp a good Skinslink mirror tick. Never raises."""
    try:
        SKINSLINK_MIRROR_SYNCED_TIMESTAMP.set(time.time())
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed",
            metric="csmarket_skinslink_mirror_synced_timestamp_seconds",
            error=type(exc).__name__,
        )


def set_waxpeer_balance_threshold(threshold_usd: float) -> None:
    """Set only the alert threshold (a tick that did not read the balance). Never raises."""
    try:
        WAXPEER_BALANCE_THRESHOLD_USD.set(threshold_usd)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed", metric="csmarket_waxpeer_balance", error=type(exc).__name__
        )


def mark_orders_health_success() -> None:
    """Stamp the end of a successful ``orders.health`` tick. Never raises."""
    try:
        ORDERS_HEALTH_LAST_SUCCESS_TIMESTAMP.set(time.time())
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed",
            metric="csmarket_orders_health_last_success_timestamp_seconds",
            error=type(exc).__name__,
        )


def serve_metrics(port: int, *, service: str) -> bool:
    """Serve this process's registry on ``port`` (``/metrics``), once, on a daemon thread.

    The worker and the scheduler have no HTTP server of their own; Prometheus scrapes them
    over the compose network (ports not published). A taken port is logged and the process
    goes on without metrics: a missing graph must never stop the money path.

    Returns:
        ``True`` when the server is up, ``False`` when it could not start.
    """
    try:
        start_http_server(port)
    except OSError as exc:
        log.warning("metrics.server_not_started", service=service, port=port, error=str(exc))
        return False
    log.info("metrics.server_started", service=service, port=port)
    return True


def record_steam_web_api_call(
    *, endpoint: SteamApiEndpoint, consumer: SteamApiConsumer, outcome: SteamApiOutcome
) -> None:
    """Count one call against the Steam Web API key. Never raises."""
    _inc(
        STEAM_WEB_API_CALLS,
        "csmarket_steam_web_api_calls_total",
        {"endpoint": endpoint, "consumer": consumer, "outcome": outcome},
    )


def record_kassa_rejection(*, provider: KassaProvider, reason: KassaRejectionReason) -> None:
    """Count one acquirer webhook refused for auth, signature or a malformed body.

    A value outside the closed sets becomes ``"other"``, so a bug (or a hostile value that
    reached here) cannot mint a new time series. Never raises.
    """
    _inc(
        KASSA_REJECTIONS,
        "csmarket_kassa_rejections_total",
        {
            "provider": provider if provider in _KASSA_PROVIDERS else "other",
            "reason": reason if reason in _KASSA_REASONS else "other",
        },
    )


def record_waxpeer_call(endpoint: WaxpeerEndpoint, outcome: WaxpeerOutcome) -> None:
    """Count one Waxpeer purchase-side call by how it ended.

    A value outside the closed sets becomes ``"other"``. Never raises.
    """
    _inc(
        WAXPEER_CALLS,
        "csmarket_waxpeer_calls_total",
        {
            "endpoint": endpoint if endpoint in _WAXPEER_ENDPOINTS else "other",
            "outcome": outcome if outcome in _WAXPEER_OUTCOMES else "other",
        },
    )


def record_skinslink_call(endpoint: SkinslinkEndpoint, outcome: SkinslinkOutcome) -> None:
    """Count one Skinslink call by how it ended.

    A value outside the closed sets becomes ``"other"``. Never raises.
    """
    _inc(
        SKINSLINK_CALLS,
        "csmarket_skinslink_calls_total",
        {
            "endpoint": endpoint if endpoint in _SKINSLINK_ENDPOINTS else "other",
            "outcome": outcome if outcome in _SKINSLINK_OUTCOMES else "other",
        },
    )


def record_order_refund(reason: OrderRefundReason) -> None:
    """Count one order refunded to the balance.

    A value outside the closed set becomes ``"other"``. Never raises.
    """
    _inc(
        ORDER_REFUNDS,
        "csmarket_order_refunds_total",
        {"reason": reason if reason in _ORDER_REFUND_REASONS else "other"},
    )


def record_order_buy(outcome: OrderBuyOutcome) -> None:
    """Count one order buy attempt by how it ended.

    A value outside the closed set becomes ``"other"``. Never raises.
    """
    _inc(
        ORDER_BUYS,
        "csmarket_order_buys_total",
        {"outcome": outcome if outcome in _ORDER_BUY_OUTCOMES else "other"},
    )


def record_trade_attention(reason: TradeAttentionReason) -> None:
    """Count one attention opened on a trade (or one new history-audit verdict).

    A value outside the closed set becomes ``"other"``. Never raises.
    """
    _inc(
        TRADE_ATTENTIONS,
        "csmarket_trade_attention_total",
        {"reason": reason if reason in _TRADE_ATTENTION_REASONS else "other"},
    )


@contextmanager
def steam_web_api_call(*, endpoint: SteamApiEndpoint, consumer: SteamApiConsumer) -> Iterator[None]:
    """Count the keyed Steam call made in the block, however it ends.

    Wrap only the request and its status check, not the body parsing. The
    block's exception (or cancellation) propagates untouched.
    """
    outcome: SteamApiOutcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        record_steam_web_api_call(endpoint=endpoint, consumer=consumer, outcome=outcome)


__all__ = [
    "EMAILS",
    "KASSA_REJECTIONS",
    "ORDERS_HEALTH_LAST_SUCCESS_TIMESTAMP",
    "ORDERS_STUCK",
    "ORDER_BUYS",
    "ORDER_REFUNDS",
    "SKINSLINK_CALLS",
    "SKINSLINK_MIRROR_SYNCED_TIMESTAMP",
    "STEAM_WEB_API_CALLS",
    "TRADES_ATTENTION",
    "TRADE_ATTENTIONS",
    "WAXPEER_BALANCE_READ_TIMESTAMP",
    "WAXPEER_BALANCE_THRESHOLD_USD",
    "WAXPEER_BALANCE_USD",
    "WAXPEER_CALLS",
    "WS_CONNECTIONS",
    "WS_NUDGES",
    "EmailKind",
    "EmailOutcome",
    "KassaProvider",
    "KassaRejectionReason",
    "OrderBuyOutcome",
    "OrderRefundReason",
    "OrderStuckState",
    "SkinslinkEndpoint",
    "SkinslinkOutcome",
    "SteamApiConsumer",
    "SteamApiEndpoint",
    "SteamApiOutcome",
    "TradeAttentionReason",
    "WaxpeerEndpoint",
    "WaxpeerOutcome",
    "mark_orders_health_success",
    "record_email",
    "record_kassa_rejection",
    "record_order_buy",
    "record_order_refund",
    "record_skinslink_call",
    "record_steam_web_api_call",
    "record_trade_attention",
    "record_waxpeer_call",
    "record_ws_nudges",
    "serve_metrics",
    "set_orders_stuck",
    "set_skinslink_mirror_synced",
    "set_trades_attention",
    "set_waxpeer_balance",
    "set_waxpeer_balance_threshold",
    "steam_web_api_call",
    "ws_connected",
]
