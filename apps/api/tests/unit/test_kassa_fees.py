"""The kassa fee: a percent on top, rounded up to whole soʻm (spec 2026-10-14-kassa-fee)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.payments.fees import DEFAULT_KASSA_FEES, KassaFees, fee_of
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("base", "pct", "fee"),
    [
        (Decimal(100000), Decimal(0), Decimal(0)),
        (Decimal(100000), Decimal(1), Decimal(1000)),
        (Decimal(100000), Decimal("1.5"), Decimal(1500)),
        (Decimal(33333), Decimal("1.5"), Decimal(500)),  # 499.995 rounds up
        (Decimal(1), Decimal("0.01"), Decimal(1)),  # any fee is at least a soʻm
    ],
)
def test_fee_is_the_percent_rounded_up(base: Decimal, pct: Decimal, fee: Decimal) -> None:
    assert fee_of(base, pct) == fee


def test_default_is_no_fee_and_unknown_kassas_pay_none() -> None:
    assert DEFAULT_KASSA_FEES.pct("payme") == 0
    fees = KassaFees(click=Decimal(1), payme=Decimal("1.5"), uzum=Decimal(2))
    assert fees.pct("payme") == Decimal("1.5")
    assert fees.pct("mock") == 0
    assert fees.pct("wallet") == 0


@pytest.mark.parametrize("bad", ["-1", "10.01", "1.234"])
def test_rates_are_bounded(bad: str) -> None:
    with pytest.raises(ValidationError):
        KassaFees(click=Decimal(bad), payme=Decimal(0), uzum=Decimal(0))
