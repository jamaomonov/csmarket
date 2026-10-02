"""An order's Waxpeer trade as we keep it: :func:`mirror` a lookup onto ``skin_trades``,
:func:`pick_trade` ours among the trades under one ``project_id``, :func:`apply` what the
trade's status means for the order, and :func:`flag` a trade for an admin.

Shared by the buy (``orders.buying``: a lookup that finds an earlier purchase adopts it) and
the trade sweeps (``orders.sweeps``). Callers hold the order row and then the trade row
``FOR UPDATE`` (ruling K) before anything here writes.

Waxpeer's status → what :func:`apply` does (rulings R1, R3):

=====================================================  ======================================
0, 1, 2, −1 (buying, unparsable)                        nothing (−1 never overwrites a status)
4 without ``release_date`` (offer sent)                 ``buying → trade_sent``
4 with ``release_date``, 5, or ``is_released``          ``buying | trade_sent → delivered``
6 on a delivered order, after acceptance, released,     ``buying | trade_sent → delivered``,
or with penalties                                       then attention ``rolled_back``; the
                                                        money is spent (R3)
6 otherwise (the offer was declined or never sent)      ``returned`` + refund ``not_accepted``
=====================================================  ======================================

A 6 is conclusive only when it is **ours**: :func:`ours` never returns a 6 for a trade whose
Waxpeer id we do not know — it may be a refused attempt under the same ``project_id`` while
our (lost) buy went through.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import TradeAttentionReason, record_trade_attention
from csmarket.modules.orders.fsm import TRANSITIONS, move
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.realtime.api import nudge
from csmarket.modules.skins.api import WaxpeerTrade

log = get_logger("csmarket.orders.trades")

#: Waxpeer's status of a failed or returned trade.
FAILED_STATUS = 6
#: A status we could not parse.
UNPARSABLE_STATUS = -1
#: Waxpeer's status of a sent offer (accepted once ``release_date`` is set).
SENT_STATUS = 4
#: Waxpeer's status of a trade out of Steam's protection (released to the buyer).
RELEASED_STATUS = 5


class AmbiguousTradeError(Exception):
    """Several live trades under our ``project_id`` and no Waxpeer id to tell ours."""


def pick_trade(trades: Sequence[WaxpeerTrade], waxpeer_id: int | None) -> WaxpeerTrade | None:
    """Our trade among those a lookup returned for one ``project_id``.

    Waxpeer keeps a refused attempt under the same ``project_id`` (status 6), so: by
    Waxpeer's id when we know it; else the only trade; else the only one still alive; when
    every one failed, the last.

    Args:
        trades: The lookup's trades for one ``project_id``.
        waxpeer_id: The id the buy answer or an earlier lookup gave us, if any.

    Returns:
        The trade, or ``None`` when there is none (or none with ``waxpeer_id``).

    Raises:
        AmbiguousTradeError: several live trades and no id to choose by.
    """
    if waxpeer_id:
        return next((t for t in trades if t.id == waxpeer_id), None)
    if len(trades) <= 1:
        return trades[0] if trades else None
    live = [t for t in trades if t.status != FAILED_STATUS]
    if len(live) == 1:
        return live[0]
    if not live:
        return trades[-1]
    raise AmbiguousTradeError(f"{len(live)} live trades")


def ours(trades: Sequence[WaxpeerTrade], trade: SkinTrade) -> WaxpeerTrade | None:
    """Our trade among a lookup's, as far as it can settle anything.

    :func:`pick_trade` by the stored Waxpeer id; but a failed (6) trade picked without a
    known id is not taken as ours — it may be a refused attempt under the same
    ``project_id`` while our lost buy went through. Then ``None``: unseen.

    Raises:
        AmbiguousTradeError: several live trades and no id to choose by.
    """
    wt = pick_trade(trades, trade.waxpeer_id)
    if wt is not None and trade.waxpeer_id is None and wt.status == FAILED_STATUS:
        return None
    return wt


# Any: the seller document is a JSON object of scalars.
def _seller(trade: SkinTrade, wt: WaxpeerTrade) -> dict[str, Any]:
    """The stored seller with every non-empty value of ``wt``'s seller laid over it."""
    fresh = {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in wt.seller.model_dump().items()
        if value not in (None, "")
    }
    return {**(trade.seller or {}), **fresh}


def mirror(trade: SkinTrade, wt: WaxpeerTrade) -> None:
    """Copy one Waxpeer trade report onto our row; never blank a known value.

    ``status`` is copied unless it is unparsable (−1) over a known one; ``accepted_at`` is stamped the first time a
    ``release_date`` appears (the buyer accepted the offer); ``is_released`` never goes
    back to false. The caller holds the order and the trade ``FOR UPDATE`` and commits.

    Args:
        trade: Our row, locked.
        wt: Waxpeer's report of the same trade.
    """
    at = now()
    trade.waxpeer_id = wt.id or trade.waxpeer_id
    if wt.status != UNPARSABLE_STATUS or trade.status is None:
        trade.status = wt.status
    trade.trade_id = wt.trade_id or trade.trade_id
    trade.escrow_status = wt.escrow_status or trade.escrow_status
    trade.send_until = wt.send_until or trade.send_until
    if wt.release_date is not None and trade.accepted_at is None:
        trade.accepted_at = at
    trade.release_date = wt.release_date or trade.release_date
    trade.is_released = trade.is_released or wt.is_released
    trade.reason = wt.reason or trade.reason
    trade.penalties = wt.penalties or trade.penalties
    trade.seller = _seller(trade, wt)
    trade.last_polled_at = at
    trade.updated_at = at


def flag(trade: SkinTrade, reason: TradeAttentionReason, *, reopen: bool = False) -> bool:
    """Open attention ``reason`` on ``trade`` unless an open one is already there.

    An open ``waxpeer_forbidden`` (the mildest) gives way to any other reason. A new
    attention never keeps an earlier resolution (it must not look settled), and is counted
    once (``csmarket_trade_attention_total``). A resolved attention with the same reason
    stays resolved unless ``reopen`` — the sweeps see the same Waxpeer state every tick and
    an admin's decision must stand; the buy re-opens a ``waxpeer_forbidden`` on a new 403.

    Args:
        trade: The trade, locked after its order.
        reason: One of ``orders.models.ATTENTION_REASONS``.
        reopen: Re-open a resolved attention with the same reason.

    Returns:
        Whether an attention was opened now.
    """
    open_reason = trade.attention_reason if trade.resolved_at is None else None
    if open_reason is not None and not (
        open_reason == "waxpeer_forbidden" and reason != open_reason
    ):
        return False
    if open_reason is None and trade.attention_reason == reason and not reopen:
        return False
    trade.attention_reason = reason
    trade.resolved_at = trade.resolved_by = trade.resolved_note = None
    trade.updated_at = now()
    record_trade_attention(reason)
    return True


def _spent(order: Order, trade: SkinTrade) -> bool:
    """A failed trade whose skin may have reached the buyer: never refunded by the app."""
    return (
        order.status == "delivered"
        or trade.accepted_at is not None
        or trade.is_released
        or bool(trade.penalties)
    )


async def _returned(db: AsyncSession, order: Order, *, first_seen: bool) -> str:
    """The offer came back unaccepted: ``returned`` and the money to the balance."""
    try:
        await refund_to_balance(
            db, order=order, to_status="returned", reason="not_accepted", actor="orders"
        )
    except ConflictError as exc:
        if exc.extra.get("code") != "order_needs_attention":
            raise
        if first_seen:  # once per order, not every tick while the attention stays open
            log.warning("orders.trade.refund_held", number=order.number)
        return "held"  # an open attention (R3): an admin decides first
    return "returned"


async def _failed(db: AsyncSession, order: Order, trade: SkinTrade, *, first_seen: bool) -> str:
    """Waxpeer 6: the skin may have reached the buyer → ``delivered`` (money spent) and an
    attention; else ``returned`` and the refund."""
    if _spent(order, trade):
        if order.status in ("buying", "trade_sent"):
            move(order, "delivered")
        if flag(trade, "rolled_back"):
            log.error("orders.trade.rolled_back", number=order.number)
        return "rolled_back"
    if order.status not in ("buying", "trade_sent"):
        return "unchanged"
    return await _returned(db, order, first_seen=first_seen)


async def apply(db: AsyncSession, *, order: Order, trade: SkinTrade, wt: WaxpeerTrade) -> str:
    """Mirror Waxpeer's report onto ``trade`` and move ``order`` as the status says.

    See the module docstring for the mapping. A ``returned`` is refunded in the same
    transaction; a refund an open attention blocks (``order_needs_attention``, R3) leaves
    the order as it is (``held``). Flushes nothing itself; never commits.

    Args:
        db: Session; the caller holds ``order``, then ``trade``, ``FOR UPDATE`` and commits.
        order: The order, locked.
        trade: Its trade, locked.
        wt: Waxpeer's report of the trade (picked with :func:`ours`).

    Returns:
        ``unchanged``, ``trade_sent``, ``delivered``, ``returned``, ``rolled_back`` (also
        when the attention was already open) or ``held``.
    """
    outcome = await _apply(db, order=order, trade=trade, wt=wt)
    if outcome in _NUDGED:
        await nudge(db, user_id=order.user_id, number=order.number)
    return outcome


#: Outcomes that change what the buyer sees; a ``returned`` is nudged by its refund.
_NUDGED = frozenset({"trade_sent", "delivered", "rolled_back"})


async def _apply(db: AsyncSession, *, order: Order, trade: SkinTrade, wt: WaxpeerTrade) -> str:
    first_seen = trade.status != FAILED_STATUS
    mirror(trade, wt)
    if wt.status == FAILED_STATUS:
        return await _failed(db, order, trade, first_seen=first_seen)
    accepted = wt.status == SENT_STATUS and trade.release_date is not None
    if accepted or wt.status == RELEASED_STATUS or trade.is_released:
        target = "delivered"
    elif wt.status == SENT_STATUS:
        target = "trade_sent"
    else:
        return "unchanged"
    if target not in TRANSITIONS.get(order.status, frozenset()):
        return "unchanged"  # already there, or settled
    move(order, target)
    return target


__all__ = [
    "FAILED_STATUS",
    "RELEASED_STATUS",
    "SENT_STATUS",
    "UNPARSABLE_STATUS",
    "AmbiguousTradeError",
    "apply",
    "flag",
    "mirror",
    "ours",
    "pick_trade",
]
