"""Sale pricing (spec 2026-10-08 §3): brackets, the raw CBU rate, every soʻm figure down to 100."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.sales.pricing import (
    ItemQuote,
    Payout,
    floor_100,
    min_prices,
    min_sum_uzs,
    payout_for,
    quote_item,
    sale_rate,
)
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, SaleSettings
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

RATE = Decimal("12650.5")
S = DEFAULT_SALE_SETTINGS


def test_floor_100_rounds_down() -> None:
    assert [floor_100(Decimal(x)) for x in ("149611.13", "100", "99.99", "0")] == [
        Decimal(149_600),
        Decimal(100),
        Decimal(0),
        Decimal(0),
    ]


@pytest.mark.parametrize(
    ("usd", "uzs", "margin"),
    [
        ("12.45", 149_600, "0.6235"),
        ("0.5", 5_600, "0.05"),
        ("1.00", 11_300, "0.1"),
        ("250", 3_083_500, "6.25"),
    ],
)
def test_an_item_is_priced_through_the_progressive_brackets(
    usd: str, uzs: int, margin: str
) -> None:
    assert quote_item(Decimal(usd), S, RATE) == ItemQuote(
        price_uzs=Decimal(uzs), margin_usd=Decimal(margin)
    )


def test_a_cent_item_can_price_to_zero() -> None:
    assert quote_item(Decimal("0.005"), S, RATE).price_uzs == 0


def test_the_rate_is_the_cbu_rate_less_the_cut_rounded_down() -> None:
    assert sale_rate(RATE, S) == Decimal("12650.5000")
    cut = S.model_copy(update={"rate_cut_pct": Decimal("1")})
    assert sale_rate(RATE, cut) == Decimal("12523.9950")


def test_the_balance_gets_the_bonus_rounded_down() -> None:
    assert payout_for(Decimal(155_200), S, to="balance", card_type=None) == Payout(
        items_uzs=Decimal(155_200),
        bonus_uzs=Decimal(3_100),
        fee_uzs=Decimal(0),
        payout_uzs=Decimal(158_300),
    )


def test_a_card_pays_its_type_fee_rounded_down() -> None:
    assert payout_for(Decimal(155_200), S, to="card", card_type="humo") == Payout(
        items_uzs=Decimal(155_200),
        bonus_uzs=Decimal(0),
        fee_uzs=Decimal(7_800),
        payout_uzs=Decimal(147_400),
    )


def test_a_card_payout_needs_a_card_type() -> None:
    with pytest.raises(ValueError, match="card type"):
        payout_for(Decimal(155_200), S, to="card", card_type=None)


def test_min_prices_are_99_percent_rounded_down_to_a_tenth_of_a_cent() -> None:
    assert min_prices([("100", Decimal("12.45")), ("101", Decimal("0.5"))]) == {
        "100": Decimal("12.325"),
        "101": Decimal("0.495"),
    }


def test_the_minimum_in_soum_is_the_minimum_priced_as_an_item() -> None:
    # 1.10 $ − (0.10 + 0.005) margin = 0.995 $ × 12650.5 = 12 587.25 → 12 500
    assert min_sum_uzs(S, RATE) == Decimal(12_500)


def test_the_defaults_ship_switched_off() -> None:
    assert S.enabled is False
    assert (S.card_min_uzs, S.min_sum_usd, S.balance_bonus_pct) == (
        30_000,
        Decimal("1.10"),
        Decimal(2),
    )


@pytest.mark.parametrize(
    "margin",
    [
        [{"from_usd": "1", "percent": "10"}],
        [{"from_usd": "0", "percent": "10"}, {"from_usd": "0", "percent": "5"}],
        [{"from_usd": "0", "percent": "100"}],
        [{"from_usd": "0", "percent": "-1"}],
    ],
)
def test_a_bad_margin_table_is_refused(margin: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError):
        SaleSettings.model_validate({**S.model_dump(mode="json"), "margin": margin})


@pytest.mark.parametrize("minimum", ["0.5", "1"])
def test_a_minimum_not_above_skinslinks_one_dollar_is_refused(minimum: str) -> None:
    """Skinslink refuses a deposit of exactly 1 $ (400 ``gt``)."""
    with pytest.raises(ValidationError):
        SaleSettings.model_validate({**S.model_dump(mode="json"), "min_sum_usd": minimum})


@given(
    usd=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(20_000), places=3),
    rate=st.decimals(min_value=Decimal(9_000), max_value=Decimal(15_000), places=2),
)
def test_an_item_never_pays_more_than_skinslink_pays_us(usd: Decimal, rate: Decimal) -> None:
    q = quote_item(usd, S, rate)
    assert q.price_uzs % 100 == 0
    assert 0 <= q.price_uzs <= usd * rate
    assert q.margin_usd > 0


@given(
    low=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(5_000), places=2),
    step=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(5_000), places=2),
)
def test_a_dearer_item_never_prices_lower(low: Decimal, step: Decimal) -> None:
    assert quote_item(low + step, S, RATE).price_uzs >= quote_item(low, S, RATE).price_uzs


@given(items=st.integers(min_value=0, max_value=10_000_000).map(lambda n: Decimal(n * 100)))
def test_payouts_are_whole_hundreds_and_cards_never_get_more_than_the_items(
    items: Decimal,
) -> None:
    balance = payout_for(items, S, to="balance", card_type=None)
    card = payout_for(items, S, to="card", card_type="uzum_visa")
    assert balance.payout_uzs % 100 == 0
    assert card.payout_uzs % 100 == 0
    assert card.payout_uzs <= items <= balance.payout_uzs
    assert card.payout_uzs + card.fee_uzs == items
