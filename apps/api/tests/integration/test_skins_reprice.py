"""Stored sell prices (``reprice_rows``), the discount and the rules loader."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.skins.models import SkinItem, SkinPricingRules
from csmarket.modules.skins.naming import slug_for
from csmarket.modules.skins.pricing import DEFAULT_RULES, PricingRules
from csmarket.modules.skins.repricing import reprice_rows
from csmarket.modules.skins.settings import (
    load_rules,
    publish_rules,
    save_rules,
)
from csmarket.modules.users.service import upsert_user_by_steam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _item(name: str, cost: int | None, **kw: object) -> SkinItem:
    fields: dict[str, object] = {
        "id": new_id(),
        "market_hash_name": name,
        "phase": "",
        "slug": slug_for(name, ""),
        "category": "rifles",
        "weapon": "AK-47",
        "search_text": name.lower(),
        "min_auto_units": cost,
        "count_auto": 10,
        "active": True,
    }
    return SkinItem(**(fields | kw))


async def _active_item(
    db: AsyncSession, name: str = "AK-47 | Redline (Field-Tested)", **kw: object
) -> SkinItem:
    cost = kw.pop("min_auto_units", 27867)
    assert cost is None or isinstance(cost, int)
    item = _item(name, cost, **kw)
    db.add(item)
    await db.commit()
    return item


async def test_reprice_writes_sell_price_and_discount(db_session: AsyncSession) -> None:
    item = await _active_item(db_session, steam_price_units=43794)
    assert await reprice_rows(db_session, DEFAULT_RULES) == 1
    await db_session.commit()
    await db_session.refresh(item)
    # liquidity 4..19 -> 0 pp: 27.867 + 3 % expenses 0.83601 + brackets 1.80069 = 30.5037 -> 30.51
    assert item.sell_price_usd == Decimal("30.51")
    assert item.discount_percent == 30  # (43.794 - 30.51) / 43.794 = 30.3 %
    # Idempotent: a second pass finds nothing to write.
    assert await reprice_rows(db_session, DEFAULT_RULES) == 0


async def test_hidden_rows_are_repriced_too(db_session: AsyncSession) -> None:
    item = await _active_item(db_session, min_auto_units=10_000, hidden=True)
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.refresh(item)
    assert item.sell_price_usd is not None


async def test_inactive_and_priceless_rows_get_no_price(db_session: AsyncSession) -> None:
    stale = await _active_item(
        db_session, "A | Old (Field-Tested)", sell_price_usd=Decimal("5.00"), discount_percent=3
    )
    stale.active = False
    priceless = await _active_item(
        db_session, "A | None (Field-Tested)", min_auto_units=None, sell_price_usd=Decimal("1.00")
    )
    await db_session.commit()
    assert await reprice_rows(db_session, DEFAULT_RULES) == 2
    await db_session.refresh(stale)
    await db_session.refresh(priceless)
    assert (stale.sell_price_usd, stale.discount_percent) == (None, None)
    assert priceless.sell_price_usd is None


async def test_ids_limit_the_pass(db_session: AsyncSession) -> None:
    one = await _active_item(db_session, "A | One (Field-Tested)")
    two = await _active_item(db_session, "A | Two (Field-Tested)")
    assert await reprice_rows(db_session, DEFAULT_RULES, ids=[one.id]) == 1
    await db_session.refresh(one)
    await db_session.refresh(two)
    assert one.sell_price_usd is not None
    assert two.sell_price_usd is None


async def test_rules_change_reprices_every_row(db_session: AsyncSession) -> None:
    await _active_item(db_session, "A | One (Field-Tested)", min_auto_units=9500)
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    before = (await db_session.execute(select(SkinItem.sell_price_usd))).scalar_one()
    richer = DEFAULT_RULES.model_copy(update={"expenses_percent": Decimal("20")})
    assert await reprice_rows(db_session, richer) == 1
    await db_session.commit()
    after = (await db_session.execute(select(SkinItem.sell_price_usd))).scalar_one()
    assert before is not None
    assert after is not None
    assert after > before


async def test_load_rules_defaults_then_caches(db_session: AsyncSession) -> None:
    assert await load_rules(db_session) == DEFAULT_RULES
    assert await get_redis().get("skins:pricing") is not None
    assert 0 < await get_redis().ttl("skins:pricing") <= 3600


async def test_save_publish_load_round_trip(db_session: AsyncSession) -> None:
    user = await upsert_user_by_steam(
        db_session, steam_id="76561198000000077", display_name=None, avatar_url=None
    )
    richer = DEFAULT_RULES.model_copy(update={"expenses_percent": Decimal("4")})
    await save_rules(db_session, rules=richer, admin_id=user.id)
    await db_session.commit()
    # Postgres is the source of truth: a fresh read ignores a stale Redis copy.
    await get_redis().set("skins:pricing", DEFAULT_RULES.model_dump_json())
    assert await load_rules(db_session, fresh=True) == richer
    await publish_rules(richer)
    assert await load_rules(db_session) == richer
    # A second save updates row 1 in place.
    await save_rules(db_session, rules=DEFAULT_RULES, admin_id=user.id)
    await db_session.commit()
    row = await db_session.get(SkinPricingRules, 1)
    assert row is not None
    assert row.updated_by == user.id
    assert PricingRules.model_validate(row.rules) == DEFAULT_RULES


async def test_garbage_in_redis_or_the_row_falls_back(db_session: AsyncSession) -> None:
    await get_redis().set("skins:pricing", "{not json")
    assert await load_rules(db_session) == DEFAULT_RULES
    await get_redis().delete("skins:pricing")
    db_session.add(SkinPricingRules(id=1, rules={"retail": []}))
    await db_session.commit()
    assert await load_rules(db_session) == DEFAULT_RULES
