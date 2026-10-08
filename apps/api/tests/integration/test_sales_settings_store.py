"""``sale_settings`` row 1: the default until saved; an unreadable row reads as the default."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.sales.models import SaleSettingsRow
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS
from csmarket.modules.sales.settings_store import read_sale_settings, save_sale_settings
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio


async def test_the_default_until_saved(db_session: AsyncSession) -> None:
    assert await read_sale_settings(db_session) == DEFAULT_SALE_SETTINGS


async def test_a_save_is_read_back_with_its_author(db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    doc = DEFAULT_SALE_SETTINGS.model_copy(update={"enabled": True, "card_min_uzs": 50_000})
    await save_sale_settings(db_session, settings=doc, admin_id=admin.id)
    await db_session.commit()
    assert await read_sale_settings(db_session) == doc
    row = await db_session.get(SaleSettingsRow, 1)
    assert row is not None
    assert row.updated_by == admin.id
    again = doc.model_copy(update={"balance_bonus_pct": Decimal("3")})
    await save_sale_settings(db_session, settings=again, admin_id=admin.id)
    await db_session.commit()
    assert (await read_sale_settings(db_session)).balance_bonus_pct == Decimal("3")


async def test_an_unreadable_row_reads_as_the_switched_off_default(
    db_session: AsyncSession,
) -> None:
    db_session.add(SaleSettingsRow(id=1, settings={"enabled": True, "margin": "nonsense"}))
    await db_session.commit()
    assert await read_sale_settings(db_session) == DEFAULT_SALE_SETTINGS
