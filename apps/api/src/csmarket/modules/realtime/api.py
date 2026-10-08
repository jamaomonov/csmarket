"""Public interface of ``realtime`` — what other modules import (rulings R1, R4).

Imports nothing from ``orders`` or ``payments``: they call :func:`nudge`, never the reverse.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: The Postgres channel order status changes are announced on.
CHANNEL = "order_events"


async def nudge(db: AsyncSession, *, user_id: str, number: str) -> None:
    """Announce that ``number`` (owned by ``user_id``) changed, in the caller's transaction.

    ``pg_notify`` is delivered only when the transaction commits, so a socket's owner who
    re-reads the order on the nudge always sees the new state (ruling R1). The payload is
    internal ids only and is never logged. Never commits.
    """
    await db.execute(select(func.pg_notify(CHANNEL, f"{user_id}:{number}")))


async def nudge_sale(db: AsyncSession, *, user_id: str, number: str) -> None:
    """Like :func:`nudge`, for a sale: the owner's sockets get ``sale.updated``. Never commits."""
    await db.execute(select(func.pg_notify(CHANNEL, f"{user_id}:{number}:sale")))


__all__ = ["CHANNEL", "nudge", "nudge_sale"]
