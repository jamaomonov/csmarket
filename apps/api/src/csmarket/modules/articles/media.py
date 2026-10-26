"""Article images: stored once per content hash, read back by hash and extension (ADR-0025).

JPEG, PNG or WebP by their bytes (:func:`csmarket.core.uploads.sniff`), at most
:data:`MAX_BYTES`, with a readable pixel size; anything else is refused before it is stored.
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from csmarket.core.errors import NotFoundError, ValidationError
from csmarket.core.uploads import image_size, sniff
from csmarket.modules.articles.models import ArticleMedia
from csmarket.modules.articles.schemas import MediaOut

#: One image's size, bytes (5 MB).
MAX_BYTES = 5 * 1024 * 1024
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_HASH = re.compile(r"[0-9a-f]{64}")


def media_out(media: ArticleMedia) -> MediaOut:
    """The image as the API shows it."""
    return MediaOut(
        hash=media.hash,
        url=f"/media/{media.hash}.{EXT[media.content_type]}",
        width=media.width,
        height=media.height,
        content_type=media.content_type,
    )


async def store_media(db: AsyncSession, data: bytes, *, by: str) -> ArticleMedia:
    """Keep ``data`` as an image (or return the row already holding these bytes).

    Raises:
        ValidationError: ``media_empty``, ``media_too_large`` or ``media_type``.
    """
    if not data:
        raise ValidationError("the file is empty", code="media_empty")
    if len(data) > MAX_BYTES:
        raise ValidationError("the file is larger than 5 MB", code="media_too_large")
    content_type = sniff(data)
    size = image_size(data, content_type) if content_type in EXT else None
    if content_type is None or size is None:
        raise ValidationError("only JPG, PNG or WebP images", code="media_type")
    digest = hashlib.sha256(data).hexdigest()
    found = await db.scalar(select(ArticleMedia).where(ArticleMedia.hash == digest))
    if found is not None:
        return found
    media = ArticleMedia(
        hash=digest,
        content_type=content_type,
        width=size[0],
        height=size[1],
        size=len(data),
        data=data,
        uploaded_by=by,
    )
    db.add(media)
    await db.flush()
    return media


async def read_media(db: AsyncSession, digest: str, ext: str) -> ArticleMedia:
    """The image with these bytes and this extension, its bytes loaded.

    Raises:
        NotFoundError: no such image, or the extension is not its type's.
    """
    if not _HASH.fullmatch(digest) or ext not in EXT.values():
        raise NotFoundError("no such image", code="media_not_found")
    media = await db.scalar(
        select(ArticleMedia).where(ArticleMedia.hash == digest).options(undefer(ArticleMedia.data))
    )
    if media is None or EXT[media.content_type] != ext:
        raise NotFoundError("no such image", code="media_not_found")
    return media
