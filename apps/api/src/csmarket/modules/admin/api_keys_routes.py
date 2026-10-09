"""``/api/v1/admin/api-keys`` -- the partners' keys, what they sold, the tariff, revoke.

Admin only. Writes need an ``Idempotency-Key`` and follow the users order: change -> audit ->
replay row -> commit. The token is never readable (only its hash exists).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin import api_keys_service as svc
from csmarket.modules.admin.api_keys_schemas import (
    AdminApiKeyCard,
    AdminApiKeysOut,
    AdminLimitsIn,
    AdminRevokeKeyIn,
    AdminTariffIn,
)
from csmarket.modules.admin.deps import require_admin, required_key
from csmarket.modules.admin.filters import text_filter
from csmarket.modules.public_api.api import ApiKey
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/api-keys", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


async def _finish(
    db: AsyncSession, key: ApiKey, *, scope: str, idem: str, request: dict[str, Any]
) -> AdminApiKeyCard:
    card = await svc.key_card(db, key)
    await svc.remember(
        db, scope=scope, key=idem, request=request, response=card.model_dump(mode="json")
    )
    await db.commit()
    return card


@router.get("", response_model=AdminApiKeysOut, summary="API keys with their sales")
async def list_keys(
    db: Db,
    q: Annotated[str | None, text_filter(80)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminApiKeysOut:
    """Live keys first, newest first; ``q`` = part of the owner's display name."""
    items, next_cursor = await svc.list_keys(db, q=q, cursor=cursor, limit=limit)
    return AdminApiKeysOut(items=items, next_cursor=next_cursor)


@router.get("/{key_id}", response_model=AdminApiKeyCard, summary="An API key's card")
async def get_key_card(key_id: str, db: Db) -> AdminApiKeyCard:
    """The key, its latest 20 orders and the owner's webhook host."""
    return await svc.key_card(db, await svc.get_key(db, key_id))


@router.put("/{key_id}/tariff", response_model=AdminApiKeyCard, summary="Switch the tariff")
async def put_tariff(
    key_id: str, body: AdminTariffIn, admin: Admin, db: Db, idem: Key
) -> AdminApiKeyCard:
    """``retail`` or ``cost`` for the next orders; 409 ``api_key_revoked`` on a dead key."""
    key = await svc.get_key(db, key_id, lock=True)
    request = {"key_id": key.id, "pricing_profile": body.pricing_profile, "reason": body.reason}
    scope = "admin.api_keys.tariff"
    if (hit := await svc.replayed(db, scope=scope, key=idem, request=request)) is not None:
        return AdminApiKeyCard.model_validate(hit)
    await svc.set_tariff(db, admin=admin, key=key, profile=body.pricing_profile, reason=body.reason)
    return await _finish(db, key, scope=scope, idem=idem, request=request)


@router.put("/{key_id}/limits", response_model=AdminApiKeyCard, summary="Set the key's limits")
async def put_limits(
    key_id: str, body: AdminLimitsIn, admin: Admin, db: Db, idem: Key
) -> AdminApiKeyCard:
    """Per-minute limits (1..10000, ``null`` = the default); 409 ``api_key_revoked`` /
    ``limits_unchanged``.
    """
    key = await svc.get_key(db, key_id, lock=True)
    values = body.model_dump(exclude={"reason"})
    request = {"key_id": key.id, **values, "reason": body.reason}
    scope = "admin.api_keys.limits"
    if (hit := await svc.replayed(db, scope=scope, key=idem, request=request)) is not None:
        return AdminApiKeyCard.model_validate(hit)
    await svc.set_limits(db, admin=admin, key=key, values=values, reason=body.reason)
    return await _finish(db, key, scope=scope, idem=idem, request=request)


@router.post("/{key_id}/revoke", response_model=AdminApiKeyCard, summary="Revoke a key")
async def post_revoke(
    key_id: str, body: AdminRevokeKeyIn, admin: Admin, db: Db, idem: Key
) -> AdminApiKeyCard:
    """End the key now; its next public request is 401. 409 when already revoked."""
    key = await svc.get_key(db, key_id, lock=True)
    request = {"key_id": key.id, "reason": body.reason}
    scope = "admin.api_keys.revoke"
    if (hit := await svc.replayed(db, scope=scope, key=idem, request=request)) is not None:
        return AdminApiKeyCard.model_validate(hit)
    await svc.revoke(db, admin=admin, key=key, reason=body.reason)
    return await _finish(db, key, scope=scope, idem=idem, request=request)


__all__ = ["router"]
