"""Catalogue cards as the storefront shows them: our price in dollars and in soʻm.

Shared by the catalogue routes and by articles (``[[skin:<slug>]]`` embeds, spec 2026-10-26).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.skins.images import steam_image
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.pricing import PricingRules, to_uzs
from csmarket.modules.skins.schemas import SkinItemOut
from csmarket.modules.skins.settings import enabled_categories, load_rules


async def usd_uzs_rate(db: AsyncSession) -> Decimal | None:
    """Soʻm per dollar for display, or ``None`` (pages then show dollars — ruling Q3)."""
    settings = get_settings()
    fx = await current_usd_uzs(db, get_redis(), max_age_days=settings.fx_max_age_days)
    return None if fx is None else fx.rate


def uzs_text(usd: Decimal | None, rate: Decimal | None, rules: PricingRules) -> str | None:
    if usd is None or rate is None:
        return None
    return str(to_uzs(usd, rate, round_to=rules.uzs_round_to))


def _units_to_usd(units: int | None) -> str | None:
    return None if units is None else str(Decimal(units) / Decimal(1000))


def item_out(item: SkinItem, rules: PricingRules, rate: Decimal | None) -> SkinItemOut:
    # Stored by ``repricing.reprice_rows`` from the same ``quote()``: the card
    # shows the number every filter and sort reads.
    price = item.sell_price_usd
    discount = (
        item.discount_percent if item.discount_percent and item.discount_percent > 0 else None
    )
    return SkinItemOut(
        slug=item.slug,
        name=item.market_hash_name,
        phase=item.phase or None,
        category=item.category,
        weapon=item.weapon,
        skin=item.skin,
        exterior=item.exterior,
        stattrak=item.stattrak,
        souvenir=item.souvenir,
        rarity=item.rarity,
        rarity_color=item.rarity_color,
        image_url=steam_image(item.image_url, host=get_settings().skins_image_host),
        price_usd=None if price is None else str(price),
        price_uzs=uzs_text(price, rate, rules),
        steam_price_usd=_units_to_usd(item.steam_price_units),
        discount_percent=discount,
        count=item.stock_count,
        min_float=None if item.min_float is None else str(item.min_float),
        max_float=None if item.max_float is None else str(item.max_float),
    )


async def item_cards(db: AsyncSession, slugs: list[str]) -> dict[str, SkinItemOut]:
    """The cards of these items that a visitor could buy now: active, shown, in an enabled
    category and priced. Unknown, hidden and sold-out slugs are simply absent."""
    if not slugs:
        return {}
    items = await db.scalars(
        select(SkinItem).where(
            SkinItem.slug.in_(slugs),
            SkinItem.active.is_(True),
            SkinItem.hidden.is_(False),
            SkinItem.category.in_(enabled_categories(get_settings())),
            SkinItem.sell_price_usd.is_not(None),
        )
    )
    rules, rate = await load_rules(db), await usd_uzs_rate(db)
    found = {i.slug: item_out(i, rules, rate) for i in items}
    return {slug: found[slug] for slug in slugs if slug in found}
