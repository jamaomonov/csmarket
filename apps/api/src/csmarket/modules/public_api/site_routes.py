"""``/api/v1/me/api-key`` -- the customer's API key (signed-in user, not key auth)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.idempotency import load_replay, require_idempotency_key, save_replay
from csmarket.modules.auth.api import current_user
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.public_api.schemas import ApiKeyIssuedOut, ApiKeyOut, IpAllowlistIn
from csmarket.modules.users.api import User

router = APIRouter(prefix="/me/api-key", tags=["api-key"])

_ISSUE_SCOPE = "public_api.issue_key"
_REVOKE_SCOPE = "public_api.revoke_key"
_ALLOWLIST_SCOPE = "public_api.ip_allowlist"


def _out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        pricing_profile=key.pricing_profile,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        ip_allowlist=list(key.ip_allowlist),
    )


@router.get("", response_model=ApiKeyOut | None, summary="My API key")
async def get_key(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ApiKeyOut | None:
    """The live key's facts, or ``null`` when none. The token is never returned."""
    key = await keys.live_key(db, user.id)
    if key is None:
        return None
    return _out(key)


@router.post("", response_model=ApiKeyIssuedOut, status_code=201, summary="Issue an API key")
async def issue_key(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApiKeyIssuedOut:
    """Issue a key, revoking the live one; the token is shown once.

    The token is never stored, so a replayed ``Idempotency-Key`` answers 409
    ``key_already_issued`` with the ``key_id`` instead of the token again.
    """
    idem = require_idempotency_key(idempotency_key)
    scoped = f"{user.id}:{idem}"
    replay = await load_replay(db, scope=_ISSUE_SCOPE, idempotency_key=scoped)
    if replay is not None:
        key_id = (replay.body or {}).get("key_id")
        raise ConflictError(
            "this Idempotency-Key already issued a key", code="key_already_issued", key_id=key_id
        )
    key, token = await keys.issue(db, user=user)
    await save_replay(
        db, scope=_ISSUE_SCOPE, idempotency_key=scoped, body={"key_id": key.id}, status_code=201
    )
    await db.commit()
    return ApiKeyIssuedOut(
        id=key.id, token=token, pricing_profile=key.pricing_profile, created_at=key.created_at
    )


@router.delete("", status_code=204, summary="Revoke my API key")
async def revoke_key(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    """Revoke the live key; 404 ``api_key_missing`` when there is none. A replay answers 204."""
    idem = require_idempotency_key(idempotency_key)
    scoped = f"{user.id}:{idem}"
    if await load_replay(db, scope=_REVOKE_SCOPE, idempotency_key=scoped) is None:
        await keys.revoke(db, user=user)
        await save_replay(
            db, scope=_REVOKE_SCOPE, idempotency_key=scoped, body=None, status_code=204
        )
        await db.commit()
    return Response(status_code=204)


@router.put("/ip-allowlist", response_model=ApiKeyOut, summary="Set my API key's IP allow-list")
async def set_ip_allowlist(
    body: IpAllowlistIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApiKeyOut:
    """Replace the live key's allow-list; ``[]`` lets any address in.

    It governs the public API only, never this route, so a user can always fix a wrong list.
    A replay answers the key as it stands. 404 ``api_key_missing`` without a live key; 422
    ``ip_allowlist_invalid`` with the ``index`` of the bad entry.
    """
    idem = require_idempotency_key(idempotency_key)
    scoped = f"{user.id}:{idem}"
    if await load_replay(db, scope=_ALLOWLIST_SCOPE, idempotency_key=scoped) is not None:
        key = await keys.live_key(db, user.id)
        if key is None:
            raise NotFoundError("no API key", code="api_key_missing")
        return _out(key)
    key = await keys.set_ip_allowlist(db, user=user, entries=body.ip_allowlist)
    await save_replay(
        db, scope=_ALLOWLIST_SCOPE, idempotency_key=scoped, body=None, status_code=200
    )
    await db.commit()
    return _out(key)
