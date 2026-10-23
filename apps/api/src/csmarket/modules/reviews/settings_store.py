"""Row 1 of ``review_settings``: whether the public page shows reviews (default off).

No cache: one primary-key read per public request; an admin's switch shows at once (the
storefront's own data cache keeps a page for up to 5 minutes).
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.modules.reviews.models import ReviewSettingsRow


async def settings_row(db: AsyncSession) -> ReviewSettingsRow | None:
    """Row 1, read fresh."""
    return await db.get(ReviewSettingsRow, 1, populate_existing=True)


async def reviews_public(db: AsyncSession) -> bool:
    """The switch; off when the row is missing."""
    row = await settings_row(db)
    return row is not None and row.reviews_public


async def save_reviews_public(db: AsyncSession, *, value: bool, admin_id: str) -> ReviewSettingsRow:
    """Upsert row 1 in one statement (two first saves at once both land); never commits."""
    values = {"reviews_public": value, "updated_by": admin_id, "updated_at": now()}
    stmt = insert(ReviewSettingsRow).values(id=1, **values)
    await db.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=values))
    row = await settings_row(db)
    assert row is not None  # just written in this transaction
    return row


__all__ = ["reviews_public", "save_reviews_public", "settings_row"]
