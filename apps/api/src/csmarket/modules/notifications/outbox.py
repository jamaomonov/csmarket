"""Enqueue a letter in the caller's transaction (M4b ruling R5).

The row and its ``NOTIFY emails`` ride the event's transaction: both land on commit, or
neither does. An order letter is unique per order and kind, so a replayed event (a second
kassa attempt settling, a re-run reconcile) enqueues nothing new.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.notifications.models import KINDS, EmailOutbox

#: The LISTEN channel of the worker's ``emails`` queue.
EMAILS_CHANNEL = "emails"


async def enqueue(
    db: AsyncSession,
    *,
    kind: str,
    user_id: str,
    order_id: str | None = None,
    address: str | None = None,
    payload: dict[str, str] | None = None,
) -> str | None:
    """Add one letter to the outbox and wake the worker on commit. Flushes, never commits.

    Args:
        db: The session of the event the letter reports.
        kind: One of :data:`~csmarket.modules.notifications.models.KINDS`.
        user_id: The account the letter is for.
        order_id: The order an order letter reports; ``None`` for ``verify``.
        address: The address a ``verify`` letter confirms; ``None`` for order letters.
        payload: Strings the template needs.

    Returns:
        The new row's id, or ``None`` when this order already has a letter of this kind.

    Raises:
        ValueError: An unknown ``kind``.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown email kind {kind!r}")
    stmt = (
        insert(EmailOutbox)
        .values(
            kind=kind,
            user_id=user_id,
            order_id=order_id,
            address=address,
            payload=payload or {},
        )
        .on_conflict_do_nothing(
            index_elements=["order_id", "kind"], index_where=EmailOutbox.order_id.is_not(None)
        )
        .returning(EmailOutbox.id)
    )
    row_id = await db.scalar(stmt)
    if row_id is None:
        return None
    await db.execute(select(func.pg_notify(EMAILS_CHANNEL, row_id)))
    return str(row_id)
