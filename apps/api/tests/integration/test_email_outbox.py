"""The email outbox: enqueue in the event's transaction, drained by the worker (M4b T3, R5–R6).

A row is enqueued once per order and kind; the drain resolves the recipient at send time,
sends with the row id as the provider's idempotency key, retries with backoff and gives up
after six attempts; a provider rejection fails the row at once.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core.metrics import EMAILS
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.api import EMAILS_CHANNEL, enqueue
from csmarket.modules.notifications.dev_transport import DEV_MAIL_KEY, DevTransport
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.notifications.resend import EmailRejectedError, EmailRetryableError
from csmarket.modules.notifications.sender import MAX_ATTEMPTS, drain_emails
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import listen_channel, make_order
from tests.integration.payments_factory import make_user

ADDRESS = "buyer@example.test"


class ScriptedTransport:
    """Answers each send with the next scripted outcome: an id, or an exception to raise."""

    def __init__(self, *outcomes: str | Exception) -> None:
        self.outcomes = list(outcomes)
        self.keys: list[str] = []
        self.sent: list[dict[str, Any]] = []

    async def send(self, **letter: Any) -> str:  # Any: the transport protocol's keywords
        self.keys.append(letter["idempotency_key"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.sent.append(letter)
        return outcome


async def _user(db: AsyncSession, *, verified: bool = False, email: str | None = ADDRESS) -> User:
    user = await make_user(db)
    user.email = email
    user.email_verified_at = clock.now() if verified else None
    await db.commit()
    return user


async def _verify_row(db: AsyncSession, user: User) -> str:
    row_id = await enqueue(
        db, kind="verify", user_id=user.id, address=user.email, payload={"token": "t0k"}
    )
    assert row_id is not None
    await db.commit()
    return row_id


async def _row(db: AsyncSession, row_id: str) -> EmailOutbox:
    db.expire_all()
    row = await db.get(EmailOutbox, row_id)
    assert row is not None
    return row


async def _make_due(db: AsyncSession, row_id: str) -> None:
    await db.execute(
        update(EmailOutbox)
        .where(EmailOutbox.id == row_id)
        .values(next_attempt_at=clock.now() - timedelta(seconds=1))
    )
    await db.commit()


def _count(kind: str, outcome: str) -> float:
    return EMAILS.labels(kind=kind, outcome=outcome)._value.get()


async def test_one_order_and_kind_enqueue_once(db_session: AsyncSession) -> None:
    order = await make_order(db_session, status="paid")
    first = await enqueue(db_session, kind="receipt", user_id=order.user_id, order_id=order.id)
    second = await enqueue(db_session, kind="receipt", user_id=order.user_id, order_id=order.id)
    await db_session.commit()
    assert first is not None
    assert second is None
    rows = (await db_session.scalars(select(EmailOutbox))).all()
    assert [(r.kind, r.status, r.attempts) for r in rows] == [("receipt", "pending", 0)]


async def test_the_wake_up_is_delivered_on_commit(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    async with listen_channel(EMAILS_CHANNEL) as events:
        row_id = await enqueue(
            db_session, kind="verify", user_id=user.id, address=ADDRESS, payload={"token": "x"}
        )
        assert await events.drain() == []
        await db_session.commit()
        assert await events.drain() == [row_id]


async def test_drain_sends_a_verify_letter_through_the_dev_transport(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    user_id = user.id
    row_id = await _verify_row(db_session, user)
    sent_before = _count("verify", "sent")
    assert await drain_emails(db_session, transport=DevTransport(get_redis())) == 1
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts) == ("sent", 1)
    assert row.sent_at is not None
    assert row.provider_message_id == f"dev-{row_id}"
    letters = [json.loads(x) for x in await get_redis().lrange(DEV_MAIL_KEY, 0, -1)]
    assert [(m["to_user"], m["kind"]) for m in letters] == [(user_id, "verify")]
    assert "/account/email/confirm?token=t0k" in letters[0]["text"]
    assert ADDRESS not in json.dumps(letters)
    assert _count("verify", "sent") == sent_before + 1
    assert await drain_emails(db_session, transport=DevTransport(get_redis())) == 0


async def test_retry_reuses_idempotency_key(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    row_id = await _verify_row(db_session, user)
    transport = ScriptedTransport(EmailRetryableError("http_503"), "msg-1")
    await drain_emails(db_session, transport=transport)
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_error_code) == ("pending", 1, "http_503")
    assert row.next_attempt_at > clock.now()
    assert await drain_emails(db_session, transport=transport) == 0  # not due yet
    await _make_due(db_session, row_id)
    await drain_emails(db_session, transport=transport)
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.provider_message_id) == ("sent", 2, "msg-1")
    assert transport.keys == [row_id, row_id]


async def test_a_rejection_fails_the_row_at_once(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    row_id = await _verify_row(db_session, user)
    failed_before = _count("verify", "failed")
    await drain_emails(db_session, transport=ScriptedTransport(EmailRejectedError("http_422")))
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts, row.last_error_code) == ("failed", 1, "http_422")
    assert _count("verify", "failed") == failed_before + 1


async def test_six_retryable_failures_fail_the_row(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    row_id = await _verify_row(db_session, user)
    transport = ScriptedTransport(*(EmailRetryableError("timeout") for _ in range(MAX_ATTEMPTS)))
    delays = []
    for _ in range(MAX_ATTEMPTS):
        before = clock.now()
        await drain_emails(db_session, transport=transport)
        row = await _row(db_session, row_id)
        delays.append(round((row.next_attempt_at - before).total_seconds() / 60))
        await _make_due(db_session, row_id)
    row = await _row(db_session, row_id)
    assert (row.status, row.attempts) == ("failed", MAX_ATTEMPTS)
    assert delays[:5] == [1, 5, 15, 60, 180]
    assert len(transport.keys) == MAX_ATTEMPTS


@pytest.mark.parametrize(
    ("email", "verified"), [(None, False), (ADDRESS, False)], ids=["no-email", "unverified"]
)
async def test_send_skips_unverified_address(
    db_session: AsyncSession, email: str | None, *, verified: bool
) -> None:
    user = await _user(db_session, email=email, verified=verified)
    order = await make_order(db_session, user=user, status="paid")
    row_id = await enqueue(db_session, kind="receipt", user_id=user.id, order_id=order.id)
    assert row_id is not None
    await db_session.commit()
    transport = ScriptedTransport()
    await drain_emails(db_session, transport=transport)
    assert (await _row(db_session, row_id)).status == "skipped"
    assert transport.keys == []


async def test_a_verify_letter_for_an_address_since_replaced_is_skipped(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    row_id = await _verify_row(db_session, user)
    user.email = "other@example.test"
    await db_session.commit()
    transport = ScriptedTransport()
    await drain_emails(db_session, transport=transport)
    assert (await _row(db_session, row_id)).status == "skipped"
    assert transport.keys == []


async def test_a_crash_inside_one_row_does_not_stop_the_drain(db_session: AsyncSession) -> None:
    first, second = await _user(db_session), await _user(db_session)
    crashed = await _verify_row(db_session, first)
    sent = await _verify_row(db_session, second)
    transport = ScriptedTransport(RuntimeError("boom"), "msg-2")
    assert await drain_emails(db_session, transport=transport) == 2
    assert (await _row(db_session, sent)).status == "sent"
    row = await _row(db_session, crashed)
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.next_attempt_at > clock.now()


async def test_dev_route_lists_only_the_signed_in_users_letters(
    integration_client: AsyncClient, customer_headers: Any, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    me = (await integration_client.get("/api/v1/me", headers=headers)).json()
    stranger = await _user(db_session)
    transport = DevTransport(get_redis())
    for user_id in (me["id"], stranger.id):
        await transport.send(
            to=ADDRESS,
            subject="s",
            html="<p>h</p>",
            text="t",
            idempotency_key=f"k-{user_id}",
            user_id=user_id,
            kind="verify",
        )
    got = await integration_client.get("/api/v1/dev/emails?kind=verify", headers=headers)
    assert got.status_code == 200
    assert [m["to_user"] for m in got.json()] == [me["id"]]
    assert (
        await integration_client.get("/api/v1/dev/emails?kind=receipt", headers=headers)
    ).json() == []
