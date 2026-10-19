"""Error reporting for every process that has a ``Settings``.

Sentry initialisation for every process that has a `Settings` — api, worker and
scheduler all call it, so a crash in the buy path reports and not only logs. It
has no dependency on `bootstrap` so a worker can import it without dragging the
route stack in.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sentry_sdk.types import Breadcrumb, BreadcrumbHint, Event, Hint

    from csmarket.core.config import Settings


def _is_shutdown_cancellation(event: Event) -> bool:
    """Is this APScheduler reporting that shutdown cancelled a running job?

    Not an error, and unavoidable. ``AsyncIOExecutor.shutdown`` cancels every
    in-flight coroutine job, and the scheduler container gets Docker's default
    ten seconds before SIGKILL. So a deploy that lands mid-tick WILL cut the
    job, and the next tick redoes it; every one of these jobs is periodic and
    re-runnable.

    What was wrong is only that it arrived as an **error**. `CancelledError`
    derives from ``BaseException``, so a job's own ``except Exception`` guard
    never sees it, APScheduler logs it, and the logging integration turns a
    routine deploy into a Sentry alert. An alert that fires on every deploy is
    an alert people learn to close.

    Narrow on purpose — the APScheduler logger AND a cancellation. A
    `CancelledError` anywhere else still reports, because one in a request
    handler or the order worker is a real finding.
    """
    if not str(event.get("logger") or "").startswith("apscheduler"):
        return False
    values = (event.get("exception") or {}).get("values") or []
    return any(v.get("type") == "CancelledError" for v in values)


#: Keys under which the SDK files a URL's query string or a full URL that may carry one.
_QUERY_KEYS = ("http.query", "query_string")
_URL_KEYS = ("url", "http.url")
#: Request parts that never reach Sentry: headers carry the storefront secret, the visitor's IP
#: (``X-Storefront-Client-Ip``, ``Cf-Connecting-Ip``, ``X-Forwarded-For``) and the bearer token.
_REQUEST_DROPPED = ("data", "query_string", "headers", "cookies", "env")
#: A URL's query in free text, e.g. ``httpx.HTTPStatusError``'s message.
_URL_QUERY = re.compile(r"(https?://[^\s'\"?]+)\?[^\s'\"]*")


def _scrub_http(data: Any) -> None:  # Any: breadcrumb/span data is an untyped SDK dict
    """Drop query strings from one breadcrumb's or span's ``data`` in place.

    Waxpeer takes its API key and the buyer's trade-link ``partner``/``token`` in the query, and
    the httpx integration records the raw query of every outgoing call. The path stays: it is
    what makes a breadcrumb useful.
    """
    if not isinstance(data, dict):
        return
    for key in _QUERY_KEYS:
        data.pop(key, None)
    for key in _URL_KEYS:
        url = data.get(key)
        if isinstance(url, str) and "?" in url:
            data[key] = url.split("?", 1)[0]


def _before_breadcrumb(crumb: Breadcrumb, _hint: BreadcrumbHint) -> Breadcrumb | None:
    """Strip query strings from a breadcrumb before the SDK keeps it."""
    _scrub_http(crumb.get("data"))
    return crumb


def _is_unreported(hint: Hint) -> bool:
    """Is this an :class:`AppError` marked ``report = False`` (an expected upstream outage)?"""
    from csmarket.core.errors import AppError

    exc_info = hint.get("exc_info")
    exc = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) > 1 else None
    return isinstance(exc, AppError) and not exc.report


def _before_send(event: Event, hint: Hint) -> Event | None:
    """Drop deploy-time APScheduler noise; strip bodies and query strings from the rest."""
    if _is_shutdown_cancellation(event) or _is_unreported(hint):
        return None
    request = event.get("request")
    if isinstance(request, dict):
        # Bodies: ``max_request_body_size="never"`` already keeps them out, but a card number
        # must not depend on one setting (``POST /sell``). Query: the Steam callback carries the
        # Steam ID (``openid.claimed_id``). Headers: see ``_REQUEST_DROPPED``.
        for part in _REQUEST_DROPPED:
            request.pop(part, None)
    exceptions = event.get("exception")
    values_ = exceptions.get("values") if isinstance(exceptions, dict) else None
    for exc in values_ if isinstance(values_, list) else []:
        if isinstance(exc, dict) and isinstance(exc.get("value"), str):
            exc["value"] = _URL_QUERY.sub(r"\1", exc["value"])
    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    for crumb in values if isinstance(values, list) else []:
        if isinstance(crumb, dict):
            _scrub_http(crumb.get("data"))
    return event


def _before_send_transaction(event: Event, hint: Hint) -> Event | None:
    """Strip query strings from a sampled transaction's spans and request."""
    spans = event.get("spans")
    for span in spans if isinstance(spans, list) else []:
        if isinstance(span, dict):
            _scrub_http(span.get("data"))
    trace = (event.get("contexts") or {}).get("trace")
    if isinstance(trace, dict):
        _scrub_http(trace.get("data"))
    return _before_send(event, hint)


def init_sentry(settings: Settings, *, integrations: str = "asgi") -> None:
    """Initialise Sentry if a DSN is configured, otherwise do nothing.

    The SDK is imported inside the function, not at module scope, so a dev
    environment without a DSN does not pay ~2 MB of import for a no-op.

    Args:
        settings: The app settings. `sentry_dsn` empty or unset is the
            supported "reporting is off" state and returns immediately.
        integrations: `"asgi"` adds the FastAPI/Starlette integrations, which
            attribute an event to the endpoint that raised it. Any other value
            registers none — right for the worker and the scheduler, which
            serve no requests and where those integrations would find nothing
            to hook. The transaction is then the service name, which is what
            `release` already carries.

    Returns:
        None. Failing to configure reporting must never stop a service from
        starting: a process that refuses to run because it cannot phone home
        is a worse outcome than one running unobserved.
    """
    if not settings.sentry_dsn:
        return

    import sentry_sdk

    extras = []
    if integrations == "asgi":
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        extras = [
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.service_name,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # TWO switches, and each covers a different half. ``send_default_pii``
        # governs request bodies, headers, cookies and user identity;
        # ``include_local_variables`` governs the **stack-frame locals**
        # attached to every exception event and defaults to ``True``. With
        # only the first set, any 500 raised while a secret is a live local —
        # a Waxpeer key or a payment-webhook signing secret, both of which
        # exist in the clear in exactly one frame — ships that secret to a
        # third-party SaaS. AGENTS.md §9.
        send_default_pii=False,
        include_local_variables=False,
        # The Starlette integration attaches JSON bodies whatever ``send_default_pii`` says,
        # and the default scrubber does not know ``number`` (a payout card, ``POST /sell``).
        max_request_body_size="never",
        before_send=_before_send,
        before_breadcrumb=_before_breadcrumb,
        before_send_transaction=_before_send_transaction,
        integrations=extras,
    )


__all__ = ["init_sentry"]
