"""A card's full number, sealed at rest (``core.crypto``)."""

from __future__ import annotations

import re

from csmarket.core.crypto import decrypt, encrypt
from csmarket.core.errors import ValidationError
from csmarket.modules.p2p.models import P2PCard

_PURPOSE = "p2p_card_pan"
_PAN_DIGITS = 16


def normalize_pan(raw: str) -> str:
    """Digits only, exactly 16, or a 422 the admin form can show."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != _PAN_DIGITS:
        raise ValidationError("card number must be 16 digits", code="p2p_pan_invalid")
    return digits


def seal_pan(pan: str) -> tuple[bytes, bytes]:
    """Encrypt a normalized number. Returns ``(ciphertext, nonce)``."""
    return encrypt(pan, purpose=_PURPOSE)


def open_pan(card: P2PCard) -> str:
    """The full number, for the one response that must carry it (an open request)."""
    return decrypt(card.pan_ciphertext, card.pan_nonce, purpose=_PURPOSE)


def masked(last4: str) -> str:
    """``•••• 1234``."""
    return f"•••• {last4}"


__all__ = ["masked", "normalize_pan", "open_pan", "seal_pan"]
