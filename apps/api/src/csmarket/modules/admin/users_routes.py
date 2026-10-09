"""``/api/v1/admin/users`` — find users, open a card, ban/unban, adjust a balance.

Admin only (``require_admin`` on the whole router). Every write requires an
``Idempotency-Key`` of 16..160 characters and follows the ``skins.admin_routes`` order:
change → ``audit.record`` → replay row → commit. A replayed key returns the stored card and
writes nothing; the same key on another body or another user is a 409.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin import users_service as svc
from csmarket.modules.admin.deps import require_admin, required_key
from csmarket.modules.admin.filters import text_filter
from csmarket.modules.admin.users_schemas import (
    AdminAdjustIn,
    AdminAdjustUsdIn,
    AdminReasonIn,
    AdminUsdSwitchIn,
    AdminUserCard,
    AdminUsersOut,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/users", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


async def _finish(
    db: AsyncSession, user: User, *, scope: str, key: str, request: dict[str, Any]
) -> AdminUserCard:
    """Build the card, store it as the replay, commit (after the change and its audit)."""
    card = await svc.user_card(db, user)
    await svc.remember(
        db, scope=scope, key=key, request=request, response=card.model_dump(mode="json")
    )
    await db.commit()
    return card


@router.get("", response_model=AdminUsersOut, summary="Find users")
async def list_users(
    db: Db,
    q: Annotated[str | None, text_filter(80)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminUsersOut:
    """Newest first; ``q`` = part of the display name or an exact 17-digit Steam ID."""
    items, next_cursor = await svc.list_users(db, q=q, cursor=cursor, limit=limit)
    return AdminUsersOut(items=items, next_cursor=next_cursor)


@router.get("/{user_id}", response_model=AdminUserCard, summary="A user's card")
async def get_user_card(user_id: str, db: Db) -> AdminUserCard:
    """Profile (trade link masked), balance, the latest 20 ledger lines and top-ups."""
    return await svc.user_card(db, await svc.get_user(db, user_id))


@router.post("/{user_id}/ban", response_model=AdminUserCard, summary="Ban a user")
async def ban_user(
    user_id: str, body: AdminReasonIn, admin: Admin, db: Db, key: Key
) -> AdminUserCard:
    """Suspend the account and end every session; 409 for oneself, an admin, a banned one."""
    user = await svc.get_user(db, user_id, lock=True)
    request = {"user_id": user.id, "reason": body.reason}
    scope = "admin.users.ban"
    if (hit := await svc.replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminUserCard.model_validate(hit)
    await svc.ban(db, admin=admin, user=user, reason=body.reason)
    return await _finish(db, user, scope=scope, key=key, request=request)


@router.post("/{user_id}/unban", response_model=AdminUserCard, summary="Lift a ban")
async def unban_user(
    user_id: str, body: AdminReasonIn, admin: Admin, db: Db, key: Key
) -> AdminUserCard:
    """Clear the ban; the user signs in again. 409 when the account is not banned."""
    user = await svc.get_user(db, user_id, lock=True)
    request = {"user_id": user.id, "reason": body.reason}
    scope = "admin.users.unban"
    if (hit := await svc.replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminUserCard.model_validate(hit)
    await svc.unban(db, admin=admin, user=user, reason=body.reason)
    return await _finish(db, user, scope=scope, key=key, request=request)


@router.post("/{user_id}/wallet/adjust", response_model=AdminUserCard, summary="Adjust a balance")
async def adjust_balance(
    user_id: str, body: AdminAdjustIn, admin: Admin, db: Db, key: Key
) -> AdminUserCard:
    """Credit (> 0) or claw back (< 0); a clawback below zero is 409 ``balance_too_low``."""
    user = await svc.get_user(db, user_id, lock=True)
    request = {"user_id": user.id, "amount_uzs": body.amount_uzs, "reason": body.reason}
    scope = "admin.users.adjust"
    if (hit := await svc.replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminUserCard.model_validate(hit)
    await svc.adjust(
        db, admin=admin, user=user, amount=body.amount_uzs, reason=body.reason, key=key
    )
    return await _finish(db, user, scope=scope, key=key, request=request)


@router.post(
    "/{user_id}/wallet/adjust-usd", response_model=AdminUserCard, summary="Adjust the USD balance"
)
async def adjust_usd_balance(
    user_id: str, body: AdminAdjustUsdIn, admin: Admin, db: Db, key: Key
) -> AdminUserCard:
    """Credit (> 0) or claw back (< 0) dollars; below zero is 409 ``balance_too_low``."""
    user = await svc.get_user(db, user_id, lock=True)
    request = {"user_id": user.id, "amount_usd": body.amount_usd, "reason": body.reason}
    scope = "admin.users.adjust_usd"
    if (hit := await svc.replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminUserCard.model_validate(hit)
    await svc.adjust_usd(db, admin=admin, user=user, units=body.units, reason=body.reason, key=key)
    return await _finish(db, user, scope=scope, key=key, request=request)


@router.put("/{user_id}/usd-wallet", response_model=AdminUserCard, summary="Switch the USD wallet")
async def switch_usd_wallet(
    user_id: str, body: AdminUsdSwitchIn, admin: Admin, db: Db, key: Key
) -> AdminUserCard:
    """Turn the USD wallet on or off for a user.

    Switching off with a non-zero USD balance is allowed: the money stays on the account;
    conversion and API purchases stop until it is switched on again.
    """
    user = await svc.get_user(db, user_id, lock=True)
    request = {"user_id": user.id, "enabled": body.enabled, "reason": body.reason}
    scope = "admin.users.usd_switch"
    if (hit := await svc.replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminUserCard.model_validate(hit)
    await svc.switch_usd(db, admin=admin, user=user, enabled=body.enabled, reason=body.reason)
    return await _finish(db, user, scope=scope, key=key, request=request)


__all__ = ["router"]
