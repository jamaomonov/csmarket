"""The buy's judgement calls (``orders.buying``, rulings R4, R6): was the answer lost, does a
refusal name our key or Waxpeer's service, the buyer's trade link, is it low balance."""

from __future__ import annotations

import json

from csmarket.modules.skins.api import (
    TradeClient,
    WaxpeerError,
    WaxpeerUnavailableError,
)
from csmarket.modules.users.api import SERVICE_HINTS

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
    "inventory public",
    "trade ban",
    "cannot trade",
    "can't trade",
    "can not trade",
)
_BUYER_WORDS = ("buyer", "your", "partner", "receiver", "recipient")


def answer_lost(err: WaxpeerError) -> bool:
    """The buy's answer does not prove nothing was bought: a 5xx, a 408, or any other HTTP
    error whose body is not Waxpeer's JSON (a proxy's or Cloudflare's page). Resolved by
    lookup, never refunded on the spot (ORD-3). A 200 ``success: false`` and Waxpeer's
    own JSON 4xx are refusals.
    """
    if err.status >= 500 or err.status == 408:
        return True
    if err.status == 200:
        return False
    try:
        json.loads(err.body)
    except ValueError:
        return True
    return False


def service_refused(err: WaxpeerError) -> bool:
    """The refusal names our key or Waxpeer's service («Wrong api key», «Internal server
    error»), the trade-link check's words (WAX-04): not the listing — refunding it «sold
    out» would fail every order until someone notices (final review M-6). Matched on the
    message only: a body may echo an item name."""
    text = str(err).lower()
    return any(hint in text for hint in SERVICE_HINTS)


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


__all__ = ["answer_lost", "link_refused", "low_balance", "service_refused"]
