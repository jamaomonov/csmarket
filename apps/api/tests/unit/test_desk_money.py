"""``desk.money``: soʻm to dollars and the price split (spec 2026-10-29-desk)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.desk.money import split_cost, split_revenue, to_usd
from hypothesis import given
from hypothesis import strategies as st


def test_usd_is_kept() -> None:
    assert to_usd(Decimal("1100"), "USD", None) == Decimal("1100.000000")


@pytest.mark.parametrize("rate", [None, Decimal(0), Decimal(-1)])
def test_uzs_needs_a_rate(rate: Decimal | None) -> None:
    with pytest.raises(ValidationError) as exc:
        to_usd(Decimal(1_300_000), "UZS", rate)
    assert exc.value.extra["code"] == "rate_required"


def test_uzs_divides_by_the_rate() -> None:
    assert to_usd(Decimal(1_300_000), "UZS", Decimal("13000")) == Decimal("100.000000")


def test_split_is_proportional() -> None:
    assert split_cost(Decimal("1100"), [Decimal("800"), Decimal("400")]) == [
        Decimal("733.333333"),
        Decimal("366.666667"),
    ]


def test_unpriced_item_takes_the_mean() -> None:
    assert split_cost(Decimal("90"), [Decimal("10"), None, Decimal("20")]) == [
        Decimal("20.000000"),
        Decimal("30.000000"),
        Decimal("40.000000"),
    ]


def test_no_prices_split_evenly() -> None:
    assert split_cost(Decimal("10"), [None, None, None]) == [
        Decimal("3.333333"),
        Decimal("3.333333"),
        Decimal("3.333334"),
    ]


def test_revenue_splits_the_same_way() -> None:
    assert split_revenue(Decimal("1200"), [Decimal("800"), Decimal("400")]) == [
        Decimal("800.000000"),
        Decimal("400.000000"),
    ]


_money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2)


@given(total=_money, weights=st.lists(st.one_of(st.none(), _money), min_size=1, max_size=30))
def test_split_always_sums_to_the_total(total: Decimal, weights: list[Decimal | None]) -> None:
    shares = split_cost(total, weights)
    assert len(shares) == len(weights)
    assert sum(shares) == total.quantize(Decimal("0.000001"))
