"""``orders.costing.spent``: the market's charge once it says, the agreed cost until then."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from csmarket.modules.orders.costing import spent


def _order(cost: str) -> Any:  # Any: a stand-in carrying only ``cost_usd``
    return SimpleNamespace(cost_usd=Decimal(cost))


def test_the_market_charge_wins_over_the_agreed_cost() -> None:
    assert spent(_order("9"), SimpleNamespace(bought_units=8_200), None) == Decimal("8.2")  # type: ignore[arg-type]
    assert spent(_order("9"), None, SimpleNamespace(amount_units=8_500)) == Decimal("8.5")  # type: ignore[arg-type]


def test_the_agreed_cost_stands_until_the_market_says() -> None:
    assert spent(_order("9"), SimpleNamespace(bought_units=None), None) == Decimal("9")  # type: ignore[arg-type]
    assert spent(_order("9"), None, SimpleNamespace(amount_units=None)) == Decimal("9")  # type: ignore[arg-type]
