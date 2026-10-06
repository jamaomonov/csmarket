"""An order's money back to the balance, exactly once (spec §7.8, rulings R3, R9).

- :func:`refund_to_balance` — the one refund path: the worker and the reconcile sweep (an
  order that ``failed`` or was ``returned``) and the admin refund all book through it. The
  key ``refund:order:{order_id}`` and ``orders.refunded_at`` (read under the order lock)
  make a second call a no-op.
- :func:`in_flight` — whether the order's skin may still reach the buyer, or may already
  have: no refund then (Waxpeer cannot recall an offer we paid for).
- :data:`ADMIN_REFUNDABLE` — the attention reasons under which an admin may refund
  (``orders.admin_actions.admin_refund``): ``failed`` and ``returned`` orders are refunded
  automatically, so the only case left is an attention order (R3) whose Waxpeer side an
  operator checked and resolved: nothing was bought.

Imports ``wallet`` and the module's own models and FSM — never ``payments`` (ruling A;
``orders.api`` exports this module).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import OrderRefundReason, record_order_refund
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.letters import enqueue_refunded
from csmarket.modules.orders.models import FAILURE_REASONS, IN_FLIGHT, Order, SkinTrade
from csmarket.modules.realtime.api import nudge
from csmarket.modules.wallet.api import credit_order_refund

log = get_logger("csmarket.orders.refunds")

#: The statuses a refund moves an order to; both come with the refund (R1).
RefundStatus = Literal["failed", "returned"]
_REFUND_STATUSES: frozenset[str] = frozenset({"failed", "returned"})
#: Attention reasons under which a ``buying`` order may hold no skin at all — once an
#: operator checked Waxpeer and resolved the trade, an admin may refund it.
ADMIN_REFUNDABLE: frozenset[str] = frozenset(
    {"buy_unconfirmed", "ambiguous_trade", "source_forbidden"}
)
#: Attention reasons whose outcome is unknown or spent (R3): while one is unresolved no
#: refund is booked, by any path. ``source_forbidden`` is not here — nothing was bought, so
#: a later sold-out or low-balance refund must still go through.
BLOCKS_REFUND: frozenset[str] = frozenset(
    {"buy_unconfirmed", "ambiguous_trade", "rolled_back", "audit_divergence"}
)


def in_flight(order: Order, trade: SkinTrade | None) -> bool:
    """Whether ``order``'s skin is on its way or may have reached the buyer — no refund.

    ``paid``, ``buying`` and ``trade_sent`` are in flight; so is a ``delivered`` order whose
    trade waits for an admin (an unresolved ``attention_reason``, e.g. ``rolled_back``).

    Args:
        order: The order.
        trade: Its ``skin_trades`` row, if any.
    """
    if order.status in IN_FLIGHT:
        return True
    return (
        order.status == "delivered"
        and trade is not None
        and trade.attention_reason is not None
        and trade.resolved_at is None
    )


async def _trade_of(db: AsyncSession, order: Order) -> SkinTrade | None:
    """``order``'s trade, read fresh under the order lock the caller holds."""
    return await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order.id)
        .execution_options(populate_existing=True)
    )


async def _refuse_while_unresolved(db: AsyncSession, order: Order) -> None:
    """409 ``order_needs_attention`` while the trade's outcome is unknown or spent (R3)."""
    trade = await _trade_of(db, order)
    if trade is not None and trade.attention_reason in BLOCKS_REFUND and trade.resolved_at is None:
        raise ConflictError("this order waits for an admin's check", code="order_needs_attention")


async def refund_to_balance(
    db: AsyncSession,
    *,
    order: Order,
    to_status: RefundStatus,
    reason: str,
    actor: str,
) -> bool:
    """Refund ``order`` to the buyer's balance and move it to ``to_status``, once.

    Books ``wallet.credit_order_refund`` (balance-paid: the purchase undone; kassa-paid:
    the kassa's money becomes balance), moves the order along the FSM, and stamps
    ``refunded_at``, ``refunded_to="balance"`` and ``failure_reason``. Logs the number,
    amount and reason, never the buyer. Flushes, never commits. Refused while the order's
    trade has an unresolved attention in :data:`BLOCKS_REFUND` (R3: the outcome is unknown
    or the skin may be spent — an admin resolves it first).

    Args:
        db: Session; the caller holds ``order`` ``FOR UPDATE`` and commits.
        order: The order, locked.
        to_status: ``failed`` (nothing reached the buyer) or ``returned`` (the trade came
            back).
        reason: One of ``orders.models.FAILURE_REASONS``.
        actor: Who refunds: ``orders`` for the automatic paths, ``admin:<id>``.

    Returns:
        ``True`` when refunded now; ``False`` when the order was already refunded (nothing
        written).

    Raises:
        ValueError: ``to_status`` or ``reason`` outside their sets — a caller bug.
        ConflictError: ``code="order_not_paid"`` — the order has no payment to give back;
            ``code="order_needs_attention"`` — an unresolved unknown or spent outcome (R3).
            Nothing written.
        InvalidOrderTransitionError: the FSM has no edge to ``to_status``; nothing written.

        On any error the caller must roll back: the order is moved in memory before the
        refund is booked, so a failure after the move leaves the row changed in the session.
    """
    if to_status not in _REFUND_STATUSES:
        raise ValueError(f"to_status {to_status!r} is not a refund status")
    if reason not in FAILURE_REASONS:
        raise ValueError(f"reason {reason!r} is not a failure reason")
    if order.refunded_at is not None:
        return False
    if order.paid_with is None:
        raise ConflictError("this order was never paid", code="order_not_paid")
    await _refuse_while_unresolved(db, order)
    move(order, to_status)
    await credit_order_refund(
        db,
        user_id=order.user_id,
        order_id=order.id,
        amount=order.price_uzs,
        paid_with=order.paid_with,
        actor=actor,
    )
    order.refunded_at = now()
    order.refunded_to = "balance"
    order.failure_reason = reason
    await db.flush()
    await nudge(db, user_id=order.user_id, number=order.number)
    await enqueue_refunded(db, order)
    refund_reason: OrderRefundReason = reason  # type: ignore[assignment] # FAILURE_REASONS
    record_order_refund(refund_reason)
    log.info(
        "orders.refunded",
        number=order.number,
        amount=str(order.price_uzs),
        reason=reason,
        status=to_status,
    )
    return True


__all__ = [
    "ADMIN_REFUNDABLE",
    "BLOCKS_REFUND",
    "RefundStatus",
    "in_flight",
    "refund_to_balance",
]
