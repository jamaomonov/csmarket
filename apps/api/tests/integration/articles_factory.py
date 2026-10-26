"""Fixtures for the articles tests: real image headers and ready-made articles."""

from __future__ import annotations

import struct
import zlib
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from csmarket.modules.articles.models import Article
    from sqlalchemy.ext.asyncio import AsyncSession


def png(width: int = 640, height: int = 360, salt: bytes = b"") -> bytes:
    """A PNG whose header reads ``width`` × ``height``; ``salt`` makes the bytes unique."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
        + salt
    )


ADMIN = "/api/v1/admin/articles"


def tr(
    title: str = "Топ бюджетных ножей", *, ready: bool = True, body: str = "Текст."
) -> dict[str, object]:
    """A translation body for the admin API."""
    return {
        "title": title,
        "description": "Описание",
        "cover_alt": "Обложка",
        "body": body,
        "ready": ready,
    }


async def make_article(
    db: AsyncSession,
    *,
    slug: str,
    section: str = "tops",
    status: str = "published",
    translations: dict[str, dict[str, object]] | None = None,
    published_at: datetime | None = None,
) -> Article:
    """A committed article with a cover; ``translations`` default to one ready ru text."""
    from datetime import UTC
    from hashlib import sha256

    from csmarket.modules.articles.models import Article, ArticleMedia, ArticleTranslation

    data = png(salt=slug.encode())
    media = ArticleMedia(
        hash=sha256(data).hexdigest(),
        content_type="image/png",
        width=640,
        height=360,
        size=len(data),
        data=data,
    )
    db.add(media)
    await db.flush()
    article = Article(
        section=section,
        slug=slug,
        status=status,
        cover_media_id=media.id,
        published_at=published_at or (datetime.now(UTC) if status == "published" else None),
    )
    db.add(article)
    await db.flush()
    for locale, values in (translations or {"ru": tr()}).items():
        db.add(ArticleTranslation(article_id=article.id, locale=locale, **values))
    await db.commit()
    return article
