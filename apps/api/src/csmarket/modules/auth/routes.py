"""``/api/v1/auth`` — Steam sign-in, refresh rotation, logout, dev login."""

from __future__ import annotations

import secrets
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import AppError, NotFoundError, UnauthorizedError, app_error_handler
from csmarket.modules.auth import steam
from csmarket.modules.auth.cookies import (
    OID_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    clear_oid_cookie,
    clear_refresh_cookie,
    set_oid_cookie,
    set_refresh_cookie,
)
from csmarket.modules.auth.ip_guard import guard_ip
from csmarket.modules.auth.schemas import DevLoginIn, SteamCallbackIn, TokensOut
from csmarket.modules.auth.service import (
    SessionTokens,
    callback_url,
    dev_login,
    logout,
    refresh_session,
    steam_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_response(response: Response, tokens: SessionTokens) -> TokensOut:
    """Refresh token → HttpOnly cookie; access token → body (ruling P2)."""
    set_refresh_cookie(
        response,
        token=tokens.refresh_token,
        max_age=tokens.refresh_expires_in,
        settings=get_settings(),
    )
    return TokensOut(access_token=tokens.access_token, expires_in=tokens.access_expires_in)


@router.get(
    "/steam/start",
    summary="Begin a Steam sign-in (302 to steamcommunity.com)",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
async def steam_start(
    app: Annotated[Literal["web", "admin"], Query()] = "web",
    locale: Annotated[Literal["ru", "uz", "en"], Query()] = "ru",
) -> RedirectResponse:
    """Send the browser to Steam, bound to this browser by a fresh nonce.

    ``return_to`` is the app's own callback page; realm is the app's origin. Both come
    from settings — the query only picks which app, so the redirect cannot be aimed
    anywhere else. The nonce goes into ``return_to`` (which Steam signs) and into the
    ``csmarket_oid`` cookie; :func:`steam_complete` requires the two to match.
    """
    s = get_settings()
    nonce = secrets.token_urlsafe(16)
    query = urlencode({"locale": locale, steam.NONCE_PARAM: nonce})
    realm = s.admin_base_url if app == "admin" else s.web_base_url
    url = steam.build_login_url(
        return_to=f"{callback_url(s, app)}?{query}", realm=realm.rstrip("/")
    )
    redirect = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    set_oid_cookie(redirect, nonce=nonce, settings=s)
    return redirect


@router.post(
    "/steam",
    response_model=TokensOut,
    summary="Complete a Steam sign-in",
    responses={401: {"description": "Not verified, or not started in this browser"}},
)
async def steam_complete(
    body: SteamCallbackIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    oid: Annotated[str | None, Cookie(alias=OID_COOKIE_NAME)] = None,
) -> TokensOut | JSONResponse:
    """Verify the callback with Steam and open a session.

    The signed ``return_to`` must carry the nonce of this browser's ``csmarket_oid``
    cookie (login-CSRF defence). The nonce is single-use: the cookie is cleared on every
    outcome, so a failure is retried from ``/auth/steam/start``.

    Keyless by design: replaying an OpenID assertion is refused by Steam itself
    (``check_authentication`` succeeds once), so an ``Idempotency-Key`` adds nothing.
    """
    s = get_settings()
    try:
        await guard_ip(request, bucket="steam-login")
        tokens = await steam_login(db, body.params, app=body.app, nonce=oid)
    except AppError as exc:
        # Rendered here rather than raised so the refusal can clear the nonce cookie too
        # (a raised error gets a fresh response). Roll back by hand: the request session
        # commits on a normal return, and a refused sign-in must write nothing.
        await db.rollback()
        refused = await app_error_handler(request, exc)
        clear_oid_cookie(refused, settings=s)
        return refused
    clear_oid_cookie(response, settings=s)
    return _session_response(response, tokens)


@router.post("/refresh", response_model=TokensOut, summary="Rotate the refresh cookie")
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokensOut:
    """Rotate-on-use; the reuse trip-wire lives in the service.

    Keyless: rotation is inherently single-use, a replay is the attack it detects. Must
    write nothing before :func:`refresh_session` — on reuse the service commits its
    burn-down, which would commit any earlier pending write too.
    """
    if not refresh_token:
        raise UnauthorizedError("missing refresh token")
    tokens = await refresh_session(db, refresh_token)
    return _session_response(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout_route(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    authorization: Annotated[str | None, Header()] = None,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    """Revoke this session and clear the cookie.

    Idempotent: unknown or already-revoked tokens succeed silently, which is also why it
    takes no ``Idempotency-Key``.
    """
    access: str | None = None
    if authorization:
        scheme, _, tok = authorization.partition(" ")
        if scheme == "Bearer" and tok.strip():
            access = tok.strip()
    await logout(db, refresh_token or "", access_token=access)
    clear_refresh_cookie(response, settings=get_settings())


def _dev_login_gate() -> None:
    """404 unless ``dev_login_active``.

    A dependency, not a check in the handler: dependencies run before the body is
    validated, so prod answers ``{}`` with the same 404 as any unknown path rather than a
    422 that would show the route exists.
    """
    if not get_settings().dev_login_active:
        raise NotFoundError("not found")


@router.post(
    "/dev-login",
    response_model=TokensOut,
    include_in_schema=False,
    dependencies=[Depends(_dev_login_gate)],
)
async def dev_login_route(
    body: DevLoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Local work and e2e only; 404 unless ``dev_login_active`` (never in prod)."""
    await guard_ip(request, bucket="dev-login")
    tokens = await dev_login(
        db, steam_id=body.steam_id, display_name=body.display_name, admin=body.admin
    )
    return _session_response(response, tokens)
