"""The skins tables exist after migration and enforce (name, phase) uniqueness."""

from __future__ import annotations

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem, SkinPricingRules
from csmarket.modules.skins.slugs import existing_slugs
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _item(name: str, phase: str = "", slug: str | None = None) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase=phase,
        slug=slug or name.lower().replace(" ", "-"),
        category="rifles",
        search_text=name.lower(),
    )


async def test_item_round_trips(db_session: AsyncSession) -> None:
    db_session.add(_item("AK-47 | Redline (Field-Tested)"))
    await db_session.commit()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    assert row is not None
    assert row.phase == ""
    assert row.active is False
    assert row.count_auto == 0
    assert row.cheapest_auto == []


async def test_same_name_and_phase_is_refused(db_session: AsyncSession) -> None:
    db_session.add(_item("★ Karambit | Doppler (Factory New)", "Phase 2", "k-p2"))
    await db_session.commit()
    db_session.add(_item("★ Karambit | Doppler (Factory New)", "Phase 2", "k-p2-dup"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_same_name_different_phase_is_two_rows(db_session: AsyncSession) -> None:
    db_session.add(_item("★ Karambit | Doppler (Factory New)", "Phase 1", "k-p1"))
    db_session.add(_item("★ Karambit | Doppler (Factory New)", "Phase 3", "k-p3"))
    await db_session.commit()


async def test_pricing_rules_is_a_singleton(db_session: AsyncSession) -> None:
    db_session.add(SkinPricingRules(id=2, rules={}))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_hidden_defaults_to_false(db_session: AsyncSession) -> None:
    item = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug="ak-47-redline-field-tested",
        category="rifles",
        search_text="ak 47 redline field tested",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.hidden is False
    assert item.active is False
    assert item.cheapest_auto == []


async def test_existing_slugs_maps_every_stored_row(db_session: AsyncSession) -> None:
    db_session.add(_item("AK-47 | Redline (Field-Tested)", slug="ak"))
    db_session.add(_item("★ Karambit | Doppler (Factory New)", "Phase 1", "k-p1"))
    await db_session.commit()
    assert await existing_slugs(db_session) == {
        ("AK-47 | Redline (Field-Tested)", ""): "ak",
        ("★ Karambit | Doppler (Factory New)", "Phase 1"): "k-p1",
    }
