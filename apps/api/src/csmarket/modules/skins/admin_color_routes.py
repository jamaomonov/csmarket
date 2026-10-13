"""``PUT /api/v1/admin/skins/items/{slug}/colors`` — an item's colours by hand (spec 2026-10-14).

Wears of one skin share one picture, so a choice is written to every row showing that picture
(the item alone when it has none) and marked manual: the ``skins.colors`` job leaves it be.
``null`` gives them back to the job, which reads the picture again on its next tick. Audited
``skins.item.colors``; an ``Idempotency-Key`` replays like the other admin item writes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.errors import NotFoundError
from csmarket.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import record, require_admin
from csmarket.modules.skins.admin_routes import item_out
from csmarket.modules.skins.admin_schemas import AdminSkinColorsIn, AdminSkinItemOut
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User

router = APIRouter(prefix="/admin/skins", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
IdemKey = Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)]


@router.put(
    "/items/{slug}/colors", response_model=AdminSkinItemOut, summary="Set an item's colours"
)
async def put_colors(
    slug: str, body: AdminSkinColorsIn, user: Admin, db: Db, idempotency_key: IdemKey = None
) -> AdminSkinItemOut:
    """Set the colours of the item and its wears, or give them back to the job (``null``)."""
    key = normalize_idempotency_key(idempotency_key)
    item = (await db.execute(select(SkinItem).where(SkinItem.slug == slug))).scalar_one_or_none()
    if item is None:
        raise NotFoundError("skin not found")
    scope = f"admin.skins.colors:{item.id}"
    if key is not None and (hit := await load_replay(db, scope=scope, idempotency_key=key)):
        return AdminSkinItemOut.model_validate(hit.body)
    same = (
        SkinItem.image_url == item.image_url
        if item.image_url is not None
        else SkinItem.id == item.id
    )
    manual = body.colors is not None
    values = (
        {"colors": list(body.colors or []), "colors_manual": True}
        if manual
        else {"colors_manual": False, "colors_image": None}
    )
    await db.execute(update(SkinItem).where(same).values(**values, updated_at=now()))
    await db.refresh(item)
    await record(
        db,
        actor_id=user.id,
        action="skins.item.colors",
        target_type="skin_item",
        target_id=item.id,
        payload={
            "slug": item.slug,
            "colors": ",".join(body.colors) if body.colors is not None else "auto",
        },
    )
    out = item_out(item)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    await db.commit()
    await bump_catalog_version(get_redis())
    return out
