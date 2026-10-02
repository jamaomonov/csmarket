"""Send and confirm the email confirmation letter (M4b ruling R7, decision D1).

- :func:`send_verification` — enqueue a ``verify`` letter for the account's current address
  with a fresh token, and start the per-account cooldown (Redis
  ``users:email_verify:cooldown:{user_id}``). ``PATCH /me`` sends on every new address;
  ``POST /me/email/verification`` re-sends, past the cooldown only.
- :func:`confirm_email` — anonymous (the link may be opened on another device): stamps
  ``email_verified_at`` when the token is valid and the account's email is still the one it
  names. Idempotent.

Neither the address nor the token is logged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import ConflictError, RateLimitedError
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.api import enqueue, verify_sent_at
from csmarket.modules.users.email_verify import make_token, read_token
from csmarket.modules.users.models import User

log = get_logger("csmarket.users.email")


def _cooldown_key(user_id: str) -> str:
    return f"users:email_verify:cooldown:{user_id}"


async def send_verification(
    db: AsyncSession, user: User, *, settings: Settings | None = None, resend: bool = False
) -> None:
    """Enqueue a confirmation letter for ``user.email``. Flushes, never commits.

    Args:
        db: The request's session.
        user: The account; its email is set and unverified.
        settings: The process settings when omitted.
        resend: A re-send asked for by the user: refused within the cooldown.

    Raises:
        ConflictError: ``email_missing``; ``email_already_verified`` (re-send only).
        RateLimitedError: ``email_verify_cooldown`` within the cooldown (re-send only).
    """
    settings = settings or get_settings()
    email = user.email
    if not email:
        raise ConflictError("add an email first", code="email_missing")
    if resend and user.email_verified_at is not None:
        raise ConflictError("this email is already confirmed", code="email_already_verified")
    cooldown = settings.email_verify_cooldown_seconds
    started = await get_redis().set(_cooldown_key(user.id), "1", ex=cooldown, nx=resend)
    if resend and not started:
        raise RateLimitedError(
            "the letter was just sent", code="email_verify_cooldown", retry_after=cooldown
        )
    expires_at = now() + timedelta(hours=settings.email_verify_ttl_hours)
    await enqueue(
        db,
        kind="verify",
        user_id=user.id,
        address=email,
        payload={"token": make_token(user.id, email, expires_at=expires_at)},
    )
    log.info("users.email.verification_sent", resend=resend)


async def confirm_email(db: AsyncSession, token: str) -> None:
    """Confirm the address a token names. Flushes, never commits.

    Raises:
        ValidationError: ``email_token_invalid`` / ``email_token_expired``.
        ConflictError: ``email_token_stale`` — no such account, or its email changed.
    """
    claim = read_token(token)
    user = await db.scalar(select(User).where(User.id == claim.user_id).with_for_update())
    if user is None or not user.email or user.email.lower() != claim.email:
        log.info("users.email.confirm", outcome="stale")
        raise ConflictError("this link is for another address", code="email_token_stale")
    if user.email_verified_at is None:
        user.email_verified_at = user.updated_at = now()
        await db.flush()
    log.info("users.email.confirm", outcome="confirmed")


async def verification_sent_at(db: AsyncSession, user: User) -> datetime | None:
    """When the latest confirmation letter for the current, unverified address was queued."""
    if not user.email or user.email_verified_at is not None:
        return None
    return await verify_sent_at(db, user_id=user.id, address=user.email)


__all__ = ["confirm_email", "send_verification", "verification_sent_at"]
