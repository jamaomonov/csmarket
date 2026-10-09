"""The ledger balances per currency (spec 2026-10-09 §3)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.wallet.service import KIND_CURRENCY, NORMAL_SIDE, Leg, _validate_legs
from hypothesis import given
from hypothesis import strategies as st

UZS = {"a": "UZS", "b": "UZS"}
MIXED = {"a": "UZS", "b": "USD", "c": "UZS", "d": "USD"}


def test_every_kind_has_a_currency_and_a_normal_side() -> None:
    assert set(KIND_CURRENCY) == set(NORMAL_SIDE)
    assert KIND_CURRENCY["user_wallet"] == "UZS"
    assert KIND_CURRENCY["user_wallet_usd"] == "USD"
    assert {KIND_CURRENCY["house_fx_uzs"], KIND_CURRENCY["house_fx_usd"]} == {"UZS", "USD"}


def test_a_pair_per_currency_balances() -> None:
    legs = [
        Leg("a", "C", Decimal(12_651)),
        Leg("c", "D", Decimal(12_651)),
        Leg("b", "D", Decimal(1000)),
        Leg("d", "C", Decimal(1000)),
    ]
    _validate_legs(legs, MIXED)


def test_balanced_overall_but_not_per_currency_is_refused() -> None:
    legs = [Leg("a", "D", Decimal(1000)), Leg("b", "C", Decimal(1000))]
    with pytest.raises(ValidationError, match="per currency"):
        _validate_legs(legs, {"a": "UZS", "b": "USD"})


def test_without_currencies_the_old_single_pool_rule_holds() -> None:
    _validate_legs([Leg("a", "D", Decimal(5)), Leg("b", "C", Decimal(5))])
    with pytest.raises(ValidationError):
        _validate_legs([Leg("a", "D", Decimal(5)), Leg("b", "C", Decimal(4))], UZS)


@given(
    uzs=st.integers(min_value=1, max_value=10**12),
    usd=st.integers(min_value=1, max_value=10**12),
)
def test_any_two_balanced_pairs_pass(uzs: int, usd: int) -> None:
    legs = [
        Leg("a", "C", Decimal(uzs)),
        Leg("c", "D", Decimal(uzs)),
        Leg("b", "D", Decimal(usd)),
        Leg("d", "C", Decimal(usd)),
    ]
    _validate_legs(legs, MIXED)
