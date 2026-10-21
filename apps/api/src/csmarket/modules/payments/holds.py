"""Held kassa payments (spec 2026-10-21-payment-risk-limits).

:func:`hold` is called by ``hooks.settle`` when the risk verdict holds: the attempt is already
``succeeded`` (the kassa has the money), the owner goes ``held`` and a ``payment_holds`` row
records why. Nothing is credited and no ``NOTIFY orders`` is sent until an admin decides.
:func:`reverse_held` is the kassa taking a held payment back (the one exception to ruling R7);
:func:`close` records any decision on an open hold.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.orders.api import Order
from csmarket.modules.orders.api import move as move_order
from csmarket.modules.payments.fsm import move as move_payment
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.risk.api import HoldDecision, HoldKind, PaymentHold, Verdict

log = get_logger("csmarket.payments.holds")


async def hold(
    db: AsyncSession, *, payment: Payment, owner: WalletTopup | Order, verdict: Verdict
) -> PaymentHold:
    """Put ``owner`` on review for ``payment`` (already ``succeeded``) and record why.

    An order goes ``pending`` → ``held`` with ``paid_with`` = the provider (``paid_at`` stays
    empty); a top-up goes ``held`` and points at the attempt, uncredited.

    Args:
        db: Session; the caller holds the owner, then the payment ``FOR UPDATE`` and commits.
        payment: The settled attempt.
        owner: The top-up or order the attempt pays.
        verdict: A holding verdict (``hold`` true, ``reason`` set).

    Returns:
        The new open hold row (flushed).
    """
    kind: HoldKind
    if isinstance(owner, Order):
        move_order(owner, "held")
        owner.paid_with = payment.provider
        kind = "order"
    else:
        owner.status = "held"
        owner.payment_id = payment.id
        owner.succeeded_at = payment.succeeded_at
        kind = "topup"
    reason = verdict.reason or "check_failed"
    row = PaymentHold(
        payment_id=payment.id,
        user_id=payment.user_id,
        kind=kind,
        provider=payment.provider,
        amount_uzs=payment.amount_uzs,
        reason=reason,
        window_sum_uzs=verdict.window_sum_uzs,
        limit_uzs=verdict.limit_uzs,
    )
    db.add(row)
    await db.flush()
    log.warning(
        "payments.hold.created",
        number=owner.number,
        kind=kind,
        provider=payment.provider,
        amount=str(payment.amount_uzs),
        reason=reason,
    )
    return row


async def open_hold_for(
    db: AsyncSession, payment_id: str, *, lock: bool = False
) -> PaymentHold | None:
    """The undecided hold of attempt ``payment_id``, if any.

    Args:
        db: Session.
        payment_id: The held attempt's id.
        lock: Take the row ``FOR UPDATE`` (a decision follows).

    Returns:
        The open hold row, or ``None`` when there is none (never held, or already decided).
    """
    q = select(PaymentHold).where(
        PaymentHold.payment_id == payment_id, PaymentHold.decision.is_(None)
    )
    if lock:
        q = q.with_for_update()
    return (await db.execute(q)).scalar_one_or_none()


def close(hold_row: PaymentHold, *, decision: HoldDecision, admin_id: str | None) -> None:
    """Record ``decision`` on an open hold (``admin_id`` ``None`` = the kassa decided).

    Args:
        hold_row: The open hold (locked by the caller).
        decision: What was decided.
        admin_id: The deciding admin's user id, or ``None`` for a kassa reversal.
    """
    hold_row.decision = decision
    hold_row.decided_by = admin_id
    hold_row.decided_at = now()


async def reverse_held(
    db: AsyncSession, *, payment: Payment, owner: WalletTopup | Order, event_id: str
) -> None:
    """The kassa took back a held payment: nothing was credited or bought, nothing to claw back.

    The attempt goes ``refunded``, an order ``cancelled``, a top-up ``reversed``, and the open
    hold closes as ``reversed_by_kassa`` with no admin.

    Args:
        db: Session; the caller locked the owner, then the payment, and commits.
        payment: The held attempt (``succeeded``).
        owner: Its top-up or order, ``held``.
        event_id: The kassa's reversal event, kept on the attempt.
    """
    row = await open_hold_for(db, payment.id, lock=True)
    move_payment(payment, "refunded")
    payment.extra_metadata = {**payment.extra_metadata, "reverse_event_id": event_id}
    if isinstance(owner, Order):
        move_order(owner, "cancelled")
    else:
        owner.status = "reversed"
    if row is not None:
        close(row, decision="reversed_by_kassa", admin_id=None)
    await db.flush()
    log.warning(
        "payments.hold.reversed_by_kassa",
        number=owner.number,
        provider=payment.provider,
        amount=str(payment.amount_uzs),
    )
