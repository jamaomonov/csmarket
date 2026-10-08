"""An offer's float as an order stores it, and as the order page shows it."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.orders.checkout import _float_of
from csmarket.modules.orders.service import _plain


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        (None, None),
        (0.62140001, Decimal("0.621400")),
        (0.0000004, Decimal("0.000000")),
        (1.0, Decimal("1.000000")),
        (1.5, None),
        (-0.1, None),
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_the_stored_float(raw: float | None, stored: Decimal | None) -> None:
    assert _float_of(raw) == stored


@pytest.mark.parametrize(
    ("stored", "wire"),
    [
        (None, None),
        (Decimal("0.621400"), "0.6214"),
        (Decimal("0.000000"), "0"),
        (Decimal("1.000000"), "1"),
        (Decimal("0.000010"), "0.00001"),
    ],
)
def test_the_wire_float(stored: Decimal | None, wire: str | None) -> None:
    assert _plain(stored) == wire
