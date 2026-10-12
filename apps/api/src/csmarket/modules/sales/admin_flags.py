"""The admin's flags on «Выкуп» (review 2026-10-11 SB-2, SB-6): a sale's attention marked
checked, and the per-user sell block.

Every change is audited in the caller's transaction (``sales.attention.resolve``,
``sales.user.block``, ``sales.user.unblock``); flush, never commit.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.admin.api import record
from csmarket.modules.sales.admin_sales import user_of, users_by_id
from csmarket.modules.sales.admin_schemas import AdminUserOut, SellBlockOut, SellBlocksOut
from csmarket.modules.sales.models import Sale, SaleBlock
from csmarket.modules.sales.status import lock_sale
from csmarket.modules.users.api import User

log = get_logger("csmarket.sales.admin_flags")

#: The blocked-users list is short by nature; this is a safety cap.
BLOCKS_LIMIT = 500


async def resolve_attention(
    db: AsyncSession, *, number: str, admin_id: str, note: str | None
) -> Sale:
    """«Проверено»: stamp the sale's attention resolved once, audited; one already resolved
    is left as it is (no second audit row).

    Raises:
        NotFoundError: No such sale.
        ConflictError: ``nothing_to_resolve`` — the sale has no attention.
    """
    sale_id = await db.scalar(select(Sale.id).where(Sale.number == number))
    sale = await lock_sale(db, sale_id) if sale_id is not None else None
    if sale is None:
        raise NotFoundError("sale not found")
    if sale.attention_reason is None:
        raise ConflictError("the sale has no attention", code="nothing_to_resolve")
    if sale.resolved_at is not None:
        return sale
    sale.resolved_at, sale.resolved_by, sale.resolved_note = now(), admin_id, note
    await record(
        db,
        actor_id=admin_id,
        action="sales.attention.resolve",
        target_type="sale",
        target_id=sale.number,
        payload={"reason": sale.attention_reason},
    )
    await db.flush()
    log.info("sales.attention.resolved", number=sale.number, reason=sale.attention_reason)
    return sale


def _block_out(
    user_id: str, block: SaleBlock | None, users: dict[str, AdminUserOut]
) -> SellBlockOut:
    by = block.blocked_by if block is not None else None
    return SellBlockOut(
        user=user_of(users, user_id),
        blocked=block is not None,
        reason=block.reason if block is not None else None,
        blocked_by=user_of(users, by) if by else None,
        blocked_at=block.created_at if block is not None else None,
    )


async def sell_block(db: AsyncSession, user_id: str) -> SellBlockOut:
    """Whether ``user_id`` may sell.

    Raises:
        NotFoundError: No such user.
    """
    if await db.get(User, user_id) is None:
        raise NotFoundError("user not found")
    block = await db.get(SaleBlock, user_id, populate_existing=True)
    users = await users_by_id(
        db, [user_id, *([block.blocked_by] if block and block.blocked_by else [])]
    )
    return _block_out(user_id, block, users)


async def sell_blocks(db: AsyncSession) -> SellBlocksOut:
    """Every blocked user, newest block first (one query for the names)."""
    rows = list(
        (
            await db.scalars(
                select(SaleBlock).order_by(SaleBlock.created_at.desc()).limit(BLOCKS_LIMIT)
            )
        ).all()
    )
    ids = [r.user_id for r in rows] + [r.blocked_by for r in rows if r.blocked_by]
    users = await users_by_id(db, ids)
    return SellBlocksOut(items=[_block_out(r.user_id, r, users) for r in rows])


async def set_sell_block(
    db: AsyncSession, *, user_id: str, blocked: bool, reason: str | None, admin_id: str
) -> bool:
    """Block ``user_id`` from selling (``reason`` required) or lift it; audited when it
    changes anything. A block already in place keeps its first reason.

    Returns:
        Whether anything changed.

    Raises:
        NotFoundError: No such user.
    """
    if await db.get(User, user_id) is None:
        raise NotFoundError("user not found")
    block = await db.get(SaleBlock, user_id, with_for_update=True, populate_existing=True)
    if blocked == (block is not None):
        return False
    if blocked:
        db.add(SaleBlock(user_id=user_id, reason=(reason or "").strip(), blocked_by=admin_id))
    else:
        await db.delete(block)
    await record(
        db,
        actor_id=admin_id,
        action="sales.user.block" if blocked else "sales.user.unblock",
        target_type="user",
        target_id=user_id,
        payload={},
    )
    await db.flush()
    log.info("sales.user.block_set", blocked=blocked)
    return True


__all__ = ["BLOCKS_LIMIT", "resolve_attention", "sell_block", "sell_blocks", "set_sell_block"]
