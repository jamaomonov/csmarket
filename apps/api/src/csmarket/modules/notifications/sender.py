"""The worker's ``emails`` drain (M4b ruling R5).

:func:`drain_emails` claims due ``pending`` rows (``FOR UPDATE SKIP LOCKED``) and, in the
claim's own short transaction, counts the attempt and books the next one ahead of time
(1, 5, 15, 60, 180, 600 minutes). The send then runs with **no lock and no open
transaction**, so a crash or a hung provider leaves the row ``pending`` and due again at
the booked time — sent again under the same idempotency key (the row id), which the
provider deduplicates. Per row:

- resolve the recipient now: an order letter goes to the user's email only while it is
  verified; a ``verify`` letter only while the address it confirms is still the user's and
  unverified — otherwise ``skipped``;
- render in the user's locale and send; ``sent`` with the provider's id; a rejection →
  ``failed`` at once; a retryable failure keeps the booked retry, or ``failed`` after the
  sixth attempt. Each outcome is a metric (``csmarket_emails_total``).

The outcome write is guarded by ``status = 'pending'`` and the claimed attempt number, so a
slow attempt never overwrites a newer one. A failed letter never touches money or orders.
Log lines carry the outbox id, the kind and the outcome — never an address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, cast
from urllib.parse import quote

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import EmailOutcome, record_email
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.dev_transport import DevTransport
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.notifications.resend import (
    EmailRejectedError,
    EmailRetryableError,
    ResendClient,
)
from csmarket.modules.notifications.templates import EmailContent, Links, Locale, render
from csmarket.modules.users.models import User

log = get_logger("csmarket.notifications.sender")

#: Minutes from an attempt to the next one; the attempt count is its length.
BACKOFF_MINUTES = (1, 5, 15, 60, 180, 600)
MAX_ATTEMPTS = len(BACKOFF_MINUTES)
_LOCALE_PREFIX: dict[str, str] = {"ru": "", "uz": "/uz", "en": "/en"}


class EmailTransport(Protocol):
    """Sends one rendered letter: Resend in prod, Redis in dev."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        idempotency_key: str,
        user_id: str,
        kind: str,
    ) -> str:
        """Send the letter; return the provider's message id."""
        ...


def build_transport(settings: Settings) -> EmailTransport:
    """The transport ``settings.email_transport`` names."""
    if settings.email_transport == "resend":
        return ResendClient(
            settings.resend_api_key,
            settings.resend_base_url,
            settings.email_send_timeout_seconds,
            sender=f"{settings.email_from_name} <{settings.email_from}>",
        )
    return DevTransport(get_redis())


@dataclass(frozen=True, slots=True)
class _Claim:
    """A row claimed for this attempt, and which attempt it is."""

    id: str
    attempts: int


@dataclass(frozen=True, slots=True)
class _Letter:
    """Everything a send needs, read before the transaction closes."""

    kind: str
    user_id: str
    to: str
    content: EmailContent


async def drain_emails(
    db: AsyncSession,
    *,
    limit: int = 20,
    transport: EmailTransport | None = None,
    settings: Settings | None = None,
) -> int:
    """Claim up to ``limit`` due letters and send each — the worker's ``emails`` drain.

    Args:
        db: The drainer's own session; committed here.
        limit: Rows claimed per call.
        transport: Where letters go; :func:`build_transport` of the settings when omitted.
        settings: The process settings when omitted.

    Returns:
        How many rows the call claimed (0 = nothing is due).
    """
    settings = settings or get_settings()
    claims, claimed = await _claim(db, limit=limit)
    if not claims:
        return claimed
    transport = transport or build_transport(settings)
    for claim in claims:
        try:
            await _deliver(db, transport, claim, settings)
        except Exception as exc:  # noqa: BLE001 -- one poisoned letter must not stop the batch
            await db.rollback()
            # The type only: an error's text can carry an address or bound SQL parameters.
            log.error("notifications.email.crashed", outbox_id=claim.id, error=type(exc).__name__)  # noqa: TRY400
    return claimed


async def _claim(db: AsyncSession, *, limit: int) -> tuple[list[_Claim], int]:
    """Count an attempt on each due row and book its next one; fail exhausted rows; commit."""
    at = clock.now()
    rows = (
        await db.scalars(
            select(EmailOutbox)
            .where(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= at)
            .order_by(EmailOutbox.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    claims: list[_Claim] = []
    for row in rows:
        row.updated_at = at
        if row.attempts >= MAX_ATTEMPTS:
            # The last attempt crashed before it could record an outcome.
            row.status, row.last_error_code = "failed", row.last_error_code or "exhausted"
            _record(row.id, row.kind, "failed")
            continue
        row.attempts += 1
        row.next_attempt_at = at + timedelta(minutes=BACKOFF_MINUTES[row.attempts - 1])
        claims.append(_Claim(id=row.id, attempts=row.attempts))
    await db.commit()
    return claims, len(rows)


async def _deliver(
    db: AsyncSession, transport: EmailTransport, claim: _Claim, settings: Settings
) -> None:
    """Resolve, render and send one claimed letter, then record how it ended."""
    letter = await _prepare(db, claim, settings)
    await db.rollback()  # no transaction stays open across the provider call
    if letter is None:
        return
    try:
        message_id = await transport.send(
            to=letter.to,
            subject=letter.content.subject,
            html=letter.content.html,
            text=letter.content.text,
            idempotency_key=claim.id,
            user_id=letter.user_id,
            kind=letter.kind,
        )
    except EmailRejectedError as exc:
        await _finish(db, claim, letter.kind, "failed", last_error_code=exc.code)
    except EmailRetryableError as exc:
        outcome: EmailOutcome = "failed" if claim.attempts >= MAX_ATTEMPTS else "retry"
        await _finish(db, claim, letter.kind, outcome, last_error_code=exc.code)
    else:
        await _finish(
            db, claim, letter.kind, "sent", provider_message_id=message_id, sent_at=clock.now()
        )


async def _prepare(db: AsyncSession, claim: _Claim, settings: Settings) -> _Letter | None:
    """The letter to send, or ``None`` after marking the row ``skipped``."""
    row = await db.get(EmailOutbox, claim.id, populate_existing=True)
    if row is None or row.status != "pending" or row.attempts != claim.attempts:
        return None
    user = await db.get(User, row.user_id)
    to = _recipient(row, user)
    if user is None or to is None:
        await _finish(db, claim, row.kind, "skipped")
        return None
    locale = cast("Locale", user.locale)
    number = row.payload.get("number")
    content = render(
        row.kind,
        locale=locale,
        number=number,
        payload=row.payload,
        links=_links(settings, locale, number=number, token=row.payload.get("token")),
    )
    return _Letter(kind=row.kind, user_id=row.user_id, to=to, content=content)


def _recipient(row: EmailOutbox, user: User | None) -> str | None:
    """Where the letter may go now (ruling R5, decision D1), or ``None`` to skip it."""
    if user is None or not user.email:
        return None
    if row.kind == "verify":
        same = row.address is not None and row.address.lower() == user.email.lower()
        return user.email if same and user.email_verified_at is None else None
    return user.email if user.email_verified_at is not None else None


def _links(settings: Settings, locale: str, *, number: str | None, token: str | None) -> Links:
    """Absolute storefront links in ``locale`` (ru has no prefix)."""
    home = settings.web_base_url.rstrip("/")
    root = home + _LOCALE_PREFIX.get(locale, "")
    return Links(
        order_url=f"{root}/orders/{number}" if number else "",
        balance_url=f"{root}/account/balance",
        confirm_url=f"{root}/account/email/confirm?token={quote(token)}" if token else "",
        home_url=root or home,
    )


async def _finish(
    db: AsyncSession,
    claim: _Claim,
    kind: str,
    outcome: EmailOutcome,
    **values: object,
) -> None:
    """Record ``outcome`` on the claimed attempt (unless a newer one took the row); commit."""
    status = {"sent": "sent", "skipped": "skipped", "failed": "failed"}.get(outcome, "pending")
    await db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.id == claim.id,
            EmailOutbox.status == "pending",
            EmailOutbox.attempts == claim.attempts,
        )
        .values(status=status, updated_at=clock.now(), **values)
    )
    await db.commit()
    _record(claim.id, kind, outcome)


def _record(outbox_id: str, kind: str, outcome: EmailOutcome) -> None:
    """Log and count one outcome."""
    log.info("notifications.email", outbox_id=outbox_id, kind=kind, outcome=outcome)
    record_email(kind, outcome)
