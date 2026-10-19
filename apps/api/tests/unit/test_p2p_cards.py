"""``p2p.cards``: the card number is sealed at rest and shown masked."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.p2p.cards import masked, normalize_pan, open_pan, seal_pan

PAN = "9860123412341234"


def test_a_sealed_number_opens_and_hides_its_digits() -> None:
    ciphertext, nonce = seal_pan(PAN)
    assert PAN.encode() not in ciphertext
    card: Any = SimpleNamespace(pan_ciphertext=ciphertext, pan_nonce=nonce)
    assert open_pan(card) == PAN


def test_a_number_is_sixteen_digits_whatever_the_spacing() -> None:
    assert normalize_pan("9860 1234-1234 1234") == PAN
    with pytest.raises(ValidationError):
        normalize_pan("9860 1234")


def test_masked_shows_the_last_four_only() -> None:
    assert masked("1234") == "•••• 1234"
