"""Sessions for Steam-signed-in users: open, rotate (with the reuse trip-wire), revoke, resolve.

The Steam flow lives in :func:`steam_login`; :func:`dev_login` is its Steam-less twin for
local work and e2e (ruling P6), reachable only when ``settings.dev_login_active``.

A session is a ``refresh_tokens`` row; its id is the ``sid`` claim of every access token
minted from it. Revoking a session writes ``revoked_at`` and drops a Redis marker
``auth:revoked_sid:{sid}`` so its outstanding access tokens die at once; a logout that
presents the access token also blocklists that token's ``jti`` (``auth:revoked:{jti}``).
Service functions flush and leave the commit to the caller — except the reuse trip-wire,
which commits its burn-down itself (see :func:`refresh_session`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from redis.exceptions import RedisError
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import AccountSuspendedError, UnauthorizedError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.auth import jwt as authjwt
from csmarket.modules.auth import steam
from csmarket.modules.auth.models import RefreshToken
from csmarket.modules.auth.security import hash_token, new_refresh_token
from csmarket.modules.users.api import User, get_user_by_id, set_roles, upsert_user_by_steam

log = get_logger("csmarket.auth.service")

#: How long a revoked or expired row is kept before :func:`purge_stale_refresh_tokens`
#: deletes it. Deleting at once would turn "your session was replaced" (reuse detection
#: on a late retry) into "this session never existed".
SESSION_RETENTION_DAYS = 7

#: Rows deleted per sweep — bounded so one DELETE never holds locks for long.
_PURGE_BATCH = 5000

#: Which app a Steam sign-in returns to; each has its own origin and callback page.
AppName = Literal["web", "admin"]

#: ``verify_callback``'s shape, injectable for tests.
SteamVerifier = Callable[..., Awaitable[int]]
#: ``fetch_persona``'s shape, injectable for tests.
PersonaFetcher = Callable[..., Awaitable[tuple[str | None, str | None]]]


@dataclass(frozen=True)
class SessionTokens:
    """Access + opaque refresh token and their TTLs (seconds)."""

    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int
    user: User


async def open_session(
    db: AsyncSession,
    *,
    user: User,
    settings: Settings | None = None,
) -> SessionTokens:
    """Create a ``refresh_tokens`` row and mint the matching access + refresh tokens.

    Every way into an account converges here — Steam, dev login and refresh rotation —
    which makes it the one place worth checking the ban: a suspended account is told
    why at sign-in instead of getting a working login followed by a broken app.

    Args:
        db: The caller's session; flushed, not committed.
        user: The account signing in.
        settings: Overrides the process settings; for tests.

    Returns:
        The new session's tokens.

    Raises:
        AccountSuspendedError: The account is banned.
    """
    s = settings or get_settings()
    if user.banned_at is not None:
        raise AccountSuspendedError("this account has been suspended")
    refresh = new_refresh_token()
    session_id = new_id()
    db.add(
        RefreshToken(
            id=session_id,
            user_id=user.id,
            token_hash=hash_token(refresh),
            expires_at=now() + timedelta(seconds=s.jwt_refresh_ttl_seconds),
        )
    )
    await db.flush()
    return SessionTokens(
        access_token=authjwt.mint_access(sub=user.id, sid=session_id, settings=s),
        refresh_token=refresh,
        access_expires_in=s.jwt_access_ttl_seconds,
        refresh_expires_in=s.jwt_refresh_ttl_seconds,
        user=user,
    )


def callback_url(settings: Settings, app: AppName) -> str:
    """Where Steam returns the browser for ``app`` — also the only accepted ``return_to``."""
    origin = settings.admin_base_url if app == "admin" else settings.web_base_url
    return f"{origin.rstrip('/')}/auth/steam/callback"


async def steam_login(
    db: AsyncSession,
    params: dict[str, str],
    *,
    app: AppName,
    nonce: str | None,
    settings: Settings | None = None,
    verifier: SteamVerifier | None = None,
    persona: PersonaFetcher | None = None,
) -> SessionTokens:
    """Verify a Steam OpenID callback for ``app`` and open a session.

    Nothing is written until Steam has said yes: a refused assertion leaves no user row.
    The persona (name, avatar) is fetched only with a Steam Web API key and is
    best-effort — a failure signs the user in nameless.

    Args:
        db: The request's session; flushed, not committed.
        params: The ``openid.*`` params exactly as Steam appended them.
        app: Which app asked; its callback is the only ``return_to`` accepted.
        nonce: The sign-in nonce from this browser's ``csmarket_oid`` cookie (``None``
            when absent); the signed ``return_to`` must carry the same one.
        settings: Overrides the process settings; for tests.
        verifier: Replaces :func:`steam.verify_callback`; for tests.
        persona: Replaces :func:`steam.fetch_persona`; for tests.

    Returns:
        The new session's tokens.

    Raises:
        UnauthorizedError: Verification failed (foreign ``return_to``, bad
            ``claimed_id``, unsigned fields, missing or foreign nonce, Steam said no,
            Steam unreachable).
        AccountSuspendedError: The account is banned.
    """
    s = settings or get_settings()
    verify = verifier or steam.verify_callback
    try:
        steam_id = await verify(params, expected_return_to=callback_url(s, app), nonce=nonce)
    except steam.SteamAuthError as exc:
        # The message is one of steam.py's fixed strings — never the steamid, the params
        # or upstream text; the cause goes out by class name only.
        cause = exc.__cause__
        log.info(
            "auth.steam.rejected",
            reason=str(exc),
            error=type(cause).__name__ if cause is not None else None,
            app=app,
        )
        raise UnauthorizedError("steam verification failed") from exc
    name: str | None = None
    avatar: str | None = None
    if s.steam_api_key:
        fetch = persona or steam.fetch_persona
        name, avatar = await fetch(steam_id, api_key=s.steam_api_key)
    user = await upsert_user_by_steam(
        db, steam_id=str(steam_id), display_name=name, avatar_url=avatar
    )
    return await open_session(db, user=user, settings=s)


async def dev_login(
    db: AsyncSession, *, steam_id: str, display_name: str | None, admin: bool
) -> SessionTokens:
    """Open a session for ``steam_id`` without Steam — dev and e2e only (ruling P6).

    The route refuses unless ``settings.dev_login_active``; this function trusts it.

    Args:
        db: The request's session; flushed, not committed.
        steam_id: The steamid64 to sign in as, as text.
        display_name: Optional name for the account.
        admin: Grant the ``admin`` role (added to any roles the account has).

    Returns:
        The new session's tokens.

    Raises:
        AccountSuspendedError: The account is banned.
    """
    user = await upsert_user_by_steam(
        db, steam_id=steam_id, display_name=display_name, avatar_url=None
    )
    if admin:
        await set_roles(db, user, [*user.roles, "admin"])
    return await open_session(db, user=user)


async def refresh_session(
    db: AsyncSession,
    refresh_token: str,
    *,
    settings: Settings | None = None,
) -> SessionTokens:
    """Rotate a refresh token: revoke the old row, open a new session.

    Reuse trip-wire: presenting a refresh token whose row is already revoked revokes
    **every** live session of the user. That burn-down is committed here, before the
    error is raised — the request dependency rolls back on any raised error, which would
    otherwise undo it and leave the other refresh tokens working.

    Args:
        db: The caller's session. Flushed on success; committed on reuse.
        refresh_token: The opaque token from the cookie.
        settings: Overrides the process settings; for tests.

    Returns:
        The new session's tokens.

    Raises:
        UnauthorizedError: Unknown, reused or expired token, or the user is gone.
        AccountSuspendedError: The account is banned.
    """
    s = settings or get_settings()
    # FOR UPDATE closes the rotation TOCTOU: without the row lock two requests with the
    # same token both read ``revoked_at IS NULL`` and both mint a session. With it the
    # loser blocks here, then sees the revoked row and trips reuse detection.
    stmt = (
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise UnauthorizedError("invalid refresh token")

    if row.revoked_at is not None:
        revoked = await _revoke_all_for_user(db, row.user_id)
        await db.commit()
        for sid in revoked:
            await _blocklist_session_id(sid, settings=s)
        raise UnauthorizedError("refresh token reuse detected")

    if row.expires_at <= now():
        raise UnauthorizedError("refresh token expired")

    user = await get_user_by_id(db, row.user_id)
    if user is None:
        raise UnauthorizedError("user no longer exists")

    row.revoked_at = now()
    # The rotated-out session's access token dies immediately, not after 15 min.
    await _blocklist_session_id(row.id, settings=s)
    return await open_session(db, user=user, settings=s)


async def _blocklist_access_token(access_token: str, *, settings: Settings) -> None:
    """Add a still-valid access token's ``jti`` to the Redis blocklist.

    Best-effort: an invalid or expired token has nothing to revoke and is ignored. The
    marker lives as long as the token would have.
    """
    try:
        claims = authjwt.verify(access_token, expected_kind="access", settings=settings)
    except UnauthorizedError:
        return
    ttl = int((claims.exp - now()).total_seconds())
    if ttl <= 0:
        return
    await _blocklist_write(f"auth:revoked:{claims.jti}", ttl=ttl, kind="access")


async def _blocklist_session_id(sid: str, *, settings: Settings) -> None:
    """Kill every outstanding access token of a revoked session immediately.

    Access tokens carry ``sid`` and live their full TTL independently of the row; the
    ``auth:revoked_sid`` marker, checked per request, ends them now. The marker outlives
    the longest access token that can carry this ``sid`` and then disappears.
    """
    await _blocklist_write(
        f"auth:revoked_sid:{sid}", ttl=settings.jwt_access_ttl_seconds, kind="session"
    )


async def _blocklist_write(key: str, *, ttl: int, kind: str) -> None:
    """Set a blocklist marker. **Fails open**, like :func:`_is_blocklisted`.

    The ``refresh_tokens`` row is the source of truth and is written regardless, so a
    Redis blip costs only the acceleration: the access token lives out its 15-minute TTL
    instead of dying now. Raising would turn a refresh or a sign-out into a 500 and leave
    the customer stuck. The key is never logged (it carries a ``jti``/``sid``).

    Args:
        key: The blocklist key to set.
        ttl: Seconds the marker lives.
        kind: ``"access"`` or ``"session"`` — for the log line.
    """
    try:
        await get_redis().set(key, "1", ex=ttl)
    except RedisError:
        log.exception("auth.blocklist_unwritable", blocklist=kind)


async def logout(
    db: AsyncSession,
    refresh_token: str,
    *,
    access_token: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Revoke the session of ``refresh_token``. Idempotent; an unknown token is a no-op.

    Args:
        db: The caller's session; flushed, not committed.
        refresh_token: The opaque token from the cookie.
        access_token: The Bearer token, when the request carried one — its ``jti`` is
            blocklisted too.
        settings: Overrides the process settings; for tests.
    """
    s = settings or get_settings()
    if access_token:
        await _blocklist_access_token(access_token, settings=s)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return  # don't leak whether the token ever existed
    if row.revoked_at is None:
        row.revoked_at = now()
        # Cookie-only logout must kill the access token too.
        await _blocklist_session_id(row.id, settings=s)
        await db.flush()


async def _revoke_all_for_user(db: AsyncSession, user_id: str) -> list[str]:
    """Revoke every live session of ``user_id`` in one statement; return their ids."""
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now())
        .returning(RefreshToken.id)
    )
    return [str(sid) for sid in result.scalars().all()]


async def _is_blocklisted(key: str, *, kind: str) -> bool:
    """Whether this access token or session has been revoked.

    **Fails open.** This runs on every authenticated request: refusing on a Redis blip
    would sign every customer out at once, and raising would do that *and* page. The
    cost is bounded — the blocklist only accelerates an expiry that happens within the
    15-minute access TTL anyway, and the ban is checked against Postgres, not here.

    The key is never logged: it carries a ``jti``/``sid``, which identifies a live
    session.

    Args:
        key: The blocklist key to read.
        kind: ``"access"`` or ``"session"`` — for the log line, since the key cannot go
            in it.

    Returns:
        ``True`` only when Redis positively says the token is revoked.
    """
    try:
        return await get_redis().get(key) is not None
    except RedisError:
        log.exception("auth.blocklist_unreadable", blocklist=kind)
        return False


async def resolve_current_user(
    db: AsyncSession,
    access_token: str,
    *,
    settings: Settings | None = None,
) -> User:
    """Resolve the signed-in user from an access JWT.

    Args:
        db: The request's session.
        access_token: The Bearer token.
        settings: Overrides the process settings; for tests.

    Returns:
        The user.

    Raises:
        UnauthorizedError: Invalid, expired or revoked token, or the user is gone.
        AccountSuspendedError: The account is banned — 403, so the apps don't loop
            refreshing.
    """
    s = settings or get_settings()
    claims = authjwt.verify(access_token, expected_kind="access", settings=s)
    if await _is_blocklisted(f"auth:revoked:{claims.jti}", kind="access"):
        raise UnauthorizedError("token revoked")
    if await _is_blocklisted(f"auth:revoked_sid:{claims.sid}", kind="session"):
        raise UnauthorizedError("session revoked")
    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise UnauthorizedError("user not found")
    # Checked on every request rather than by revoking sessions on ban: a ban takes
    # effect on the very next call, even with an access token minted seconds earlier.
    if user.banned_at is not None:
        raise AccountSuspendedError("this account has been suspended")
    return user


async def purge_stale_refresh_tokens(db: AsyncSession, *, limit: int = _PURGE_BATCH) -> int:
    """Delete rows that expired or were revoked more than the retention window ago.

    Both conditions are needed: a logout leaves ``expires_at`` in the future, so expiry
    alone never reaches a revoked row.

    Args:
        db: Session to run in; the caller owns the transaction.
        limit: Maximum rows to delete in this sweep.

    Returns:
        How many rows were deleted.
    """
    cutoff = now() - timedelta(days=SESSION_RETENTION_DAYS)
    doomed = (
        select(RefreshToken.id)
        .where(or_(RefreshToken.expires_at < cutoff, RefreshToken.revoked_at < cutoff))
        .limit(limit)
    )
    result = await db.execute(
        delete(RefreshToken).where(RefreshToken.id.in_(doomed.scalar_subquery()))
    )
    # ``rowcount`` lives on CursorResult; async execute() is typed as the narrower Result.
    return int(getattr(result, "rowcount", 0) or 0)
