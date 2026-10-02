"""What an admin may do to an order: resolve its trade's attention, refund it to the balance,
retry its buy (spec §13, rulings R3, K, M).

Each action locks the order row, then its trade (ruling K), re-checks under the locks and
flushes — never commits: the admin route writes its audit row and replay in the same
transaction. Whether refund and retry are allowed is one function each
(:func:`refund_refusal`, :func:`retry_refusal`), used by the admin detail
(``can_refund`` / ``can_retry``) and by the actions themselves, so the button and the
action never disagree.

**The buy lease.** While an attempt holds the order (``buy_pending`` and ``next_check_at`` in
the future, ``orders.buy_lease``) a Waxpeer buy may be on the wire: refund and retry answer
409 ``order_busy``. A refund also turns ``buy_pending`` off under the order lock, so no new
attempt can start after it (``take_lease`` needs the row lock and a ``buying`` order).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.refunds import ADMIN_REFUNDABLE, in_flight, refund_to_balance

#: Attention reasons after which a resolved ``buying`` order may be bought again: the
#: next attempt looks the ``project_id`` up first, so a buy Waxpeer did make is adopted.
RETRYABLE: frozenset[str] = frozenset({"buy_unconfirmed", "ambiguous_trade", "waxpeer_forbidden"})

#: 409 codes of the admin actions → the problem's ``detail``.
CONFLICTS: dict[str, str] = {
    "already_refunded": "this order was already refunded",
    "order_in_flight": "the skin may still reach the buyer",
    "order_not_refundable": "this order has nothing to refund",
    "order_busy": "a buy attempt is running for this order; try again in a few minutes",
    "not_retryable": "this order's buy cannot be retried now",
    "nothing_to_resolve": "this order's trade has no attention to resolve",
}


def _conflict(code: str) -> ConflictError:
    return ConflictError(CONFLICTS[code], code=code)


async def lock_order(db: AsyncSession, number: str) -> tuple[Order, SkinTrade | None]:
    """Order ``number``, then its trade, ``FOR UPDATE`` (ruling K), read fresh.

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
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, trade


def buy_running(order: Order, trade: SkinTrade | None, at: datetime) -> bool:
    """An attempt may hold the order's buy lease: ``buy_pending`` and ``next_check_at > at``."""
    return (
        trade is not None
        and trade.buy_pending
        and order.next_check_at is not None
        and order.next_check_at > at
    )


def _resolved_in(trade: SkinTrade | None, reasons: frozenset[str]) -> bool:
    return trade is not None and trade.attention_reason in reasons and trade.resolved_at is not None


def refund_refusal(order: Order, trade: SkinTrade | None, at: datetime) -> str | None:
    """Why an admin may not refund ``order`` now (a 409 code), or ``None`` when they may.

    Only a ``buying`` order whose trade carries a **resolved** attention in
    :data:`~csmarket.modules.orders.refunds.ADMIN_REFUNDABLE` (an operator checked Waxpeer:
    nothing was bought), not refunded yet, with no buy attempt running.
    """
    if order.refunded_at is not None:
        return "already_refunded"
    if not (order.status == "buying" and _resolved_in(trade, ADMIN_REFUNDABLE)):
        return "order_in_flight" if in_flight(order, trade) else "order_not_refundable"
    if buy_running(order, trade, at):
        return "order_busy"
    return None


def retry_refusal(order: Order, trade: SkinTrade | None, at: datetime) -> str | None:
    """Why an admin may not retry ``order``'s buy now (a 409 code), or ``None``.

    Only a ``buying``, unrefunded order whose trade carries a **resolved** attention in
    :data:`RETRYABLE`, with no buy attempt running.
    """
    if order.status != "buying" or order.refunded_at is not None:
        return "not_retryable"
    if not _resolved_in(trade, RETRYABLE):
        return "not_retryable"
    if buy_running(order, trade, at):
        return "order_busy"
    return None


def can_refund(order: Order, trade: SkinTrade | None, at: datetime | None = None) -> bool:
    """Whether :func:`admin_refund` would refund ``order`` now (the detail's ``can_refund``)."""
    return refund_refusal(order, trade, at or now()) is None


def can_retry(order: Order, trade: SkinTrade | None, at: datetime | None = None) -> bool:
    """Whether :func:`retry_buy` would retry ``order`` now (the detail's ``can_retry``)."""
    return retry_refusal(order, trade, at or now()) is None


async def admin_refund(db: AsyncSession, *, number: str, admin_id: str) -> Order:
    """An admin refunds order ``number`` to the balance (``failed``, reason ``admin``).

    Under the locks: refused unless :func:`refund_refusal` passes; then ``buy_pending`` is
    turned off (no new attempt may start) and ``refund_to_balance`` books the refund.
    Flushes, never commits.

    Args:
        db: Session; the order and its trade are locked here.
        number: The order's public number.
        admin_id: The admin's user id (booked as actor ``admin:<id>``, never logged).

    Returns:
        The refunded order.

    Raises:
        NotFoundError: no such order.
        ConflictError: ``already_refunded``; ``order_in_flight`` — the skin may be on its
            way or delivered, or the attention is unresolved or not a "nothing bought" case;
            ``order_not_refundable`` — settled with nothing to give back (unpaid, cancelled,
            delivered); ``order_busy`` — a buy attempt holds the order.
    """
    order, trade = await lock_order(db, number)
    at = now()
    code = refund_refusal(order, trade, at)
    if code is not None or trade is None:  # no refusal implies a trade; mypy needs the test
        raise _conflict(code or "order_not_refundable")
    trade.buy_pending = False
    trade.updated_at = at
    await db.flush()
    await refund_to_balance(
        db, order=order, to_status="failed", reason="admin", actor=f"admin:{admin_id}"
    )
    return order


async def retry_buy(db: AsyncSession, *, number: str, admin_id: str) -> str:
    """An admin sends order ``number``'s buy round again after resolving its attention.

    Clears ``attention_reason``, ``buy_unconfirmed_at`` and ``resolved_*``, sets
    ``buy_pending`` and makes the order due now: the reconcile sweep's next attempt looks
    the ``project_id`` up first, so a purchase Waxpeer did make is adopted, never repeated.
    Flushes, never commits.

    Args:
        db: Session; the order and its trade are locked here.
        number: The order's public number.
        admin_id: The admin's user id (unused in the row; the caller audits it).

    Returns:
        The attention reason the retry cleared (for the audit row).

    Raises:
        NotFoundError: no such order.
        ConflictError: ``not_retryable``, or ``order_busy`` — a buy attempt holds the order.
    """
    del admin_id  # the audit row names the admin
    order, trade = await lock_order(db, number)
    at = now()
    code = retry_refusal(order, trade, at)
    if code is not None or trade is None:  # no refusal implies a trade; mypy needs the test
        raise _conflict(code or "not_retryable")
    reason = str(trade.attention_reason)
    trade.attention_reason = None
    trade.buy_unconfirmed_at = None
    trade.resolved_at = trade.resolved_by = trade.resolved_note = None
    trade.buy_pending = True
    trade.updated_at = at
    order.next_check_at = at
    order.updated_at = at
    await db.flush()
    return reason


async def resolve_attention(
    db: AsyncSession, *, number: str, admin_id: str, note: str | None
) -> str | None:
    """An admin marks order ``number``'s trade attention as checked («Разобрано»).

    Sets ``resolved_at``, ``resolved_by`` (the admin's id) and ``resolved_note`` once: an
    attention already resolved is left as it is. Flushes, never commits.

    Args:
        db: Session; the order and its trade are locked here.
        number: The order's public number.
        admin_id: The admin's user id.
        note: What the operator found (≤ 500 characters), or ``None``.

    Returns:
        The attention reason resolved now, or ``None`` when it was already resolved.

    Raises:
        NotFoundError: no such order.
        ConflictError: ``nothing_to_resolve`` — no trade, or no attention on it.
    """
    _, trade = await lock_order(db, number)
    if trade is None or trade.attention_reason is None:
        raise _conflict("nothing_to_resolve")
    if trade.resolved_at is not None:
        return None
    at = now()
    trade.resolved_at, trade.resolved_by, trade.resolved_note = at, admin_id, note
    trade.updated_at = at
    await db.flush()
    return trade.attention_reason


__all__ = [
    "CONFLICTS",
    "RETRYABLE",
    "admin_refund",
    "buy_running",
    "can_refund",
    "can_retry",
    "lock_order",
    "refund_refusal",
    "resolve_attention",
    "retry_buy",
    "retry_refusal",
]
