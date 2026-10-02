"""The admin pricing editor (M4b ruling R8): the rules document, a preview, one item's
overrides.

Writes are serialised with the price tick by ``repricing.lock_pricing``, taken first, and
reprice in the same transaction, so a stored price never disagrees with the rules. The
caller commits, then publishes the rules to Redis (``settings.publish_rules``) and bumps the
catalogue version: a failed write leaves the old prices, rules and cache everywhere. A
preview reads Postgres only and writes nothing — no row, no cache, no audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.core.errors import NotFoundError
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import record
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.skins.admin_schemas import (
    PreviewIn,
    PreviewOut,
    PricingOut,
    UpdatedByOut,
)
from csmarket.modules.skins.models import SkinItem, SkinPricingRules
from csmarket.modules.skins.pricing import PricingRules, quote, to_uzs
from csmarket.modules.skins.repricing import lock_pricing, reprice_rows
from csmarket.modules.skins.settings import load_rules, read_rules, save_rules
from csmarket.modules.users.models import User

_UNITS_PER_USD = Decimal(1000)


async def _rate(db: AsyncSession) -> Decimal | None:
    fx = await current_usd_uzs(db, get_redis(), max_age_days=get_settings().fx_max_age_days)
    return None if fx is None else fx.rate


async def pricing_view(db: AsyncSession) -> PricingOut:
    """The saved document, who saved it, how many items it prices, and the rate."""
    row = await db.get(SkinPricingRules, 1, populate_existing=True)
    author = None if row is None or row.updated_by is None else await db.get(User, row.updated_by)
    active, overridden = (
        await db.execute(
            select(
                func.count().filter(SkinItem.active),
                func.count().filter(
                    or_(
                        SkinItem.margin_override_pp.is_not(None),
                        SkinItem.fixed_price_usd.is_not(None),
                    )
                ),
            ).select_from(SkinItem)
        )
    ).one()
    rate = await _rate(db)
    return PricingOut(
        rules=await read_rules(db),
        updated_at=None if row is None else row.updated_at,
        updated_by=None
        if author is None
        else UpdatedByOut(id=author.id, display_name=author.display_name),
        items_active=active,
        items_overridden=overridden,
        rate_uzs=None if rate is None else str(rate),
    )


async def save_pricing(db: AsyncSession, *, rules: PricingRules, admin: User) -> int:
    """Replace the document and reprice the catalogue; audited ``skins.pricing.save``.

    Flushes, never commits; the caller publishes the rules after its commit.

    Returns:
        Rows repriced.
    """
    await lock_pricing(db)
    await save_rules(db, rules=rules, admin_id=admin.id)
    repriced = await reprice_rows(db, rules)
    await record(
        db,
        actor_id=admin.id,
        action="skins.pricing.save",
        target_type="skin_pricing_rules",
        target_id="1",
        payload={"items_repriced": repriced},
    )
    return repriced


async def override_item(
    db: AsyncSession,
    *,
    item: SkinItem,
    margin_override_pp: Decimal | None,
    fixed_price_usd: Decimal | None,
    admin: User,
) -> None:
    """Set (or clear) one item's margin override and pinned price, and reprice it; audited
    ``skins.item.override``. Flushes, never commits."""
    await lock_pricing(db)
    item.margin_override_pp, item.fixed_price_usd = margin_override_pp, fixed_price_usd
    await db.flush()
    await reprice_rows(db, await load_rules(db, fresh=True), ids=[item.id])
    await db.refresh(item)
    await record(
        db,
        actor_id=admin.id,
        action="skins.item.override",
        target_type="skin_item",
        target_id=item.id,
        payload={
            "slug": item.slug,
            "margin_override_pp": None if margin_override_pp is None else str(margin_override_pp),
            "fixed_price_usd": None if fixed_price_usd is None else str(fixed_price_usd),
        },
    )


async def preview(db: AsyncSession, body: PreviewIn) -> PreviewOut:
    """Price an item (or a made-up one) under the saved or a draft document; writes nothing.

    Raises:
        NotFoundError: ``slug`` names no item.
    """
    rules = body.rules or await read_rules(db)
    item = None
    if body.slug is not None:
        item = await db.scalar(select(SkinItem).where(SkinItem.slug == body.slug))
        if item is None:
            raise NotFoundError("skin not found")
    own = _ItemFacts.of(item)
    cost = _pick(body.cost_usd, own.cost_usd) or Decimal(0)
    q = quote(
        int((cost * _UNITS_PER_USD).to_integral_value(rounding=ROUND_HALF_UP)),
        rules=rules,
        category=body.category or own.category,
        weapon=body.weapon or own.weapon,
        count_auto=_pick(body.count_auto, own.count_auto),
        item_pp=_pick(body.item_pp, own.item_pp),
        fixed_price_usd=_pick(body.fixed_price_usd, own.fixed_price_usd),
        steam_price_units=own.steam_price_units,
    )
    rate = await _rate(db)
    uzs = None if rate is None else to_uzs(q.price_usd, rate, round_to=rules.uzs_round_to)
    return PreviewOut(
        price_usd=str(q.price_usd),
        price_uzs=None if uzs is None else str(uzs),
        cost_usd=_plain(q.cost_usd),
        expenses_usd=_plain(q.expenses_usd),
        bracket_margin_usd=_plain(q.bracket_margin_usd),
        category_pp=_plain(q.category_pp),
        weapon_pp=_plain(q.weapon_pp),
        liquidity_pp=_plain(q.liquidity_pp),
        item_pp=_plain(q.item_pp),
        effective_percent=str(q.effective_percent),
        applied=q.applied,
    )


@dataclass(frozen=True, slots=True)
class _ItemFacts:
    """What an item contributes to a preview; all blank without one."""

    cost_usd: Decimal | None = None
    category: str = ""
    weapon: str | None = None
    count_auto: int | None = None
    item_pp: Decimal | None = None
    fixed_price_usd: Decimal | None = None
    steam_price_units: int | None = None

    @classmethod
    def of(cls, item: SkinItem | None) -> _ItemFacts:
        if item is None:
            return cls()
        units = item.min_auto_units
        return cls(
            cost_usd=None if units is None else Decimal(units) / _UNITS_PER_USD,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.count_auto,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        )


def _pick[T](given: T | None, own: T | None) -> T | None:
    """The request's value when it gave one, else the item's."""
    return given if given is not None else own


def _plain(value: Decimal) -> str:
    """A Decimal without trailing zeros or an exponent: ``10``, ``0.55``."""
    text = format(value.normalize(), "f")
    return text if "." not in text else text.rstrip("0").rstrip(".") or "0"


__all__ = ["override_item", "preview", "pricing_view", "save_pricing"]
