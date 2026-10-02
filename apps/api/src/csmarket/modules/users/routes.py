"""``/api/v1/me`` — the signed-in account, its profile and trade link."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user, guard_ip, trade_hold_days
from csmarket.modules.skins.api import FakeTradeClient, WaxpeerClient, fake_active
from csmarket.modules.users.email_flow import verification_sent_at
from csmarket.modules.users.models import User
from csmarket.modules.users.schemas import MeOut, MePatchIn, TradeLinkIn, TradeLinkOut
from csmarket.modules.users.service import (
    record_trade_link_check,
    save_trade_link,
    update_profile,
)
from csmarket.modules.users.tradelink import (
    HoldChecker,
    TradelinkChecker,
    assert_owned,
    check_trade_link,
    parse_tradelink,
)

router = APIRouter(prefix="/me", tags=["me"])
_ADVISORY_TIMEOUT = 4.0


class _SteamHold:
    """Steam's hold check with our key; no key → no number (ruling P10)."""

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        """Days Steam would hold a trade to this link, or ``None`` without a key."""
        key = get_settings().steam_api_key
        if not key:
            return None
        return await trade_hold_days(int(steam_id), token, api_key=key)


def tradelink_checkers() -> tuple[TradelinkChecker, HoldChecker]:
    """Upstream checkers; overridden in tests via ``app.dependency_overrides``.

    Under the dev Waxpeer fake every link passes Waxpeer's half of the check.
    """
    s = get_settings()
    if fake_active(s):
        return FakeTradeClient(get_redis()), _SteamHold()
    waxpeer = WaxpeerClient(
        api_key=s.waxpeer_api_key, base_url=s.waxpeer_base_url, timeout_seconds=_ADVISORY_TIMEOUT
    )
    return waxpeer, _SteamHold()


async def _replayed(
    db: AsyncSession, scope: str, key: str | None
) -> dict[str, Any] | None:  # Any: a stored JSON response body
    if key is None:
        return None
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    return cached.body if cached is not None else None


async def _me_out(db: AsyncSession, user: User) -> MeOut:
    return MeOut.of(user, verification_sent_at=await verification_sent_at(db, user))


@router.get("", response_model=MeOut, summary="The signed-in account")
async def get_me(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> MeOut:
    """Profile, roles, trade-link state and email confirmation state."""
    return await _me_out(db, user)


@router.patch("", response_model=MeOut, summary="Edit locale or email")
async def patch_me(
    body: MePatchIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> MeOut:
    """Partial update; replays a stored response for a repeated ``Idempotency-Key``.

    A new email is unconfirmed until its link is opened: a confirmation letter is queued.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = f"users.patch_me:{user.id}"
    if (hit := await _replayed(db, scope, key)) is not None:
        return MeOut.model_validate(hit)
    await update_profile(db, user, fields=body.model_dump(exclude_unset=True))
    out = await _me_out(db, user)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@router.put("/trade-link", response_model=TradeLinkOut, summary="Save my trade link")
async def put_trade_link(
    body: TradeLinkIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> TradeLinkOut:
    """Parse, require that it is this account's own link, save. No external call."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"users.trade_link:{user.id}"
    if (hit := await _replayed(db, scope, key)) is not None:
        return TradeLinkOut.model_validate(hit)
    link = parse_tradelink(body.url)
    assert_owned(link, user.steam_id)
    await save_trade_link(db, user, link.url)
    out = TradeLinkOut.of(user)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@router.post("/trade-link/check", response_model=TradeLinkOut, summary="Check my trade link")
async def check_my_trade_link(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    checkers: Annotated[tuple[TradelinkChecker, HoldChecker], Depends(tradelink_checkers)],
) -> TradeLinkOut:
    """Advisory check of the saved link (AGENTS §11 carve-out).

    Keyless on purpose: it writes only the derived verdict of a link the user already
    saved, and re-running it is the intended use; the 10-minute cache makes a repeat free.
    """
    await guard_ip(request, bucket="trade-link-check", subject=user.id)
    if not user.trade_link:
        raise ValidationError("no trade link saved", code="trade_link_missing")
    link = parse_tradelink(user.trade_link)
    # End the read transaction before the upstream calls (AGENTS §11): the connection
    # goes back to the pool instead of idling for up to 8 s. ``expire_on_commit=False``
    # keeps ``user`` loaded; the verdict write below opens a fresh transaction.
    await db.commit()
    waxpeer, hold = checkers
    result = await check_trade_link(link, waxpeer=waxpeer, hold=hold, redis=get_redis())
    await record_trade_link_check(db, user, verdict=result.verdict, reason=result.reason)
    return TradeLinkOut.of(user)
