"""One-shot "ask Skinslink about purchase N" rows, drained by the worker's ``skinslink`` queue.

A webhook (or nothing: the reconcile job polls on its own) inserts a row and notifies in the
caller's transaction; the drain claims rows ``FOR UPDATE SKIP LOCKED`` and deletes them once
asked. A failed ask is not retried by the row: the reconcile job polls every open purchase.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.skinslink.models import SKINSLINK_CHANNEL, SkinslinkCheck


async def enqueue_check(db: AsyncSession, purchase_id: int) -> None:
    """Queue a check of ``purchase_id``; delivered when the caller commits."""
    db.add(SkinslinkCheck(purchase_id=purchase_id))
    await db.flush()
    await db.execute(select(func.pg_notify(SKINSLINK_CHANNEL, str(purchase_id))))


async def claim_checks(db: AsyncSession, *, limit: int = 20) -> list[int]:
    """Take up to ``limit`` queued checks, oldest first, and delete them; the caller commits.

    Returns:
        The purchase ids to ask about (a purchase queued twice is asked once).
    """
    rows = (
        await db.execute(
            select(SkinslinkCheck.id, SkinslinkCheck.purchase_id)
            .order_by(SkinslinkCheck.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return []
    await db.execute(delete(SkinslinkCheck).where(SkinslinkCheck.id.in_([r[0] for r in rows])))
    return list(dict.fromkeys(r[1] for r in rows))


__all__ = ["claim_checks", "enqueue_check"]
