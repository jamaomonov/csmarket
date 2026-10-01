"""An order's money back to the balance, exactly once (spec §7.8, rulings R3, R9).

- :func:`refund_to_balance` — the one refund path: the worker and the reconcile sweep (an
  order that ``failed`` or was ``returned``) and the admin refund all book through it. The
  key ``refund:order:{order_id}`` and ``orders.refunded_at`` (read under the order lock)
  make a second call a no-op.
- :func:`in_flight` — whether the order's skin may still reach the buyer, or may already
  have: no refund then (Waxpeer cannot recall an offer we paid for).
- :func:`admin_refund` — the admin's manual refund. ``failed`` and ``returned`` orders are
  refunded automatically, so the only case left is an attention order (R3) whose Waxpeer
  side an operator checked and resolved: nothing was bought.

Imports ``wallet`` and the module's own models and FSM — never ``payments`` (ruling A;
``orders.api`` exports this module).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import OrderRefundReason, record_order_refund
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.models import FAILURE_REASONS, IN_FLIGHT, Order, SkinTrade
from csmarket.modules.wallet.api import credit_order_refund

log = get_logger("csmarket.orders.refunds")

#: The statuses a refund moves an order to; both come with the refund (R1).
RefundStatus = Literal["failed", "returned"]
_REFUND_STATUSES: frozenset[str] = frozenset({"failed", "returned"})
#: Attention reasons under which a ``buying`` order may hold no skin at all — once an
#: operator checked Waxpeer and resolved the trade, an admin may refund it.
ADMIN_REFUNDABLE: frozenset[str] = frozenset(
    {"buy_unconfirmed", "ambiguous_trade", "waxpeer_forbidden"}
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
    amount and reason, never the buyer. Flushes, never commits.

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
        ConflictError: ``code="order_not_paid"`` — the order has no payment to give back.
        InvalidOrderTransitionError: the FSM has no edge to ``to_status``; nothing written.
    """
    if to_status not in _REFUND_STATUSES:
        raise ValueError(f"to_status {to_status!r} is not a refund status")
    if reason not in FAILURE_REASONS:
        raise ValueError(f"reason {reason!r} is not a failure reason")
    if order.refunded_at is not None:
        return False
    if order.paid_with is None:
        raise ConflictError("this order was never paid", code="order_not_paid")
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


async def _locked(db: AsyncSession, number: str) -> tuple[Order, SkinTrade | None]:
    """Order ``number`` locked ``FOR UPDATE`` and its trade (read under that lock).

    Raises:
        NotFoundError: malformed, a top-up's, or unknown.
    """
    if not is_number(number) or is_topup_number(number):
        raise NotFoundError("order not found")
    order = await db.scalar(
        select(Order)
        .where(Order.number == number)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise NotFoundError("order not found")
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    return order, trade


def _admin_refundable(order: Order, trade: SkinTrade | None) -> bool:
    """A ``buying`` order an operator found nothing bought for (see :data:`ADMIN_REFUNDABLE`)."""
    return (
        order.status == "buying"
        and trade is not None
        and trade.attention_reason in ADMIN_REFUNDABLE
        and trade.resolved_at is not None
    )


async def admin_refund(db: AsyncSession, *, number: str, admin_id: str) -> Order:
    """An admin refunds order ``number`` to the balance (``failed``, reason ``admin``).

    Only a ``buying`` order whose trade carries ``buy_unconfirmed``, ``ambiguous_trade`` or
    ``waxpeer_forbidden`` **and** was resolved (an operator checked Waxpeer: nothing was
    bought). Flushes, never commits: the caller writes its audit row in the same
    transaction.

    Args:
        db: Session; the order is locked here.
        number: The order's public number.
        admin_id: The admin's user id (booked as actor ``admin:<id>``, never logged).

    Returns:
        The refunded order.

    Raises:
        NotFoundError: no such order.
        ConflictError: ``already_refunded``; ``order_in_flight`` — the skin may be on its
            way or delivered (:func:`in_flight`), or the attention is unresolved or not a
            "nothing bought" case; ``order_not_refundable`` — settled with nothing to give
            back (unpaid, cancelled, delivered).
    """
    order, trade = await _locked(db, number)
    if order.refunded_at is not None:
        raise ConflictError("this order was already refunded", code="already_refunded")
    if not _admin_refundable(order, trade):
        if in_flight(order, trade):
            raise ConflictError("the skin may still reach the buyer", code="order_in_flight")
        raise ConflictError("this order has nothing to refund", code="order_not_refundable")
    await refund_to_balance(
        db, order=order, to_status="failed", reason="admin", actor=f"admin:{admin_id}"
    )
    return order


__all__ = ["ADMIN_REFUNDABLE", "RefundStatus", "admin_refund", "in_flight", "refund_to_balance"]
