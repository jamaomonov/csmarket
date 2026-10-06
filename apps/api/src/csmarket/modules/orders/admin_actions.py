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

**The refund asks Waxpeer first** (ADR-0007, the admin carve-out): a refund is the one place
the system could hand out both the skin and the money, so :func:`admin_refund` reads the
order unlocked, ends the transaction, looks its ``project_id`` up at Waxpeer
(:data:`REFUND_LOOKUP_SECONDS`), and only then locks and re-checks — no lock and no open
transaction across the call. A live trade, or one that was ever accepted, refuses the
refund (``order_in_flight``); a lookup that fails refuses it too (``waxpeer_unavailable``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.refunds import ADMIN_REFUNDABLE, in_flight, refund_to_balance
from csmarket.modules.orders.sweep_base import LOOKUP_ERRORS, of_project
from csmarket.modules.orders.trades import FAILED_STATUS
from csmarket.modules.skins.api import TradeClient, WaxpeerTrade
from csmarket.modules.skinslink.api import SkinslinkPurchase

log = get_logger("csmarket.orders.admin")

#: How long an admin refund waits for Waxpeer's lookup before refusing
#: (``waxpeer_unavailable``) — the request path's 4 s (AGENTS §11).
REFUND_LOOKUP_SECONDS = 4.0

#: Attention reasons after which a resolved ``buying`` order may be bought again: the
#: next attempt looks the ``project_id`` up first, so a buy Waxpeer did make is adopted.
RETRYABLE: frozenset[str] = frozenset({"buy_unconfirmed", "ambiguous_trade", "source_forbidden"})

#: 409 codes of the admin actions → the problem's ``detail``.
CONFLICTS: dict[str, str] = {
    "already_refunded": "this order was already refunded",
    "order_in_flight": "the skin may still reach the buyer",
    "order_not_refundable": "this order has nothing to refund",
    "order_busy": "a buy attempt is running for this order; try again in a few minutes",
    "not_retryable": "this order's buy cannot be retried now",
    "nothing_to_resolve": "this order's trade has no attention to resolve",
    "waxpeer_unavailable": "the purchase could not be checked at Waxpeer; try again later",
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
    nothing was bought), not refunded yet, with no purchase on record that is not
    conclusively our failed trade (``waxpeer_id`` set and Waxpeer status ≠ 6 — the skin may
    still arrive; the same guard as :func:`retry_refusal`), no buy answer lost after the
    operator's check, with no buy attempt running.
    """
    if order.refunded_at is not None:
        return "already_refunded"
    if not (order.status == "buying" and _resolved_in(trade, ADMIN_REFUNDABLE)):
        return "order_in_flight" if in_flight(order, trade) else "order_not_refundable"
    if trade is not None and trade.waxpeer_id is not None and trade.status != FAILED_STATUS:
        return "order_in_flight"
    if _lost_after_resolve(trade):
        return "order_in_flight"
    if buy_running(order, trade, at):
        return "order_busy"
    return None


def _lost_after_resolve(trade: SkinTrade | None) -> bool:
    """A buy whose answer was lost **after** the operator resolved the attention: they checked
    a Waxpeer that has changed since, so their check no longer covers it (ruling Z)."""
    return (
        trade is not None
        and trade.buy_unconfirmed_at is not None
        and (trade.resolved_at is None or trade.buy_unconfirmed_at > trade.resolved_at)
    )


def retry_refusal(order: Order, trade: SkinTrade | None, at: datetime) -> str | None:
    """Why an admin may not retry ``order``'s buy now (a 409 code), or ``None``.

    Only a ``buying``, unrefunded order whose trade carries a **resolved** attention in
    :data:`RETRYABLE`, has no purchase on record (``waxpeer_id`` unset — a bought trade that
    stopped being reported is ``ambiguous_trade`` too, and a retry would buy it twice), with
    no buy attempt running.
    """
    if order.status != "buying" or order.refunded_at is not None:
        return "not_retryable"
    if not _resolved_in(trade, RETRYABLE) or (trade is not None and trade.waxpeer_id is not None):
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


async def _read_refundable(db: AsyncSession, number: str) -> str:
    """Order ``number``'s id if :func:`refund_refusal` passes on an unlocked read; the read
    transaction is ended either way (nothing is held while Waxpeer answers).

    Raises:
        NotFoundError: malformed, a top-up's, or unknown.
        ConflictError: the refusal's code.
    """
    if not is_number(number) or is_topup_number(number):
        raise NotFoundError("order not found")
    order = await db.scalar(
        select(Order).where(Order.number == number).execution_options(populate_existing=True)
    )
    trade = (
        None
        if order is None
        else await db.scalar(
            select(SkinTrade)
            .where(SkinTrade.order_id == order.id)
            .execution_options(populate_existing=True)
        )
    )
    code = None if order is None else refund_refusal(order, trade, now())
    order_id = None if order is None else order.id
    await db.commit()  # nothing written: the read transaction ends before Waxpeer is asked
    if order_id is None:
        raise NotFoundError("order not found")
    if code is not None:
        raise _conflict(code)
    return order_id


def _purchase_seen(trades: Sequence[WaxpeerTrade]) -> bool:
    """A trade under the order's ``project_id`` is live (status ≠ 6) or was ever accepted."""
    return any(
        t.status != FAILED_STATUS or t.release_date or t.penalties or t.is_released for t in trades
    )


async def _ask_waxpeer(client: TradeClient, *, order_id: str, number: str) -> None:
    """Refuse the refund unless Waxpeer shows no purchase that may reach the buyer.

    Raises:
        ConflictError: ``order_in_flight`` — a live or once-accepted trade under the
            ``project_id``; ``waxpeer_unavailable`` — the lookup failed or timed out.
    """
    try:
        async with asyncio.timeout(REFUND_LOOKUP_SECONDS):
            trades = of_project(await client.check_project_ids([order_id]), order_id)
    except (*LOOKUP_ERRORS, TimeoutError) as exc:
        log.warning("orders.admin_refund.lookup_failed", number=number, error=type(exc).__name__)
        raise _conflict("waxpeer_unavailable") from None
    if _purchase_seen(trades):
        log.warning("orders.admin_refund.purchase_seen", number=number, trades=len(trades))
        raise _conflict("order_in_flight")


async def admin_refund(
    db: AsyncSession, *, number: str, admin_id: str, client: TradeClient
) -> Order:
    """An admin refunds order ``number`` to the balance (``failed``, reason ``admin``).

    Lookup first (ADR-0007): an unlocked read refuses early (:func:`refund_refusal`) and
    ends the transaction; Waxpeer is asked for every trade under the order's
    ``project_id`` with no lock and no transaction open; then the order and its trade are
    locked, the refusal is checked again (the rows may have moved meanwhile), ``buy_pending``
    is turned off (no new attempt may start) and ``refund_to_balance`` books the refund.
    Flushes, never commits; returns with the locks held.

    Args:
        db: Session; the order and its trade are locked here.
        number: The order's public number.
        admin_id: The admin's user id (booked as actor ``admin:<id>``, never logged).
        client: Waxpeer, for the one lookup (the request path's 4 s client).

    Returns:
        The refunded order.

    Raises:
        NotFoundError: no such order.
        ConflictError: ``already_refunded``; ``order_in_flight`` — the skin may be on its
            way or delivered (a purchase on record or at Waxpeer that is not a failed trade
            never accepted), or the attention is unresolved or not a "nothing bought" case;
            ``order_not_refundable`` — settled with nothing to give back (unpaid, cancelled,
            delivered); ``order_busy`` — a buy attempt holds the order;
            ``waxpeer_unavailable`` — Waxpeer could not be asked.
    """
    order_id = await _read_refundable(db, number)
    await _ask_waxpeer(client, order_id=order_id, number=number)
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
    """An admin marks order ``number``'s trade (or Skinslink purchase) attention as checked
    («Разобрано»).

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
    order, waxpeer_trade = await lock_order(db, number)
    trade: SkinTrade | SkinslinkPurchase | None = waxpeer_trade
    if trade is None:  # a Skinslink order keeps its attention on the purchase
        trade = await db.scalar(
            select(SkinslinkPurchase)
            .where(SkinslinkPurchase.order_id == order.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
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
    "REFUND_LOOKUP_SECONDS",
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
