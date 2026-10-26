"""``/api/v1/admin/articles/media`` (upload) and ``/api/v1/media/{hash}.{ext}`` (read).

The upload is the file itself as the body, like payout receipts (ADR-0024): no multipart parser.
The edge lets 6 MB through on that path only (``infra/caddy/Caddyfile.prod``). A read is public
and immutable: the name is the bytes' SHA-256, so a URL never changes what it shows.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.uploads import read_capped_body
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.articles.media import MAX_BYTES, media_out, read_media, store_media
from csmarket.modules.articles.schemas import MediaOut
from csmarket.modules.users.api import User

admin_router = APIRouter(prefix="/admin/articles", tags=["admin"])
router = APIRouter(tags=["articles"])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]

_UPLOAD_BODY: dict[str, Any] = {  # an OpenAPI fragment
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@admin_router.post(
    "/media",
    response_model=MediaOut,
    responses={422: {"description": "`media_empty`, `media_too_large` or `media_type`"}},
    openapi_extra=_UPLOAD_BODY,
    summary="Upload an article image",
)
async def post_media(request: Request, admin: Admin, db: Db, key: Key) -> MediaOut:
    """A JPG, PNG or WebP image up to 5 MB; the same bytes again return the same image.
    Audited ``articles.media.add``."""
    scope = "admin.articles.media.add"
    data = await read_capped_body(request, max_bytes=MAX_BYTES, too_large_code="media_too_large")
    replay = {"sha256": hashlib.sha256(data).hexdigest()}
    if (hit := await replayed(db, scope=scope, key=key, request=replay)) is not None:
        return MediaOut.model_validate(hit)
    media = await store_media(db, data, by=admin.id)
    out = media_out(media)
    await record(
        db,
        actor_id=admin.id,
        action="articles.media.add",
        target_type="article_media",
        target_id=media.id,
        payload={"content_type": media.content_type, "size": media.size},
    )
    await remember(db, scope=scope, key=key, request=replay, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get(
    "/media/{digest}.{ext}",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}, "description": "The image"}, 404: {}},
    summary="An article image",
)
async def get_media(digest: str, ext: str, db: Db) -> Response:
    """The image's bytes; cached for a year by browsers and Cloudflare (the name is its hash)."""
    media = await read_media(db, digest, ext)
    return Response(
        content=media.data,
        media_type=media.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
