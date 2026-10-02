"""The buyer's view of an order's Steam trade, for the order page.

Waxpeer's numbers become five states a customer understands:

* ``buying`` — the skin is being bought and the offer created (paid, no trade yet, or
  Waxpeer status 0–3);
* ``offer_sent`` — the offer is in Steam, accept it before ``send_until`` (4, no
  ``release_date``);
* ``accepted`` — received; Steam's trade protection runs to ``release_date`` (4 with it);
* ``released`` — protection over (5);
* ``failed`` — Waxpeer status 6, or the order ``failed`` / ``returned``.

``reason_code`` says why a trade failed: ``not_accepted`` (declined or expired),
``sold_out`` (nothing left to buy), ``try_later`` (the purchase could not go through for
now — a retry in a few minutes may work), ``support`` (an unresolved attention — a buy we
could not confirm, an ambiguous lookup, a rollback after acceptance, a Waxpeer refusal or an
audit divergence; a person settles it), ``other``. ``support`` shows whatever the state while
the attention is unresolved (ruling R3): the page says «мы проверяем покупку», never a bare
failure and never a refund; once resolved, the order's own ``failure_reason`` speaks.

Whether the money came back is never read off the reason: ``refunded_to`` says where a
refund actually went, from the order, so the page never promises a refund that has not
happened. The seller is shown on purpose: the customer should recognise the offer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import pydantic
from pydantic import BaseModel

from csmarket.modules.orders.models import ATTENTION_REASONS, Order, SkinTrade

SkinTradeState = Literal["buying", "offer_sent", "accepted", "released", "failed"]
SkinTradeReason = Literal["not_accepted", "sold_out", "try_later", "support", "other"]
RefundedTo = Literal["balance"]

#: Attention reasons the buyer reads as «we are checking the purchase» — every one (R3):
#: an outcome waiting for an admin is never shown as a bare failure.
_SUPPORT_REASONS = frozenset(ATTENTION_REASONS)
#: ``orders.failure_reason`` → what the buyer is told.
_FAILURE_REASONS: dict[str, SkinTradeReason] = {
    "waxpeer_low_balance": "try_later",
    "sold_out": "sold_out",
    "not_accepted": "not_accepted",
}
#: Order statuses with no trade to show.
_NO_TRADE = frozenset({"pending", "cancelled"})


class SkinSellerOut(BaseModel):
    """Who the offer comes from."""

    name: str | None = None
    avatar_url: str | None = None
    level: int | None = None
    joined_at: datetime | None = None


class SkinTradeOut(BaseModel):
    """An order's trade, as the buyer sees it."""

    state: SkinTradeState
    reason_code: SkinTradeReason | None = None
    offer_url: str | None = None
    send_until: datetime | None = None
    release_date: datetime | None = None
    seller: SkinSellerOut | None = None
    refunded_to: RefundedTo | None = None


def trade_state(order: Order, trade: SkinTrade | None) -> SkinTradeState:
    """The trade's state as the buyer reads it (also the admin trades list's ``state``)."""
    status = None if trade is None else trade.status
    if status == 6 or order.status in ("failed", "returned"):
        return "failed"
    if trade is not None and (status == 5 or trade.is_released):
        return "released"
    if trade is not None and status == 4:
        return "accepted" if trade.release_date is not None else "offer_sent"
    return "buying"


def _needs_support(trade: SkinTrade | None) -> bool:
    """An unresolved attention the buyer reads as «we are checking the purchase»."""
    return (
        trade is not None
        and trade.resolved_at is None
        and trade.attention_reason in _SUPPORT_REASONS
    )


def _reason(order: Order, trade: SkinTrade | None) -> SkinTradeReason:
    if _needs_support(trade):
        return "support"
    return _FAILURE_REASONS.get(order.failure_reason or "", "other")


# Any: the ``seller`` JSON object as stored (scalar values).
def _seller(raw: dict[str, Any] | None) -> SkinSellerOut | None:
    if not raw or not any(raw.values()):
        return None
    try:
        return SkinSellerOut.model_validate(raw)
    except pydantic.ValidationError:
        # A malformed stored seller must not break the order page; it just is not shown.
        return None


def skin_trade_out(order: Order, trade: SkinTrade | None) -> SkinTradeOut | None:
    """Map an order and its trade mirror to the buyer's view.

    Args:
        order: The order (its status decides ``failed`` and whether there is a trade at all).
        trade: The order's ``skin_trades`` row, ``None`` before the worker took it.

    Returns:
        ``None`` for a ``pending`` or ``cancelled`` order; else the trade as the buyer sees
        it (a ``paid`` order with no trade yet reads ``buying``).
    """
    if order.status in _NO_TRADE:
        return None
    state = trade_state(order, trade)
    reason: SkinTradeReason | None = None
    if state == "failed":
        reason = _reason(order, trade)
    elif _needs_support(trade):
        reason = "support"
    trade_id = None if trade is None else trade.trade_id
    return SkinTradeOut(
        state=state,
        reason_code=reason,
        offer_url=f"https://steamcommunity.com/tradeoffer/{trade_id}/" if trade_id else None,
        send_until=None if trade is None else trade.send_until,
        release_date=None if trade is None else trade.release_date,
        seller=None if trade is None else _seller(trade.seller),
        refunded_to="balance" if order.refunded_to == "balance" else None,
    )


__all__ = [
    "RefundedTo",
    "SkinSellerOut",
    "SkinTradeOut",
    "SkinTradeReason",
    "SkinTradeState",
    "skin_trade_out",
    "trade_state",
]
