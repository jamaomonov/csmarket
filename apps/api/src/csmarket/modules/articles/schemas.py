"""Request and response shapes of ``articles`` (spec 2026-10-26-articles)."""

from __future__ import annotations

from pydantic import BaseModel


class MediaOut(BaseModel):
    """An uploaded image. ``url`` is the relative path Markdown stores (``/media/<hash>.<ext>``)."""

    hash: str
    url: str
    width: int
    height: int
    content_type: str
