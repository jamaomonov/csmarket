"""Held kassa payments (spec 2026-10-21-payment-risk-limits).

:func:`hold` is called by ``hooks.settle`` when the risk verdict holds: the attempt is already
``succeeded`` (the kassa has the money), the owner goes ``held`` and a ``payment_holds`` row
records why. Nothing is credited and no ``NOTIFY orders`` is sent until an admin decides.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.logging import get_logger
from csmarket.modules.orders.api import Order
from csmarket.modules.orders.api import move as move_order
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.risk.api import HoldKind, PaymentHold, Verdict

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
