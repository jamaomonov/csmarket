"""Error reporting for every process that has a ``Settings``.

Sentry initialisation for every process that has a `Settings` — api, worker and
scheduler all call it, so a crash in the buy path reports and not only logs. It
has no dependency on `bootstrap` so a worker can import it without dragging the
route stack in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sentry_sdk.types import Event, Hint

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


def _before_send(event: Event, _hint: Hint) -> Event | None:
    """Drop the one class of non-error APScheduler reports on every deploy."""
    if _is_shutdown_cancellation(event):
        return None
    return event


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
        before_send=_before_send,
        integrations=extras,
    )


__all__ = ["init_sentry"]
