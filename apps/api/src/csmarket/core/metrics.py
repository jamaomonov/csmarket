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


def _inc(counter: Counter, name: str, labels: dict[str, str]) -> None:
    """Increment one labelled counter, swallowing anything the registry throws."""
    try:
        counter.labels(**labels).inc()
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning("metrics.increment_failed", metric=name, error=type(exc).__name__)


def record_steam_web_api_call(
    *, endpoint: SteamApiEndpoint, consumer: SteamApiConsumer, outcome: SteamApiOutcome
) -> None:
    """Count one call against the Steam Web API key. Never raises."""
    _inc(
        STEAM_WEB_API_CALLS,
        "csmarket_steam_web_api_calls_total",
        {"endpoint": endpoint, "consumer": consumer, "outcome": outcome},
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
    "STEAM_WEB_API_CALLS",
    "SteamApiConsumer",
    "SteamApiEndpoint",
    "SteamApiOutcome",
    "record_steam_web_api_call",
    "steam_web_api_call",
]
