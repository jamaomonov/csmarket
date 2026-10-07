"""The buy's judgement calls (``orders.buying``, rulings R4, R6): does a refusal name the
buyer's trade link, is it low balance, and which listing may replace a refused one."""

from __future__ import annotations

from csmarket.modules.skins.api import (
    TradeClient,
    WaxpeerError,
    WaxpeerUnavailableError,
)

_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")
#: Waxpeer's words for a refusal caused by the buyer's trade link (as its ``check-tradelink``
#: answers: "Invalid tradelink", "Inventory is private", a trade ban). Matched on the
#: message only — a body may echo the link back on any refusal. The link phrases name the
#: buyer's link outright; the account phrases could be about the seller too, so they count
#: only when the message also names the buyer (M4b ruling R12/Z2).
_LINK_PHRASES = ("tradelink", "trade link", "trade url")
_ACCOUNT_HINTS = (
    "inventory is private",
    "private inventory",
    "trade ban",
    "cannot trade",
    "can't trade",
    "can not trade",
)
_BUYER_WORDS = ("buyer", "your", "partner", "receiver", "recipient")


def link_refused(err: WaxpeerError) -> bool:
    """Waxpeer refused the buy because of the buyer's trade link: another listing would be
    refused the same way, so the order is refunded (``invalid_trade_link``), not sold out.

    A seller-side refusal ("Seller cannot trade") is a refused listing, not the buyer's link.
    """
    text = str(err).lower()
    if any(phrase in text for phrase in _LINK_PHRASES):
        return True
    return any(hint in text for hint in _ACCOUNT_HINTS) and any(
        word in text for word in _BUYER_WORDS
    )


async def low_balance(client: TradeClient, err: WaxpeerError, units: int) -> bool:
    """Waxpeer named low balance, or our Waxpeer wallet holds less than ``units``.

    A balance call that fails counts as "not low": the refusal then reads as sold.
    """
    text = f"{err} {err.body}".lower()
    if any(hint in text for hint in _LOW_BALANCE_HINTS):
        return True
    try:
        return await client.balance_units() < units
    except (WaxpeerError, WaxpeerUnavailableError):
        return False


__all__ = ["link_refused", "low_balance"]
