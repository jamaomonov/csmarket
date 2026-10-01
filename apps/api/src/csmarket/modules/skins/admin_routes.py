"""``/api/v1/admin/skins`` — catalogue status, item search, hide/unhide, search aliases.

Admin only (``require_admin`` on the whole router). Every write takes an optional
``Idempotency-Key`` (the ``users.routes`` pattern), records one ``admin_audit_log`` row,
commits, and only then bumps the catalogue version so every cached public page expires
(rulings Q4, Q5, Q13). A replayed key returns the stored response and writes nothing.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.errors import NotFoundError, ValidationError
from csmarket.core.idempotency import (
    IDEMPOTENCY_HEADER,
    CachedResponse,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import record, require_admin
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.skins.admin_schemas import (
    AdminSkinItemOut,
    AdminSkinItemPatchIn,
    AdminSkinItemsOut,
    AliasesOut,
    AliasIn,
    AliasOut,
    CatalogStatusOut,
    FxOut,
    JobOut,
)
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.images import steam_image
from csmarket.modules.skins.job_status import JOB_IMPORT, JOB_PRICE_SYNC, JobStatus, read_job
from csmarket.modules.skins.models import SkinItem, SkinSearchAlias
from csmarket.modules.skins.naming import search_text
from csmarket.modules.users.models import User

router = APIRouter(prefix="/admin/skins", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
IdemKey = Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)]

#: One word: letters (any script), digits and hyphen; ``\w`` also admits ``_``, refused
#: apart. No space: ``expand_aliases`` substitutes whole words, so a phrase never matches.
_ALIAS_RE = re.compile(r"^[\w\-]{1,64}$", re.UNICODE)


def normalize_alias(raw: str) -> str:
    """``raw`` trimmed and lower-cased, or :class:`ValidationError` when malformed."""
    alias = raw.strip().lower()
    if "_" in alias or _ALIAS_RE.fullmatch(alias) is None:
        raise ValidationError(
            "alias must be one word: 1-64 letters, digits or hyphens", code="alias_invalid"
        )
    return alias


async def _replay(db: AsyncSession, scope: str, key: str | None) -> CachedResponse | None:
    return None if key is None else await load_replay(db, scope=scope, idempotency_key=key)


async def _commit_and_bump(db: AsyncSession) -> None:
    """Commit the change with its audit row, then expire every cached public page."""
    await db.commit()
    await bump_catalog_version(get_redis())


def _job_out(job: JobStatus | None) -> JobOut | None:
    if job is None:
        return None
    return JobOut(finished_at=job.finished_at, ok=job.ok, counters=job.counters, error=job.error)


def _item_out(item: SkinItem) -> AdminSkinItemOut:
    return AdminSkinItemOut(
        slug=item.slug,
        name=item.market_hash_name,
        phase=item.phase or None,
        category=item.category,
        weapon=item.weapon,
        exterior=item.exterior,
        stattrak=item.stattrak,
        souvenir=item.souvenir,
        image_url=steam_image(item.image_url, host=get_settings().skins_image_host),
        active=item.active,
        hidden=item.hidden,
        price_usd=None if item.sell_price_usd is None else str(item.sell_price_usd),
        count=item.count_auto,
    )


def _like_escape(needle: str) -> str:
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/catalog/status", response_model=CatalogStatusOut, summary="Catalogue status")
async def catalog_status(db: Db) -> CatalogStatusOut:
    """Item counts, the newest price tick, the last job runs, the rate and the switches."""
    settings = get_settings()
    redis = get_redis()
    total, active, hidden, prices_at = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(SkinItem.active),
                func.count().filter(SkinItem.hidden),
                func.max(SkinItem.prices_updated_at),
            ).select_from(SkinItem)
        )
    ).one()
    fx = await current_usd_uzs(db, redis, max_age_days=settings.fx_max_age_days)
    return CatalogStatusOut(
        items_total=total,
        items_active=active,
        items_hidden=hidden,
        prices_updated_at=prices_at,
        import_job=_job_out(await read_job(redis, JOB_IMPORT)),
        price_sync_job=_job_out(await read_job(redis, JOB_PRICE_SYNC)),
        fx=None
        if fx is None
        else FxOut(usd_uzs=str(fx.rate), fetched_at=fx.fetched_at, source=fx.source),
        sync_enabled=settings.skins_sync_enabled,
        waxpeer_key_set=bool(settings.waxpeer_api_key),
    )


@router.get("/items", response_model=AdminSkinItemsOut, summary="Find items (hidden included)")
async def search_items(
    db: Db,
    q: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    hidden: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminSkinItemsOut:
    """Substring match on the folded name; ``hidden`` filters; most listings first."""
    stmt = select(SkinItem)
    if q is not None:
        needle = search_text(q, "")
        if not needle:
            return AdminSkinItemsOut(items=[])
        stmt = stmt.where(SkinItem.search_text.ilike(f"%{_like_escape(needle)}%", escape="\\"))
    if hidden is not None:
        stmt = stmt.where(SkinItem.hidden.is_(hidden))
    stmt = stmt.order_by(SkinItem.count_auto.desc(), SkinItem.slug).limit(limit)
    return AdminSkinItemsOut(items=[_item_out(i) for i in (await db.execute(stmt)).scalars()])


@router.patch("/items/{slug}", response_model=AdminSkinItemOut, summary="Hide or show an item")
async def patch_item(
    slug: str, body: AdminSkinItemPatchIn, user: Admin, db: Db, idempotency_key: IdemKey = None
) -> AdminSkinItemOut:
    """Hide or show an item on every public read; the price sync keeps pricing it."""
    key = normalize_idempotency_key(idempotency_key)
    item = (await db.execute(select(SkinItem).where(SkinItem.slug == slug))).scalar_one_or_none()
    if item is None:
        raise NotFoundError("skin not found")
    # Scoped by id, not slug: a slug may run to 255 characters, the scope column to 128.
    scope = f"admin.skins.item:{item.id}"
    if (hit := await _replay(db, scope, key)) is not None:
        return AdminSkinItemOut.model_validate(hit.body)
    item.hidden = body.hidden
    item.updated_at = now()
    await record(
        db,
        actor_id=user.id,
        action="skins.item.hide" if body.hidden else "skins.item.unhide",
        target_type="skin_item",
        target_id=item.id,
        payload={"slug": item.slug},
    )
    out = _item_out(item)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    await _commit_and_bump(db)
    return out


@router.get("/aliases", response_model=AliasesOut, summary="Search aliases")
async def list_aliases(db: Db) -> AliasesOut:
    """Every alias, ordered by alias."""
    rows = (await db.execute(select(SkinSearchAlias).order_by(SkinSearchAlias.alias))).scalars()
    return AliasesOut(items=[AliasOut(alias=r.alias, text=r.text) for r in rows])


@router.put("/aliases/{alias}", response_model=AliasOut, summary="Create or replace an alias")
async def put_alias(
    alias: str, body: AliasIn, user: Admin, db: Db, idempotency_key: IdemKey = None
) -> AliasOut:
    """Set what ``alias`` expands to in a search; both are stored lower-case."""
    key = normalize_idempotency_key(idempotency_key)
    name = normalize_alias(alias)
    scope = f"admin.skins.alias:{name}"
    if (hit := await _replay(db, scope, key)) is not None:
        return AliasOut.model_validate(hit.body)
    stmt = insert(SkinSearchAlias).values(alias=name, text=body.text)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=[SkinSearchAlias.alias], set_={"text": body.text})
    )
    out = AliasOut(alias=name, text=body.text)
    await record(
        db,
        actor_id=user.id,
        action="skins.alias.put",
        target_type="skin_alias",
        target_id=name,
        payload=out.model_dump(),
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    await _commit_and_bump(db)
    return out


@router.delete(
    "/aliases/{alias}", status_code=204, response_class=Response, summary="Delete an alias"
)
async def delete_alias(
    alias: str, user: Admin, db: Db, idempotency_key: IdemKey = None
) -> Response:
    """Remove an alias; 404 when there is none by that name."""
    key = normalize_idempotency_key(idempotency_key)
    name = normalize_alias(alias)
    scope = f"admin.skins.alias.delete:{name}"
    if await _replay(db, scope, key) is not None:
        return Response(status_code=204)
    row = await db.get(SkinSearchAlias, name)
    if row is None:
        raise NotFoundError("alias not found")
    await db.delete(row)
    await record(
        db,
        actor_id=user.id,
        action="skins.alias.delete",
        target_type="skin_alias",
        target_id=name,
        payload={"alias": name},
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=None, status_code=204)
    await _commit_and_bump(db)
    return Response(status_code=204)


__all__ = ["normalize_alias", "router"]
