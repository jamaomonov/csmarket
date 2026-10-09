"""API keys: issue, reissue, revoke, look up (plan B, Task 2; rulings R2, R3).

The token is ``csm_`` + 32 random bytes (url-safe), shown once; only its ``sha256`` is kept.
A user has one live key: a reissue revokes it. The tariff carries over from the user's newest
key, revoked or not.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.auth.api import hash_token
from csmarket.modules.public_api.ip_allowlist import normalise
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import has_topup

log = get_logger("csmarket.public_api.keys")

TOKEN_PREFIX = "csm_"  # noqa: S105 -- a public prefix, not a secret
#: What a new key inherits from the user's newest key (the tariff follows the user).
CARRIED_FIELDS: tuple[str, ...] = (
    "pricing_profile",
    "ip_allowlist",
    "read_per_min",
    "orders_per_min",
    "feed_per_min",
    "check_per_min",
)


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
    # The tariff, limits and allow-list follow the user, not the live key: revoke-then-issue must
    # not drop a ``cost`` client back to ``retail``.
    newest = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user.id)
            .order_by(ApiKey.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    carried = {f: getattr(newest, f) for f in CARRIED_FIELDS} if newest is not None else {}
    if "ip_allowlist" in carried:
        carried["ip_allowlist"] = list(carried["ip_allowlist"])
    if old is not None:
        old.revoked_at = datetime.now(UTC)
        await db.flush()
    token = new_token()
    key = ApiKey(user_id=user.id, token_hash=hash_token(token), **carried)
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


async def set_pricing_profile(
    db: AsyncSession, *, key: ApiKey, profile: Literal["retail", "cost"]
) -> None:
    """Switch a live key's tariff. Flushes, never commits.

    Orders already placed keep the price and profile stamped on them; only the next order
    reads the new tariff (the key row is read at every request). The tariff follows the user
    to a reissued key (see :func:`issue`).

    Raises:
        ConflictError: ``api_key_revoked`` -- the key is revoked.
    """
    if key.revoked_at is not None:
        raise ConflictError("the API key is revoked", code="api_key_revoked")
    key.pricing_profile = profile
    await db.flush()
    log.info("api_key.tariff", key_id=key.id, profile=profile)


async def set_ip_allowlist(db: AsyncSession, *, user: User, entries: list[str]) -> ApiKey:
    """Replace the user's live key's IP allow-list. Flushes, never commits.

    The addresses are the partner's infrastructure: only their count is logged.

    Raises:
        NotFoundError: ``api_key_missing`` -- no live key.
        ValidationError: ``ip_allowlist_invalid`` -- a bad entry, with its ``index``.
    """
    key = await live_key(db, user.id)
    if key is None:
        raise NotFoundError("no API key", code="api_key_missing")
    key.ip_allowlist = normalise(entries)
    await db.flush()
    log.info("api_key.ip_allowlist", key_id=key.id, count=len(key.ip_allowlist))
    return key


async def revoke_key(db: AsyncSession, *, key: ApiKey) -> None:
    """Revoke one key (the admin's path). Flushes, never commits.

    Raises:
        ConflictError: ``api_key_revoked`` -- already revoked.
    """
    if key.revoked_at is not None:
        raise ConflictError("the API key is already revoked", code="api_key_revoked")
    key.revoked_at = datetime.now(UTC)
    await db.flush()
    log.info("api_key.revoked", key_id=key.id, by_admin=True)


__all__ = [
    "CARRIED_FIELDS",
    "TOKEN_PREFIX",
    "issue",
    "live_key",
    "new_token",
    "revoke",
    "revoke_key",
    "set_pricing_profile",
]
