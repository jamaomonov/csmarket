"""The worker's ``api_webhooks`` drain: signed partner webhooks, pinned and retried (plan C, T3).

:func:`drain_webhooks` mirrors ``notifications.sender``: it claims due ``pending`` deliveries
(``FOR UPDATE SKIP LOCKED``) and, in the claim's own short transaction, counts the attempt and
books the next one (1 m, 5 m, 30 m, 2 h, then every 2 h; ``webhook_max_attempts`` in all). The
POST then runs with **no lock and no open transaction**; a crash leaves the row ``pending`` and
due again at the booked time. Per row:

- the user's live key and webhook URL are read now: no live key → ``failed no_key``; no
  webhook → ``failed no_webhook``. The signing key is the live key's ``token_hash`` at send
  time, so a reissued key signs with the new hash;
- the stored URL is re-checked (:func:`check_url`) and its host resolved again with
  :func:`public_addresses` — any non-public address refuses the send (``private``, retried:
  the partner may fix DNS or the URL). DNS may have changed since the URL was saved;
- the connection is **pinned** to the checked address: the request goes to
  ``https://<ip>[:port]/path`` with the partner's ``Host`` header and
  ``extensions={"sni_hostname": host}``. httpcore uses ``sni_hostname`` as the TLS
  ``server_hostname``, and the default SSL context checks the certificate against it — so TLS
  still verifies the partner's host while a DNS change after the check cannot move the
  connection. Each delivery opens its own transport, so no pooled connection opened for one
  host is reused for another behind the same address. Redirects are not followed and proxies
  from the environment are ignored;
- 2xx → ``sent``; anything else keeps the booked retry (``http_<code>``, ``timeout``,
  ``connect``) or ends ``failed`` on the last attempt.

The outcome write is guarded by ``status = 'pending'`` and the claimed attempt number, so a slow
attempt never overwrites a newer one. Log lines carry the delivery id, the event, the outcome
and the host — never the URL, the body or the signature.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import ApiWebhookOutcome, record_webhook
from csmarket.modules.public_api.keys import live_key
from csmarket.modules.public_api.models import ApiWebhook, ApiWebhookDelivery
from csmarket.modules.public_api.webhook_url import check_url, public_addresses

log = get_logger("csmarket.public_api.webhook_sender")

#: Seconds from an attempt to the next one; past the table, the last value repeats.
BACKOFF_SECONDS = (60, 300, 1800, 7200)
USER_AGENT = "csmarket-webhooks/1"

#: ``(host, port) -> addresses``; raises ``ValidationError`` unless every address is public.
Resolver = Callable[[str, int], Awaitable[list[str]]]


def sign(key_hex: str, timestamp: int, body: bytes) -> str:
    """Hex HMAC-SHA256 over ``f"{timestamp}."`` + ``body``, keyed by ``key_hex``'s bytes.

    Args:
        key_hex: The lowercase hex SHA-256 of the partner's token (``api_keys.token_hash``).
        timestamp: Unix seconds, as sent in ``X-Csm-Timestamp``.
        body: The exact body bytes sent.

    Returns:
        The signature sent in ``X-Csm-Signature``.
    """
    return hmac.new(key_hex.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def backoff_seconds(attempt: int) -> int:
    """Seconds from attempt number ``attempt`` (1-based) to the next one."""
    return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]


@dataclass(frozen=True, slots=True)
class _Claim:
    """A row claimed for this attempt, and which attempt it is."""

    id: str
    attempts: int
    event: str


@dataclass(frozen=True, slots=True)
class _Send:
    """Everything a POST needs, read before the transaction closes."""

    url: str
    key_hash: str
    body: bytes


@dataclass(frozen=True, slots=True)
class _Target:
    """Where the POST connects (``url``, by address) and who it is for (``host``)."""

    url: str
    host: str
    host_header: str


async def drain_webhooks(
    db: AsyncSession,
    *,
    limit: int = 20,
    transport: httpx.AsyncBaseTransport | None = None,
    settings: Settings | None = None,
    resolve: Resolver = public_addresses,
) -> int:
    """Claim up to ``limit`` due deliveries and POST each — the worker's ``api_webhooks`` drain.

    Args:
        db: The drainer's own session; committed here.
        limit: Rows claimed per call.
        transport: The HTTP transport (tests); a fresh ``AsyncHTTPTransport`` per delivery
            when omitted. A shared transport pools by address, so only tests pass one.
        settings: The process settings when omitted.
        resolve: The host guard; :func:`public_addresses` outside tests.

    Returns:
        How many rows the call claimed (0 = nothing is due).
    """
    settings = settings or get_settings()
    claims, claimed = await _claim(db, limit=limit, max_attempts=settings.webhook_max_attempts)
    for claim in claims:
        try:
            await _deliver(db, claim, settings, transport, resolve)
        except Exception as exc:  # noqa: BLE001 -- one poisoned delivery must not stop the batch
            await db.rollback()
            # The type only: an error's text can carry the URL or bound SQL parameters.
            log.error("public_api.webhook.crashed", delivery_id=claim.id, error=type(exc).__name__)  # noqa: TRY400
    return claimed


async def _claim(db: AsyncSession, *, limit: int, max_attempts: int) -> tuple[list[_Claim], int]:
    """Count an attempt on each due row and book its next one; fail exhausted rows; commit."""
    at = clock.now()
    rows = (
        await db.scalars(
            select(ApiWebhookDelivery)
            .where(ApiWebhookDelivery.status == "pending", ApiWebhookDelivery.next_attempt_at <= at)
            .order_by(ApiWebhookDelivery.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    claims: list[_Claim] = []
    for row in rows:
        row.updated_at = at
        if row.attempts >= max_attempts:
            # The last attempt crashed before it could record an outcome.
            row.status, row.last_error = "failed", row.last_error or "exhausted"
            _record(row.id, row.event, "failed")
            continue
        row.attempts += 1
        row.next_attempt_at = at + timedelta(seconds=backoff_seconds(row.attempts))
        claims.append(_Claim(id=row.id, attempts=row.attempts, event=row.event))
    await db.commit()
    return claims, len(rows)


async def _deliver(
    db: AsyncSession,
    claim: _Claim,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    resolve: Resolver,
) -> None:
    """Prepare, guard and POST one claimed delivery, then record how it ended."""
    send = await _prepare(db, claim)
    await db.rollback()  # no transaction stays open across the partner's call
    if send is None:
        return
    last = claim.attempts >= settings.webhook_max_attempts
    retry: ApiWebhookOutcome = "failed" if last else "retry"
    try:
        target = await _target(send.url, resolve)
    except ValidationError as exc:
        error = "private" if exc.extra.get("code") == "webhook_url_private" else "invalid"
        await _finish(db, claim, retry, host=_host_of(send.url), last_error=error)
        return
    try:
        status = await _post(target, send, claim.event, settings, transport)
    except (httpx.TimeoutException, TimeoutError):
        await _finish(db, claim, retry, host=target.host, last_error="timeout")
        return
    except httpx.TransportError:
        await _finish(db, claim, retry, host=target.host, last_error="connect")
        return
    if 200 <= status < 300:
        await _finish(
            db,
            claim,
            "sent",
            host=target.host,
            last_status_code=status,
            last_error=None,
            sent_at=clock.now(),
        )
    else:
        await _finish(
            db,
            claim,
            retry,
            host=target.host,
            last_status_code=status,
            last_error=f"http_{status}",
        )


async def _prepare(db: AsyncSession, claim: _Claim) -> _Send | None:
    """The POST to make, or ``None`` (the row moved on, or was failed here for good)."""
    row = await db.get(ApiWebhookDelivery, claim.id, populate_existing=True)
    if row is None or row.status != "pending" or row.attempts != claim.attempts:
        return None
    key = await live_key(db, row.user_id)
    if key is None:
        await _finish(db, claim, "failed", last_error="no_key")
        return None
    hook = await db.get(ApiWebhook, row.user_id, populate_existing=True)
    if hook is None:
        await _finish(db, claim, "failed", last_error="no_webhook")
        return None
    body = json.dumps(row.payload, separators=(",", ":"), sort_keys=True).encode()
    return _Send(url=hook.url, key_hash=key.token_hash, body=body)


async def _target(url: str, resolve: Resolver) -> _Target:
    """Re-check the stored URL, resolve its host and pin the first checked address.

    Raises:
        ValidationError: ``webhook_url_invalid`` / ``webhook_url_private``.
    """
    parts = urlsplit(check_url(url))
    host = parts.hostname or ""
    addresses = await resolve(host, parts.port or 443)
    # IPv4 first: the server may have no IPv6 route.
    address = sorted(addresses, key=lambda a: (":" in a, a))[0]
    netloc = f"[{address}]" if ":" in address else address
    if parts.port is not None:
        netloc += f":{parts.port}"
    pinned = urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))
    return _Target(url=pinned, host=host, host_header=parts.netloc)


async def _post(
    target: _Target,
    send: _Send,
    event: str,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
) -> int:
    """POST the body to the pinned address; the response status (its body is never read)."""
    timestamp = int(clock.now().timestamp())
    headers = {
        "Host": target.host_header,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Csm-Event": event,
        "X-Csm-Timestamp": str(timestamp),
        "X-Csm-Signature": sign(send.key_hash, timestamp, send.body),
    }
    timeout = settings.webhook_timeout_seconds
    client = httpx.AsyncClient(
        transport=transport or httpx.AsyncHTTPTransport(),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,  # an env proxy would bypass the pinned address
    )
    try:
        async with asyncio.timeout(timeout):
            request = client.build_request(
                "POST",
                target.url,
                content=send.body,
                headers=headers,
                extensions={"sni_hostname": target.host},
            )
            response = await client.send(request, stream=True)
            await response.aclose()
            return response.status_code
    finally:
        if transport is None:  # an injected transport belongs to the caller
            await client.aclose()


def _host_of(url: str) -> str:
    """The URL's host for a log line (never the URL itself)."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


async def _finish(
    db: AsyncSession,
    claim: _Claim,
    outcome: ApiWebhookOutcome,
    *,
    host: str = "",
    **values: object,
) -> None:
    """Record ``outcome`` on the claimed attempt (unless a newer one took the row); commit."""
    status = {"sent": "sent", "failed": "failed"}.get(outcome, "pending")
    await db.execute(
        update(ApiWebhookDelivery)
        .where(
            ApiWebhookDelivery.id == claim.id,
            ApiWebhookDelivery.status == "pending",
            ApiWebhookDelivery.attempts == claim.attempts,
        )
        .values(status=status, updated_at=clock.now(), **values)
    )
    await db.commit()
    _record(claim.id, claim.event, outcome, host=host, error=values.get("last_error"))


def _record(
    delivery_id: str,
    event: str,
    outcome: ApiWebhookOutcome,
    *,
    host: str = "",
    error: object = None,
) -> None:
    """Log and count one outcome."""
    log.info(
        "public_api.webhook",
        delivery_id=delivery_id,
        webhook_event=event,
        outcome=outcome,
        host=host,
        error=error,
    )
    record_webhook(event, outcome)


__all__ = ["BACKOFF_SECONDS", "USER_AGENT", "Resolver", "backoff_seconds", "drain_webhooks", "sign"]
