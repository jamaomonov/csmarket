"""Partner webhook delivery: signed, pinned to a checked address, retried (plan C, Task 3).

Review Focus 1 (never a private address, DNS re-checked at send) and 3 (the signature covers the
timestamp and the exact body bytes) are the two contracts this file guards.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from csmarket.core import clock
from csmarket.core.config import get_settings
from csmarket.core.metrics import API_WEBHOOKS
from csmarket.modules.public_api.models import ApiKey, ApiWebhook, ApiWebhookDelivery
from csmarket.modules.public_api.webhook_sender import BACKOFF_SECONDS, drain_webhooks, sign
from csmarket.modules.users.models import User
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_user

HOST = "hooks.partner.example"
URL = f"https://{HOST}/csm/secret-path-7Q?x=1"
PUBLIC_IP = "93.184.216.34"
TOKEN = "csm_fake_token_for_tests_only"
PAYLOAD: dict[str, Any] = {
    "event": "order.paid",
    "event_id": "e1",
    "created_at": "2026-10-09T10:00:00Z",
    "order": {"order_id": "o1", "status": "buying", "price": {"amount_usd": "1.500000"}},
}

Resolver = Callable[[str, int], Awaitable[list[str]]]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _resolver(*addresses: str) -> Resolver:
    async def resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolve


class Recorder:
    """A ``MockTransport`` handler that records requests and answers a scripted status."""

    def __init__(self, *statuses: int | Exception) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


async def _partner(db: AsyncSession, *, key: bool = True, webhook: bool = True) -> User:
    user = await make_user(db)
    if key:
        db.add(ApiKey(user_id=user.id, token_hash=_hash(TOKEN)))
    if webhook:
        db.add(ApiWebhook(user_id=user.id, url=URL))
    await db.commit()
    return user


async def _delivery(db: AsyncSession, user: User) -> str:
    order = await make_order(db, user=user, status="paid")
    row = ApiWebhookDelivery(
        user_id=user.id, order_id=order.id, event="order.paid", payload=PAYLOAD
    )
    db.add(row)
    await db.commit()
    return row.id


async def _row(db: AsyncSession, row_id: str) -> ApiWebhookDelivery:
    db.expire_all()
    row = await db.get(ApiWebhookDelivery, row_id)
    assert row is not None
    return row


async def _make_due(db: AsyncSession, row_id: str) -> None:
    await db.execute(
        update(ApiWebhookDelivery)
        .where(ApiWebhookDelivery.id == row_id)
        .values(next_attempt_at=clock.now() - timedelta(seconds=1))
    )
    await db.commit()


def _count(event: str, outcome: str) -> float:
    return API_WEBHOOKS.labels(event=event, outcome=outcome)._value.get()


async def test_a_pending_delivery_is_posted_once_signed(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    sent_before = _count("order.paid", "sent")
    rec = Recorder(204)

    assert (
        await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP)) == 1
    )
    assert (
        await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP)) == 0
    )

    [request] = rec.requests
    assert request.method == "POST"
    # Connected to the checked address; the partner's host stays in Host and in SNI.
    assert request.url.host == PUBLIC_IP
    assert request.url.raw_path == b"/csm/secret-path-7Q?x=1"
    assert request.headers["host"] == HOST
    assert request.extensions["sni_hostname"] == HOST
    assert request.headers["content-type"] == "application/json"
    assert request.headers["user-agent"] == "csmarket-webhooks/1"
    assert request.headers["x-csm-event"] == "order.paid"
    body = request.content
    assert body == json.dumps(PAYLOAD, separators=(",", ":"), sort_keys=True).encode()
    ts = int(request.headers["x-csm-timestamp"])
    assert abs(ts - clock.now().timestamp()) < 60
    assert request.headers["x-csm-signature"] == sign(_hash(TOKEN), ts, body)
    tampered = body.replace(b"1.500000", b"9.500000")
    assert sign(_hash(TOKEN), ts, tampered) != request.headers["x-csm-signature"]

    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_status_code, row.last_error) == (
        "sent",
        1,
        204,
        None,
    )
    assert row.sent_at is not None
    assert _count("order.paid", "sent") == sent_before + 1


async def test_an_ipv6_address_is_bracketed(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    await _delivery(db_session, user)
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver("2606:4700::1111"))
    [request] = rec.requests
    assert request.url.netloc == b"[2606:4700::1111]"
    assert request.headers["host"] == HOST


async def test_ipv4_is_preferred_and_a_port_is_kept(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    await _delivery(db_session, user)
    await db_session.execute(
        update(ApiWebhook)
        .where(ApiWebhook.user_id == user.id)
        .values(url=f"https://{HOST}:8443/hook")
    )
    await db_session.commit()
    rec = Recorder(200)
    await drain_webhooks(
        db_session, transport=rec.transport, resolve=_resolver("2606:4700::1111", PUBLIC_IP)
    )
    [request] = rec.requests
    assert request.url.netloc == f"{PUBLIC_IP}:8443".encode()
    assert request.headers["host"] == f"{HOST}:8443"


async def test_the_pinned_address_rotates_per_attempt(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    rec = Recorder(500)
    resolve = _resolver(PUBLIC_IP, "93.184.216.40")
    await drain_webhooks(db_session, transport=rec.transport, resolve=resolve)
    await _make_due(db_session, row_id)
    await drain_webhooks(db_session, transport=rec.transport, resolve=resolve)
    first, second = rec.requests
    assert first.url.host == PUBLIC_IP
    assert second.url.host == "93.184.216.40"


async def test_a_500_stays_pending_and_retries_in_a_minute(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    retry_before = _count("order.paid", "retry")
    before = clock.now()

    await drain_webhooks(
        db_session, transport=Recorder(500).transport, resolve=_resolver(PUBLIC_IP)
    )

    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_status_code, row.last_error) == (
        "pending",
        1,
        500,
        "http_500",
    )
    delay = (row.next_attempt_at - before).total_seconds()
    assert BACKOFF_SECONDS[0] - 1 <= delay <= BACKOFF_SECONDS[0] + 5
    assert _count("order.paid", "retry") == retry_before + 1


async def test_a_redirect_is_not_followed(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://10.0.0.1/steal"})

    await drain_webhooks(
        db_session, transport=httpx.MockTransport(handler), resolve=_resolver(PUBLIC_IP)
    )
    assert len(calls) == 1
    row = await _row(db_session, row_id)
    assert (row.status, row.last_error) == ("pending", "http_302")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectTimeout("t"), "timeout"),
        (httpx.ReadTimeout("t"), "timeout"),
        (httpx.ConnectError("c"), "connect"),
        (httpx.RemoteProtocolError("p"), "connect"),
    ],
)
async def test_a_network_failure_is_retried(
    db_session: AsyncSession, error: Exception, code: str
) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    await drain_webhooks(
        db_session, transport=Recorder(error).transport, resolve=_resolver(PUBLIC_IP)
    )
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_status_code, row.last_error) == (
        "pending",
        1,
        None,
        code,
    )


async def test_backoff_then_failed_after_the_last_attempt(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    failed_before = _count("order.paid", "failed")
    rec = Recorder(500)
    max_attempts = get_settings().webhook_max_attempts
    assert max_attempts == 10
    delays: list[float] = []
    for attempt in range(1, max_attempts + 1):
        before = clock.now()
        await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP))
        row = await _row(db_session, row_id)
        assert row.attempts == attempt
        delays.append((row.next_attempt_at - before).total_seconds())
        if attempt < max_attempts:
            assert row.status == "pending"
            await _make_due(db_session, row_id)

    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 10, "http_500")
    assert len(rec.requests) == 10
    expected = [60, 300, 1800, 7200, 7200, 7200, 7200, 7200, 7200]
    assert [round(d / 10) * 10 for d in delays[:9]] == expected
    assert _count("order.paid", "failed") == failed_before + 1
    # Exhausted: never claimed again.
    await _make_due(db_session, row_id)
    assert (
        await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP)) == 0
    )


async def test_an_attempt_that_crashed_last_is_failed_at_claim(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    await db_session.execute(
        update(ApiWebhookDelivery).where(ApiWebhookDelivery.id == row_id).values(attempts=10)
    )
    await db_session.commit()
    rec = Recorder(200)
    assert (
        await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP)) == 1
    )
    row = await _row(db_session, row_id)
    assert (row.status, row.last_error) == ("failed", "exhausted")
    assert rec.requests == []


async def test_a_host_now_resolving_privately_is_not_sent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 1: the real resolver re-checks at send; DNS now says 10.0.0.1."""
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)

    def private_dns(host: str, port: object, *args: object, **kwargs: object) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport)  # the default resolver

    assert rec.requests == []
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_error) == ("pending", 1, "private")


async def test_any_private_address_among_public_ones_refuses(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)

    def mixed_dns(host: str, port: object, *args: object, **kwargs: object) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_dns)
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport)
    assert rec.requests == []
    assert (await _row(db_session, row_id)).last_error == "private"


async def test_a_stored_url_that_no_longer_passes_is_not_sent(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)
    await db_session.execute(
        update(ApiWebhook).where(ApiWebhook.user_id == user.id).values(url=f"http://{HOST}/h")
    )
    await db_session.commit()
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP))
    assert rec.requests == []
    row = await _row(db_session, row_id)
    assert (row.status, row.last_error) == ("pending", "invalid")


async def test_no_live_key_fails_the_delivery(db_session: AsyncSession) -> None:
    user = await _partner(db_session, key=False)
    row_id = await _delivery(db_session, user)
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP))
    row = await _row(db_session, row_id)
    assert (row.status, row.last_error) == ("failed", "no_key")
    assert rec.requests == []


async def test_no_webhook_fails_the_delivery(db_session: AsyncSession) -> None:
    user = await _partner(db_session, webhook=False)
    row_id = await _delivery(db_session, user)
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP))
    row = await _row(db_session, row_id)
    assert (row.status, row.last_error) == ("failed", "no_webhook")
    assert rec.requests == []


async def test_a_reissued_key_signs_with_the_new_hash(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    await db_session.execute(
        update(ApiKey).where(ApiKey.user_id == user.id).values(revoked_at=clock.now())
    )
    new_token = "csm_fake_reissued_token_for_tests"
    db_session.add(ApiKey(user_id=user.id, token_hash=_hash(new_token)))
    await db_session.commit()
    await _delivery(db_session, user)
    rec = Recorder(200)
    await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP))
    [request] = rec.requests
    ts = int(request.headers["x-csm-timestamp"])
    assert request.headers["x-csm-signature"] == sign(_hash(new_token), ts, request.content)
    assert request.headers["x-csm-signature"] != sign(_hash(TOKEN), ts, request.content)


async def test_a_slow_attempt_never_overwrites_a_newer_one(db_session: AsyncSession) -> None:
    """The outcome write is guarded by the claimed attempt number."""
    user = await _partner(db_session)
    row_id = await _delivery(db_session, user)

    async def bump_then_answer(request: httpx.Request) -> httpx.Response:
        await db_session.connection()  # the sender's session is idle here (rolled back)
        await db_session.execute(
            update(ApiWebhookDelivery).where(ApiWebhookDelivery.id == row_id).values(attempts=2)
        )
        await db_session.commit()
        return httpx.Response(200)

    await drain_webhooks(
        db_session, transport=httpx.MockTransport(bump_then_answer), resolve=_resolver(PUBLIC_IP)
    )
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts) == ("pending", 2)


async def test_the_url_and_signature_never_reach_the_logs(db_session: AsyncSession) -> None:
    user = await _partner(db_session)
    await _delivery(db_session, user)
    await _delivery(db_session, user)
    rec = Recorder(500, 204)
    with capture_logs() as logs:
        await drain_webhooks(db_session, transport=rec.transport, resolve=_resolver(PUBLIC_IP))
    assert logs
    text = json.dumps(logs, default=str)
    for request in rec.requests:
        assert request.headers["x-csm-signature"] not in text
    assert "secret-path" not in text
    assert URL not in text
    assert any(entry.get("host") == HOST for entry in logs)


async def test_a_crash_on_one_row_does_not_stop_the_batch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _partner(db_session)
    first = await _delivery(db_session, user)
    second = await _delivery(db_session, user)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return httpx.Response(200)

    with capture_logs() as logs:
        await drain_webhooks(
            db_session, transport=httpx.MockTransport(handler), resolve=_resolver(PUBLIC_IP)
        )
    statuses = {(await _row(db_session, first)).status, (await _row(db_session, second)).status}
    assert statuses == {"pending", "sent"}
    crashed = [e for e in logs if e["event"] == "public_api.webhook.crashed"]
    assert crashed
    assert crashed[0]["error"] == "RuntimeError"


# --- Pinning keeps TLS honest: the certificate is checked against the host, not the IP. ---


def _self_signed(tmp_path: Path, name: str) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture
async def tls_server(tmp_path: Path) -> AsyncIterator[tuple[int, Path, list[bytes]]]:
    """A local HTTPS server whose certificate names only ``HOST``; records request heads."""
    cert_path, key_path = _self_signed(tmp_path, HOST)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert_path, key_path)
    heads: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            heads.append(head)
            writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port, cert_path, heads
    finally:
        server.close()
        await server.wait_closed()


async def test_pinned_tls_verifies_the_partner_host(
    db_session: AsyncSession, tls_server: tuple[int, Path, list[bytes]]
) -> None:
    """Connected to 127.0.0.1, the handshake still verifies the certificate for ``HOST``."""
    port, cert_path, heads = tls_server
    user = await _partner(db_session)
    await db_session.execute(
        update(ApiWebhook)
        .where(ApiWebhook.user_id == user.id)
        .values(url=f"https://{HOST}:{port}/h")
    )
    await db_session.commit()
    row_id = await _delivery(db_session, user)
    trust = ssl.create_default_context(cafile=str(cert_path))

    await drain_webhooks(
        db_session,
        transport=httpx.AsyncHTTPTransport(verify=trust),
        resolve=_resolver("127.0.0.1"),
    )

    row = await _row(db_session, row_id)
    assert (row.status, row.last_status_code) == ("sent", 204)
    [head] = heads
    assert f"host: {HOST}:{port}".encode() in head.lower()


async def test_pinned_tls_refuses_a_certificate_for_another_host(
    db_session: AsyncSession, tls_server: tuple[int, Path, list[bytes]]
) -> None:
    """The same server under another name: the certificate does not match, nothing is sent."""
    port, cert_path, heads = tls_server
    user = await _partner(db_session)
    await db_session.execute(
        update(ApiWebhook)
        .where(ApiWebhook.user_id == user.id)
        .values(url=f"https://other.partner.example:{port}/h")
    )
    await db_session.commit()
    row_id = await _delivery(db_session, user)
    trust = ssl.create_default_context(cafile=str(cert_path))

    await drain_webhooks(
        db_session,
        transport=httpx.AsyncHTTPTransport(verify=trust),
        resolve=_resolver("127.0.0.1"),
    )

    row = await _row(db_session, row_id)
    assert (row.status, row.last_error) == ("pending", "connect")
    assert heads == []
