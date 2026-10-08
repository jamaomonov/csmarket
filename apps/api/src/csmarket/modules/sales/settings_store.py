"""Row 1 of ``sale_settings``: read (the default when missing or unreadable) and saved.

No cache: one primary-key read per sell request is cheaper than keeping a copy honest. A row
that no longer parses reads as :data:`DEFAULT_SALE_SETTINGS` — switched off — with a warning,
never as a half-read document that prices sales.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.sales.models import SaleSettingsRow
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, SaleSettings

log = get_logger("csmarket.sales.settings")


async def settings_row(db: AsyncSession) -> SaleSettingsRow | None:
    """Row 1, read fresh."""
    return await db.get(SaleSettingsRow, 1, populate_existing=True)


async def read_sale_settings(db: AsyncSession) -> SaleSettings:
    """The saved document, or the switched-off default."""
    row = await settings_row(db)
    if row is None:
        return DEFAULT_SALE_SETTINGS
    try:
        return SaleSettings.model_validate(row.settings)
    except ValidationError:
        log.warning("sales.settings.row_invalid", reason="falling back to the default")
        return DEFAULT_SALE_SETTINGS


async def save_sale_settings(db: AsyncSession, *, settings: SaleSettings, admin_id: str) -> None:
    """Upsert row 1; flushes, never commits. New sales use it; existing ones keep theirs."""
    document = json.loads(settings.model_dump_json())
    row = await settings_row(db)
    if row is None:
        db.add(SaleSettingsRow(id=1, settings=document, updated_by=admin_id))
    else:
        row.settings, row.updated_by, row.updated_at = document, admin_id, now()
    await db.flush()


__all__ = ["read_sale_settings", "save_sale_settings", "settings_row"]
