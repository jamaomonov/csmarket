"""Card checks: 16 digits, the type's prefix, Luhn; a refusal never says the number."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.sales.cards import card_digits, luhn_ok, masked

HUMO = "9860123456789015"
UZCARD = "8600123456789012"
VISA = "4000000000000002"


@pytest.mark.parametrize("number", [HUMO, UZCARD, VISA])
def test_luhn_accepts_the_fake_cards(number: str) -> None:
    assert luhn_ok(number)


def test_luhn_refuses_a_typo() -> None:
    assert not luhn_ok("9860123456789016")


@pytest.mark.parametrize(
    ("card_type", "raw", "digits"),
    [
        ("humo", "9860 1234 5678 9015", HUMO),
        ("uzcard", "8600-1234-5678-9012", UZCARD),
        ("uzcard", "5614 1234 5678 9012", "5614123456789012"),  # Uzcard's 5614 range (owner)
        ("uzum_visa", VISA, VISA),
    ],
)
def test_spaces_and_dashes_are_dropped(card_type: str, raw: str, digits: str) -> None:
    assert card_digits(card_type, raw) == digits


@pytest.mark.parametrize(
    ("card_type", "raw"),
    [
        ("humo", UZCARD),  # another type's prefix
        ("uzcard", HUMO),
        ("uzum_visa", HUMO),
        ("humo", "9860123456789016"),  # Luhn
        ("humo", HUMO[:-1]),  # 15 digits
        ("humo", HUMO + "0"),  # 17 digits
        ("humo", "98601234567890１５"),  # full-width digits
        ("mastercard", "5100000000000008"),  # not a type we pay to
    ],
)
def test_a_bad_number_is_refused_without_echoing_it(card_type: str, raw: str) -> None:
    with pytest.raises(ValidationError) as caught:
        card_digits(card_type, raw)
    assert caught.value.extra.get("code") == "card_invalid"
    assert raw not in str(caught.value)
    assert raw not in repr(caught.value.extra)


def test_masked_shows_the_last_four() -> None:
    assert masked("9015") == "•••• 9015"
