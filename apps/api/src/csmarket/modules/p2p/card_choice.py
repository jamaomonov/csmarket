"""Which card a new request goes on, and how far its amount may be bumped."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, time
from typing import Final

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError
from csmarket.modules.orders.api import TASHKENT
from csmarket.modules.p2p.models import P2PCard, P2PReservation

#: An amount already open on a card is bumped by up to this many soʻm.
MAX_BUMP: Final = 99
_LOCK_NAMESPACE: Final = b"p2p-card-daily-limit:"
_NO_LIMIT: Final = 10**18


def card_lock_key(card_id: str) -> int:
    """A stable signed 64-bit ``pg_advisory_xact_lock`` key for one card (not Python's
    per-process salted ``hash``, so every API process takes the same lock)."""
    digest = hashlib.blake2b(_LOCK_NAMESPACE + card_id.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def _lock_limited(db: AsyncSession, cards: Sequence[P2PCard]) -> None:
    """Serialise requests per card with a daily limit, to the transaction's end.

    The daily room is a read-then-insert: without the lock two concurrent holds both read
    the same room and together pass the limit. Locks are taken in key order, all before any
    room is read, so two requests wanting overlapping cards never wait in a cycle.
    """
    keys = sorted({card_lock_key(c.id) for c in cards if c.daily_limit_uzs is not None})
    for key in keys:
        await db.execute(select(func.pg_advisory_xact_lock(key)))


async def held_today(db: AsyncSession, card: P2PCard, at: datetime) -> int:
    """Soʻm the card is committed to today: paid this Tashkent day plus open holds."""
    start = datetime.combine(at.astimezone(TASHKENT).date(), time(), TASHKENT)
    total = await db.scalar(
        select(func.coalesce(func.sum(P2PReservation.amount_uzs), 0)).where(
            P2PReservation.card_id == card.id,
            or_(
                and_(P2PReservation.status == "paid", P2PReservation.closed_at >= start),
                and_(P2PReservation.status == "pending", P2PReservation.expires_at > at),
            ),
        )
    )
    return int(total or 0)


async def eligible_cards(db: AsyncSession, amount: int, at: datetime) -> list[tuple[P2PCard, int]]:
    """Cards that can take ``amount``, most daily room first, each with its bump cap.

    Raises:
        ConflictError: ``p2p_unavailable`` — no active card's bounds or daily room fit.
    """
    cards = (
        (
            await db.execute(
                select(P2PCard)
                .where(
                    P2PCard.active.is_(True),
                    P2PCard.min_amount_uzs <= amount,
                    P2PCard.max_amount_uzs >= amount,
                )
                .order_by(P2PCard.created_at, P2PCard.id)
            )
        )
        .scalars()
        .all()
    )
    await _lock_limited(db, cards)
    ranked: list[tuple[int, P2PCard, int]] = []
    for card in cards:
        room: int | None = None
        if card.daily_limit_uzs is not None:
            room = card.daily_limit_uzs - await held_today(db, card, at)
            if room < amount:
                continue
        cap = min(MAX_BUMP, card.max_amount_uzs - amount)
        if room is not None:
            cap = min(cap, room - amount)
        ranked.append((room if room is not None else _NO_LIMIT, card, cap))
    if not ranked:
        raise ConflictError("no card can take this amount now", code="p2p_unavailable")
    ranked.sort(key=lambda t: -t[0])  # stable: ties keep the oldest card first
    return [(card, cap) for _, card, cap in ranked]


__all__ = ["MAX_BUMP", "card_lock_key", "eligible_cards", "held_today"]
