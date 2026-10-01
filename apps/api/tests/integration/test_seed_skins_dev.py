"""The dev seed leaves a browsable, priced catalogue and can be run again."""

from __future__ import annotations

import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.skins.cachekeys import catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.naming import canonical_name
from csmarket.scripts import seed_skins_dev
from csmarket.scripts.seed_skins_dev import seed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


async def test_seed_makes_a_browsable_priced_catalogue(db_engine) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    made = await seed(factory, get_redis())
    assert made >= 40
    async with factory() as db:
        active = await db.scalar(select(func.count()).select_from(SkinItem).where(SkinItem.active))
        unpriced = await db.scalar(
            select(func.count())
            .select_from(SkinItem)
            .where(SkinItem.active, SkinItem.sell_price_usd.is_(None))
        )
        cats = set(
            (
                await db.execute(select(SkinItem.category).where(SkinItem.active).distinct())
            ).scalars()
        )
        phased = set(
            (
                await db.execute(
                    select(SkinItem.phase).where(SkinItem.active, SkinItem.phase != "")
                )
            ).scalars()
        )
        assert active == made
        assert unpriced == 0
        assert {"rifles", "pistols", "smgs", "heavy", "knives", "gloves", "agents", "cases"} <= cats
        assert {"Phase 1", "Phase 2"} <= phased  # Doppler phases survive the Waxpeer spelling
        rate = await current_usd_uzs(db, get_redis(), max_age_days=7)
        assert rate is not None
        assert rate.source == "dev"
    assert await catalog_version(get_redis()) > 0


async def test_seed_is_repeatable(db_engine) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    first = await seed(factory, get_redis())
    async with factory() as db:
        prices = dict((await db.execute(select(SkinItem.slug, SkinItem.sell_price_usd))).all())
        rates = await db.scalar(select(func.count()).select_from(FxSnapshot))
    assert await seed(factory, get_redis()) == first
    async with factory() as db:
        after = dict((await db.execute(select(SkinItem.slug, SkinItem.sell_price_usd))).all())
        assert after == prices
        assert await db.scalar(select(func.count()).select_from(FxSnapshot)) == rates == 1


async def test_fake_listing_names_fold_back_to_the_catalogue_key() -> None:
    assert canonical_name(
        seed_skins_dev.listing_name("★ Karambit | Doppler (Factory New)", "Phase 2")
    ) == (
        "★ Karambit | Doppler (Factory New)",
        "Phase 2",
    )
    assert seed_skins_dev.listing_name("AK-47 | Redline (Field-Tested)", "") == (
        "AK-47 | Redline (Field-Tested)"
    )


def test_refuses_in_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Prod:
        is_prod = True

    monkeypatch.setattr(seed_skins_dev, "get_settings", _Prod)
    assert seed_skins_dev.main() == 2
    assert "refusing to seed in production" in capsys.readouterr().err
