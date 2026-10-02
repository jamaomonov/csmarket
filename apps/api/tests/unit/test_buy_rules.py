"""``buy_rules.link_refused``: only a refusal that names the buyer's link refunds the order as
``invalid_trade_link`` (M4b ruling R12/Z2)."""

from __future__ import annotations

import pytest
from csmarket.modules.orders.buy_rules import link_refused
from csmarket.modules.skins.api import WaxpeerError


@pytest.mark.parametrize(
    "message",
    [
        "Invalid tradelink",
        "Bad trade link",
        "trade url is broken",
        "Your inventory is private",
        "Buyer has a trade ban",
        "partner cannot trade",
    ],
)
def test_buyer_link_refusals_are_recognised(message: str) -> None:
    assert link_refused(WaxpeerError(message))


@pytest.mark.parametrize(
    "message",
    [
        "Seller cannot trade right now",
        "Item owner has a trade ban",
        "inventory is private",
        "Price changed",
    ],
)
def test_seller_side_or_unscoped_refusals_are_not_the_buyers_link(message: str) -> None:
    assert not link_refused(WaxpeerError(message))
