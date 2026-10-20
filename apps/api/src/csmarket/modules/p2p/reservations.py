"""Exact-amount top-up requests (spec 2026-10-19-p2p-topup).

The amount a buyer transfers is the only thing that ties a bank notification back to them,
so two open requests on one card must never share an amount. That rule lives in the partial
unique index ``uq_p2p_reservations_open_amount`` (``holds_amount`` is true while pending and
through quarantine), not in a read-then-write here: two requests racing for 50 000 both try
the insert, one wins, the other bumps to 50 001.

A request is the top-up's P2P attempt held by the "kassa" (``payments.mark_pending``) for its
ten minutes and its quarantine, so the top-up expiry sweep leaves it alone and a late transfer
still settles it; when the quarantine ends the sweep cancels the attempt and the top-up then
expires the usual way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final

from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, ValidationError
from csmarket.core.logging import get_logger
from csmarket.modules.orders.api import TASHKENT
from csmarket.modules.p2p.card_choice import eligible_cards
from csmarket.modules.p2p.cards import open_pan
from csmarket.modules.p2p.integrity import violated_constraint
from csmarket.modules.p2p.models import P2PCard, P2PReservation
from csmarket.modules.p2p.settings import load_settings
from csmarket.modules.payments.api import Payment, WalletTopup, cancel_pending, mark_pending

log = get_logger("csmarket.p2p.reservations")

RESERVATION_TTL: Final = timedelta(minutes=10)
QUARANTINE: Final = timedelta(minutes=10)
_OPEN_AMOUNT_INDEX: Final = "uq_p2p_reservations_open_amount"
_ONE_PENDING_INDEX: Final = "uq_p2p_reservations_one_pending"


@dataclass(frozen=True)
class P2PDetails:
    """What the buyer needs to transfer: the full card, the holder, the exact amount."""

    number: str
    card_number: str
    holder: str
    amount_uzs: int
    expires_at: datetime
    status: str


@dataclass(frozen=True)
class SweepResult:
    """Rows touched by one :func:`sweep` pass."""

    expired: int
    released: int


def _day_start(at: datetime) -> datetime:
    return datetime.combine(at.astimezone(TASHKENT).date(), time(), TASHKENT)


async def _check_limits(db: AsyncSession, *, user_id: str, amount: int, at: datetime) -> None:
    """The buyer's limits (spec ruling 4); an open request past its time is expired first.

    Raises:
        ValidationError: ``p2p_amount`` — outside the settings' min / max.
        ConflictError: ``p2p_open_request`` (one is still waiting) or ``p2p_daily_limit``.
    """
    s = await load_settings(db)
    if not s.min_amount_uzs <= amount <= s.max_amount_uzs:
        raise ValidationError(
            "amount out of the transfer range",
            code="p2p_amount",
            min=s.min_amount_uzs,
            max=s.max_amount_uzs,
        )
    await _expire_overdue(db, at, user_id=user_id)
    if await db.scalar(
        select(P2PReservation.id).where(
            P2PReservation.user_id == user_id, P2PReservation.status == "pending"
        )
    ):
        raise ConflictError("a transfer request is already waiting", code="p2p_open_request")
    today = and_(
        P2PReservation.user_id == user_id,
        P2PReservation.created_at >= _day_start(at),
        P2PReservation.status.in_(("pending", "paid")),
    )
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(P2PReservation.amount_uzs), 0)).where(today)
        )
    ).one()
    if int(count) >= s.daily_count or int(total) + amount > s.daily_amount_uzs:
        raise ConflictError(
            "the daily transfer limit is reached",
            code="p2p_daily_limit",
            count=s.daily_count,
            amount=s.daily_amount_uzs,
        )


async def _hold(
    db: AsyncSession, *, topup: WalletTopup, payment: Payment, amount: int, at: datetime
) -> P2PReservation:
    """Insert the request on the first card and amount (``amount`` … ``amount + cap``) free."""
    for card, cap in await eligible_cards(db, amount, at):
        for bump in range(cap + 1):
            row = P2PReservation(
                number=topup.number,
                user_id=topup.user_id,
                topup_id=topup.id,
                payment_id=payment.id,
                card_id=card.id,
                amount_uzs=amount + bump,
                status="pending",
                holds_amount=True,
                created_at=at,
                expires_at=at + RESERVATION_TTL,
            )
            try:
                async with db.begin_nested():
                    db.add(row)
                    await db.flush()
            except IntegrityError as exc:
                hit = violated_constraint(exc, (_OPEN_AMOUNT_INDEX, _ONE_PENDING_INDEX))
                if hit == _OPEN_AMOUNT_INDEX:
                    continue
                if hit == _ONE_PENDING_INDEX:
                    raise ConflictError(
                        "a transfer request is already waiting", code="p2p_open_request"
                    ) from exc
                raise
            log.info("p2p.reserved", number=row.number, amount_uzs=row.amount_uzs)
            return row
    raise ConflictError("every nearby amount is taken; try again", code="p2p_unavailable")


async def reserve_topup(
    db: AsyncSession, *, topup: WalletTopup, payment: Payment, at: datetime
) -> P2PReservation:
    """Hold an exact amount on a card for ``topup``'s P2P attempt ``payment``; flushes.

    The top-up and its attempt take the held amount (the typed one, or up to +99 soʻm): the
    whole transfer is credited. The attempt is marked held (``pending``) at once.

    Raises:
        ValidationError: ``p2p_amount``.
        ConflictError: ``p2p_open_request``, ``p2p_daily_limit``, ``p2p_unavailable``.
    """
    amount = int(topup.amount_uzs)
    await _check_limits(db, user_id=topup.user_id, amount=amount, at=at)
    row = await _hold(db, topup=topup, payment=payment, amount=amount, at=at)
    if row.amount_uzs != amount:
        topup.amount_uzs = payment.amount_uzs = type(topup.amount_uzs)(row.amount_uzs)
    # Past the request and its quarantine the sweep cancels the attempt; until then no
    # top-up expiry may touch it.
    topup.expires_at = row.expires_at + QUARANTINE
    await mark_pending(db, payment=payment)
    return row


async def details(db: AsyncSession, topup_id: str) -> P2PDetails | None:
    """The transfer details of ``topup_id``'s request; ``None`` for a non-P2P top-up."""
    row = await db.scalar(select(P2PReservation).where(P2PReservation.topup_id == topup_id))
    if row is None:
        return None
    card = await db.get(P2PCard, row.card_id)
    if card is None:  # a card row is never deleted
        return None
    return P2PDetails(
        number=row.number,
        card_number=open_pan(card),
        holder=card.holder_name,
        amount_uzs=row.amount_uzs,
        expires_at=row.expires_at,
        status=row.status,
    )


async def _expire_overdue(db: AsyncSession, at: datetime, *, user_id: str | None = None) -> int:
    """Pending requests past their time → ``expired``, quarantined from their expiry."""
    stmt = update(P2PReservation).where(
        P2PReservation.status == "pending", P2PReservation.expires_at <= at
    )
    if user_id is not None:
        stmt = stmt.where(P2PReservation.user_id == user_id)
    result = await db.execute(
        stmt.values(
            status="expired",
            closed_at=P2PReservation.expires_at,
            quarantine_until=P2PReservation.expires_at + QUARANTINE,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def sweep(db: AsyncSession, *, at: datetime) -> SweepResult:
    """Expire overdue requests, then release amounts whose quarantine ended and cancel the
    attempts of the released unpaid ones (their top-ups then expire). Flushes, never commits.

    ``paid`` rows are released too: they hold their amount for the same quarantine so a
    repeated transfer of it lands unmatched.
    """
    expired = await _expire_overdue(db, at)
    done = list(
        (
            await db.execute(
                select(P2PReservation)
                .where(
                    P2PReservation.holds_amount.is_(True),
                    P2PReservation.status.in_(("expired", "cancelled", "paid")),
                    P2PReservation.quarantine_until <= at,
                )
                # Intake locks the row it settles: a late credit landing as the quarantine
                # ends must keep its hold (``paid`` restarts it); the next tick gets it.
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for row in done:
        row.holds_amount = False
        if row.status != "paid":
            payment = await db.get(Payment, row.payment_id)
            if payment is not None:
                await cancel_pending(db, payment=payment)
    await db.flush()
    return SweepResult(expired=expired, released=len(done))


async def sweep_tick(db: AsyncSession, *, at: datetime) -> tuple[SweepResult, datetime | None]:
    """One scheduler tick: :func:`sweep`, and when the last HUMO notification arrived (the
    ``P2PSilence`` alert's input)."""
    result = await sweep(db, at=at)
    return result, (await load_settings(db)).last_received_at


__all__ = [
    "QUARANTINE",
    "RESERVATION_TTL",
    "P2PDetails",
    "SweepResult",
    "details",
    "reserve_topup",
    "sweep",
    "sweep_tick",
]
