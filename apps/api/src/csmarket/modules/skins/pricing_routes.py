"""``/api/v1/admin/skins/pricing`` and ``/items/{slug}/pricing`` — the pricing editor (M4b R8).

Admin only. Writes need an ``Idempotency-Key`` (``admin.api.required_key``; a key reused for
another body is 409 ``idempotency_mismatch``), record one audit row, commit, and only then
publish the rules to Redis and bump the catalogue version. Logic: ``pricing_admin``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import NotFoundError
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.skins.admin_routes import item_out
from csmarket.modules.skins.admin_schemas import (
    AdminSkinItemOut,
    ItemPricingIn,
    PreviewIn,
    PreviewOut,
    PricingOut,
)
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.pricing import PricingRules
from csmarket.modules.skins.pricing_admin import (
    override_item,
    preview,
    pricing_view,
    save_pricing,
)
from csmarket.modules.skins.settings import publish_rules
from csmarket.modules.users.models import User

router = APIRouter(prefix="/admin/skins", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@router.get("/pricing", response_model=PricingOut, summary="The pricing rules")
async def get_pricing(db: Db) -> PricingOut:
    """The saved document, who saved it and when, item counts and the rate."""
    return await pricing_view(db)


@router.put("/pricing", response_model=PricingOut, summary="Save the pricing rules")
async def put_pricing(body: PricingRules, user: Admin, db: Db, key: Key) -> PricingOut:
    """Replace the document and reprice every item in one transaction; publish after commit."""
    scope, request = "admin.skins.pricing", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PricingOut.model_validate(hit)
    await save_pricing(db, rules=body, admin=user)
    out = await pricing_view(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    await publish_rules(body)
    await bump_catalog_version(get_redis())
    return out


@router.post("/pricing/preview", response_model=PreviewOut, summary="Preview a price")
async def post_preview(body: PreviewIn, db: Db) -> PreviewOut:
    """Price an item or a made-up one under the saved or a draft document.

    Keyless: it writes nothing — no row, no cache, no audit — so there is nothing to replay.
    """
    return await preview(db, body)


@router.put(
    "/items/{slug}/pricing", response_model=AdminSkinItemOut, summary="Override one item's price"
)
async def put_item_pricing(
    slug: str, body: ItemPricingIn, user: Admin, db: Db, key: Key
) -> AdminSkinItemOut:
    """Set or clear the item's margin override and pinned price, and reprice it."""
    item = await db.scalar(select(SkinItem).where(SkinItem.slug == slug))
    if item is None:
        raise NotFoundError("skin not found")
    # Scoped by id, not slug: a slug may run to 255 characters, the scope column to 128.
    scope, request = f"admin.skins.item.pricing:{item.id}", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminSkinItemOut.model_validate(hit)
    await override_item(
        db,
        item=item,
        margin_override_pp=body.margin_override_pp,
        fixed_price_usd=body.fixed_price_usd,
        admin=user,
    )
    out = item_out(item)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    await bump_catalog_version(get_redis())
    return out


__all__ = ["router"]
