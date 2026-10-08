"""Sale letters, enqueued in the transaction of the event they report (spec 2026-10-08 §8).

``sale_hold`` when the trade is accepted, ``sale_paid`` when the money is on the balance or
an admin paid the card (or rejected it and the money went to the balance), ``sale_canceled``
when an offered sale closes or is reverted. One letter per sale and kind (a replay enqueues
nothing); whether it is sent is decided at send time (a verified address). The payload
snapshots the number and the amount; a card appears by its last four digits only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.money import wire_uzs
from csmarket.modules.notifications.api import enqueue
from csmarket.modules.sales.models import Sale

SaleLetter = Literal["sale_hold", "sale_paid", "sale_canceled"]


async def enqueue_sale_letter(
    db: AsyncSession,
    sale: Sale,
    kind: SaleLetter,
    *,
    amount_uzs: Decimal | None = None,
    to: Literal["balance", "card"] | None = None,
    last4: str | None = None,
) -> None:
    """Queue ``kind`` about ``sale``; flushes with the caller's transaction, never commits."""
    payload = {
        "number": sale.number,
        "amount_uzs": wire_uzs(amount_uzs if amount_uzs is not None else sale.payout_uzs),
    }
    if to is not None:
        payload["to"] = to
    if last4 is not None:
        payload["last4"] = last4
    await enqueue(db, kind=kind, user_id=sale.user_id, sale_id=sale.id, payload=payload)


__all__ = ["SaleLetter", "enqueue_sale_letter"]
