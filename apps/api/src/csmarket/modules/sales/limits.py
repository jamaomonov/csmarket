"""What ``POST /sell`` refuses before it stores a sale (review 2026-10-11 SB-6, SB-10).

- a seller an admin blocked (``sale_blocks``) → 409 ``sell_blocked``;
- an item already in one of the seller's open sales (``creating`` / ``offered``: its Steam
  offer may still be accepted) → 409 ``items_in_sale``;
- the admin's optional USD ceilings (:class:`.rules.SaleSettings`), on the sum of the items'
  Skinslink prices: ``max_sale_usd`` → 409 ``above_sale_maximum``; ``max_user_day_usd`` over
  the seller's last 24 h → 409 ``user_daily_limit``; ``max_day_usd`` over everyone's last
  24 h → 409 ``daily_limit``. Each carries the limit and what is left of it, in USD.

A sale counts towards a day unless it ended paying nothing (``closed`` / ``reverted``). The
checks hold transaction-scoped advisory locks — the seller's, and the shop's while a daily
limit is set — until ``service._store`` commits the sale, so two requests at once cannot both
pass on the same items or the same remainder. Nothing external runs while they are held.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError
from csmarket.modules.sales.models import Sale, SaleBlock, SaleItem
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.schemas import plain

#: The window of the daily limits.
DAY = timedelta(hours=24)
#: Sales whose Steam offer may still be accepted: their items cannot be sold twice.
_OFFERING = ("creating", "offered")
#: Sales that ended paying nothing do not count towards a limit.
_UNPAID = ("closed", "reverted")


async def _lock(db: AsyncSession, name: str) -> None:
    """A transaction-scoped advisory lock on ``name`` (released at commit or rollback)."""
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(name))))


async def is_blocked(db: AsyncSession, user_id: str) -> bool:
    """Whether an admin stopped ``user_id`` from selling."""
    return await db.get(SaleBlock, user_id, populate_existing=True) is not None


async def _check_items(db: AsyncSession, user_id: str, asset_ids: Sequence[str]) -> None:
    busy = await db.scalar(
        select(SaleItem.asset_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.user_id == user_id,
            Sale.status.in_(_OFFERING),
            SaleItem.asset_id.in_(list(asset_ids)),
        )
        .limit(1)
    )
    if busy is not None:
        raise ConflictError("an item is already in an open sale", code="items_in_sale")


async def _sold_usd(db: AsyncSession, since: datetime, *where: ColumnElement[bool]) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(Sale.quoted_usd), 0)).where(
            Sale.created_at >= since, Sale.status.not_in(_UNPAID), *where
        )
    )
    return Decimal(total or 0)


def _over(code: str, message: str, limit: Decimal, used: Decimal) -> ConflictError:
    left = max(limit - used, Decimal(0))
    return ConflictError(message, code=code, limit_usd=plain(limit), left_usd=plain(left))


async def check_sale_allowed(
    db: AsyncSession,
    *,
    user_id: str,
    asset_ids: Sequence[str],
    quoted_usd: Decimal,
    doc: SaleSettings,
    at: datetime,
) -> None:
    """Refuse the sale if the seller is blocked, an item is taken, or a ceiling is passed.

    Takes the locks described in the module docstring; the caller commits or rolls back.

    Raises:
        ConflictError: ``sell_blocked``, ``items_in_sale``, ``above_sale_maximum``,
            ``user_daily_limit``, ``daily_limit`` (the last three with ``limit_usd`` and
            ``left_usd``).
    """
    if await is_blocked(db, user_id):
        raise ConflictError("this account may not sell", code="sell_blocked")
    await _lock(db, f"sales:user:{user_id}")
    await _check_items(db, user_id, asset_ids)
    if doc.max_sale_usd is not None and quoted_usd > doc.max_sale_usd:
        raise _over(
            "above_sale_maximum", "the sale is above the maximum", doc.max_sale_usd, Decimal(0)
        )
    since = at - DAY
    if doc.max_user_day_usd is not None:
        used = await _sold_usd(db, since, Sale.user_id == user_id)
        if used + quoted_usd > doc.max_user_day_usd:
            raise _over("user_daily_limit", "the seller's daily limit", doc.max_user_day_usd, used)
    if doc.max_day_usd is not None:
        await _lock(db, "sales:day")
        used = await _sold_usd(db, since)
        if used + quoted_usd > doc.max_day_usd:
            raise _over("daily_limit", "the shop's daily limit", doc.max_day_usd, used)


__all__ = ["DAY", "check_sale_allowed", "is_blocked"]
