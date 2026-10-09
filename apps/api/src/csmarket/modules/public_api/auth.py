"""Key authentication for the public API: ``Authorization: Bearer csm_…`` -> key and user."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.client_ip import client_ip
from csmarket.core.errors import (
    AccountSuspendedError,
    ForbiddenError,
    RateLimitedError,
    UnauthorizedError,
)
from csmarket.core.logging import hash_short
from csmarket.modules.auth.api import hash_token, hit_counter
from csmarket.modules.public_api.keys import TOKEN_PREFIX
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.users.api import User

#: ``last_used_at`` is refreshed only when older than this.
LAST_USED_REFRESH = timedelta(seconds=60)

#: Failed key authentications allowed per client address per window (the public routes are
#: exempt from the coarse per-IP limiter, so guessing a key must be throttled here).
AUTH_FAIL_LIMIT = 30
AUTH_FAIL_WINDOW = 60


@dataclass(frozen=True)
class ApiCaller:
    """The authenticated key and its owner."""

    key: ApiKey
    user: User


def _ip_allowed(allowlist: list[str], ip: str) -> bool:
    """Whether ``ip`` is inside any CIDR of a non-empty list; unparsable fails closed."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in allowlist:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _token(authorization: str | None) -> str:
    """The ``csm_`` token from the header, or 401."""
    if not authorization:
        raise UnauthorizedError("missing Authorization header", code="unauthorized")
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme != "Bearer" or not token.startswith(TOKEN_PREFIX):
        raise UnauthorizedError("invalid API key", code="unauthorized")
    return token


async def api_caller(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> ApiCaller:
    """Resolve the caller from the bearer key.

    Failed authentications are counted per client address; past :data:`AUTH_FAIL_LIMIT` a
    minute they answer 429 instead of 401.

    Raises:
        UnauthorizedError: ``unauthorized`` -- missing, unknown or revoked key.
        RateLimitedError: ``rate_limited`` -- too many failed attempts from this address.
        AccountSuspendedError: ``account_suspended`` -- the owner is banned.
        ForbiddenError: ``ip_not_allowed`` -- an allow-list is set and the client is outside it.
    """
    try:
        return await _resolve(request, db, authorization)
    except UnauthorizedError:
        over = await hit_counter(
            f"public_api:authfail:{hash_short(client_ip(request))}",
            limit=AUTH_FAIL_LIMIT,
            window=AUTH_FAIL_WINDOW,
        )
        if over:
            raise RateLimitedError(
                "too many failed attempts", code="rate_limited", retry_after=AUTH_FAIL_WINDOW
            ) from None
        raise


async def _resolve(request: Request, db: AsyncSession, authorization: str | None) -> ApiCaller:
    """The caller behind the header (see :func:`api_caller` for the errors)."""
    token = _token(authorization)
    stmt = select(ApiKey).where(ApiKey.token_hash == hash_token(token))
    key = (await db.execute(stmt)).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        raise UnauthorizedError("invalid API key", code="unauthorized")
    user = await db.get(User, key.user_id)
    if user is None:
        raise UnauthorizedError("invalid API key", code="unauthorized")
    if user.banned_at is not None:
        raise AccountSuspendedError("this account has been suspended", code="account_suspended")
    if key.ip_allowlist and not _ip_allowed(key.ip_allowlist, client_ip(request)):
        raise ForbiddenError("this address is not allowed for the key", code="ip_not_allowed")
    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_REFRESH:
        key.last_used_at = now
        await db.commit()
    return ApiCaller(key=key, user=user)


__all__ = ["AUTH_FAIL_LIMIT", "AUTH_FAIL_WINDOW", "LAST_USED_REFRESH", "ApiCaller", "api_caller"]
