"""A card sale's payout request (spec 2026-10-08 §4, §6): opened at ``hold``, payable at
``completed``, canceled when the sale fails or is reverted before it was paid.

Read under the sale's lock and then its own (the order :mod:`.status` and the admin's
actions both take: sale, then request). Flush, never commit.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.sales.models import PayoutRequest, Sale

#: A request still waiting for its money; a failed or reverted sale cancels it.
_OPEN = frozenset({"waiting_hold", "to_pay"})


async def request_of(db: AsyncSession, sale_id: str, *, lock: bool = False) -> PayoutRequest | None:
    """The sale's request, read fresh (``FOR UPDATE`` with ``lock``)."""
    stmt = select(PayoutRequest).where(PayoutRequest.sale_id == sale_id)
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt.execution_options(populate_existing=True))


async def open_request(
    db: AsyncSession, sale: Sale, *, status: Literal["waiting_hold", "to_pay"]
) -> PayoutRequest:
    """The card sale's request, created in ``status`` if it has none yet.

    Raises:
        ValueError: ``sale`` pays to the balance — a caller bug.
    """
    existing = await request_of(db, sale.id, lock=True)
    if existing is not None:
        return existing
    if sale.payout_card_id is None:
        raise ValueError("a balance sale has no payout request")
    request = PayoutRequest(
        id=new_id(),
        sale_id=sale.id,
        user_id=sale.user_id,
        card_id=sale.payout_card_id,
        amount_uzs=sale.payout_uzs,
        fee_uzs=sale.items_uzs - sale.payout_uzs,
        status=status,
        to_pay_at=now() if status == "to_pay" else None,
    )
    db.add(request)
    await db.flush()
    return request


async def cancel_request(db: AsyncSession, sale: Sale) -> None:
    """Cancel the sale's request if it still waits for money; a paid one is left alone."""
    request = await request_of(db, sale.id, lock=True)
    if request is not None and request.status in _OPEN:
        request.status = "canceled"
        await db.flush()


__all__ = ["cancel_request", "open_request", "request_of"]
