"""``/api/v1/admin/users`` — find users, open a card, ban/unban, adjust a balance.

Admin only (``require_admin`` on the whole router). Every write requires an
``Idempotency-Key`` of 16..160 characters and follows the ``skins.admin_routes`` order:
change → ``audit.record`` → replay row → commit. A replayed key returns the stored card and
writes nothing; the same key on another body or another user is a 409.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import ValidationError
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, normalize_idempotency_key
from csmarket.modules.admin import users_service as svc
from csmarket.modules.admin.deps import require_admin
from csmarket.modules.admin.users_schemas import (
    AdminAdjustIn,
    AdminReasonIn,
    AdminUserCard,
    AdminUsersOut,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/users", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
#: ``idempotent_responses.idempotency_key`` is ``varchar(160)``.
_MAX_KEY_LENGTH = 160


def _required_key(
    value: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> str:
    """The ``Idempotency-Key`` every admin write must carry: 16 to 160 characters."""
    key = normalize_idempotency_key(value)
    if key is None or len(key) > _MAX_KEY_LENGTH:
        raise ValidationError(
            f"{IDEMPOTENCY_HEADER} header of 16 to {_MAX_KEY_LENGTH} characters is required",
            header=IDEMPOTENCY_HEADER,
        )
    return key


Key = Annotated[str, Depends(_required_key)]


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
    q: Annotated[str | None, Query(max_length=80)] = None,
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


__all__ = ["router"]
