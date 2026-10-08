"""API keys: issue, reissue, revoke, look up (plan B, Task 2; rulings R2, R3).

The token is ``csm_`` + 32 random bytes (url-safe), shown once; only its ``sha256`` is kept.
A user has one live key: a reissue revokes it and the tariff carries over to the new one.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.auth.api import hash_token
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import has_topup

log = get_logger("csmarket.public_api.keys")

TOKEN_PREFIX = "csm_"  # noqa: S105 -- a public prefix, not a secret


def new_token() -> str:
    """A fresh API token (never logged, never stored)."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


async def live_key(db: AsyncSession, user_id: str) -> ApiKey | None:
    """The user's live (not revoked) key, if any."""
    stmt = select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def issue(db: AsyncSession, *, user: User) -> tuple[ApiKey, str]:
    """Mint a key, revoking the live one; returns the row and the plain token.

    Eligibility (R2): a booked top-up or the USD wallet switched on. Flushes, never commits.

    Raises:
        ConflictError: ``api_key_not_allowed`` -- neither condition holds;
            ``api_key_race`` -- two issues raced for the same user.
    """
    if not (user.usd_wallet_enabled or await has_topup(db, user.id)):
        raise ConflictError(
            "an API key needs a top-up or the dollar wallet", code="api_key_not_allowed"
        )
    old = await live_key(db, user.id)
    profile = "retail"
    if old is not None:
        profile = old.pricing_profile
        old.revoked_at = datetime.now(UTC)
        await db.flush()
    token = new_token()
    key = ApiKey(user_id=user.id, token_hash=hash_token(token), pricing_profile=profile)
    try:
        async with db.begin_nested():
            db.add(key)
            await db.flush()
    except IntegrityError as exc:  # a concurrent issue won the live-key slot
        raise ConflictError("try again", code="api_key_race") from exc
    log.info("api_key.issued", key_id=key.id, reissue=old is not None)
    return key, token


async def revoke(db: AsyncSession, *, user: User) -> None:
    """Revoke the user's live key. Flushes, never commits.

    Raises:
        NotFoundError: ``api_key_missing`` -- no live key.
    """
    key = await live_key(db, user.id)
    if key is None:
        raise NotFoundError("no API key", code="api_key_missing")
    key.revoked_at = datetime.now(UTC)
    await db.flush()
    log.info("api_key.revoked", key_id=key.id)


__all__ = ["TOKEN_PREFIX", "issue", "live_key", "new_token", "revoke"]
