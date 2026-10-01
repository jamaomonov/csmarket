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

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from prometheus_client import Counter

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


#: Why an order's money went back to the balance (``orders.failure_reason``).
OrderRefundReason = Literal[
    "sold_out", "waxpeer_low_balance", "invalid_trade_link", "not_accepted", "admin"
]

_ORDER_REFUND_REASONS = frozenset(
    ("sold_out", "waxpeer_low_balance", "invalid_trade_link", "not_accepted", "admin")
)

ORDER_REFUNDS = Counter(
    "csmarket_order_refunds_total",
    "Orders refunded to the balance, by reason (each order at most once).",
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
    )
)

ORDER_BUYS = Counter(
    "csmarket_order_buys_total",
    "Order buy attempts at Waxpeer, by outcome (alert: WaxpeerForbidden).",
    ("outcome",),
)


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
    "KASSA_REJECTIONS",
    "ORDER_BUYS",
    "ORDER_REFUNDS",
    "STEAM_WEB_API_CALLS",
    "WAXPEER_CALLS",
    "KassaProvider",
    "KassaRejectionReason",
    "OrderBuyOutcome",
    "OrderRefundReason",
    "SteamApiConsumer",
    "SteamApiEndpoint",
    "SteamApiOutcome",
    "WaxpeerEndpoint",
    "WaxpeerOutcome",
    "record_kassa_rejection",
    "record_order_buy",
    "record_order_refund",
    "record_steam_web_api_call",
    "record_waxpeer_call",
    "steam_web_api_call",
]
