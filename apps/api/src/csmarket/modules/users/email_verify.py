"""The email confirmation token (M4b ruling R7, decision D1).

Stateless: ``user_id | email | expiry`` sealed with authenticated encryption
(``nacl.secret.SecretBox``) under the ``email-verify`` purpose key derived from
``CSMARKET_APP_ENC_KEY`` (``core.crypto``), base64url without padding. The token travels in
a URL, so it is opaque — it reveals neither the address nor the account — and any change
to it fails the MAC. Valid 24 h; confirming checks that the account's email is still the
one the token names, so a link for an old address cannot verify a new one.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime

from nacl.exceptions import CryptoError

from csmarket.core import clock
from csmarket.core.crypto import box_for
from csmarket.core.errors import ValidationError

#: Domain-separation label of the token key; a new format is a new label.
PURPOSE = "csmarket:email-verify:v1"
#: Far above any real token (~150 chars); a longer input is refused before decoding.
_MAX_TOKEN = 1024


@dataclass(frozen=True, slots=True)
class VerifyClaim:
    """What a valid token says: this account may confirm this address until then."""

    user_id: str
    email: str
    expires_at: datetime


def make_token(user_id: str, email: str, *, expires_at: datetime) -> str:
    """Seal a claim into a URL-safe token.

    Args:
        user_id: The account confirming.
        email: The address being confirmed (compared case-insensitively).
        expires_at: When the token stops working.

    Returns:
        The opaque token.
    """
    body = f"{user_id}|{email.lower()}|{int(expires_at.timestamp())}".encode()
    sealed = bytes(box_for(PURPOSE).encrypt(body))
    return base64.urlsafe_b64encode(sealed).rstrip(b"=").decode("ascii")


def read_token(token: str) -> VerifyClaim:
    """Open a token and check its expiry.

    Raises:
        ValidationError: ``email_token_invalid`` for anything forged, truncated or
            malformed; ``email_token_expired`` past its expiry.
    """
    claim = _open(token)
    if claim.expires_at <= clock.now():
        raise ValidationError("the link has expired", code="email_token_expired")
    return claim


def _open(token: str) -> VerifyClaim:
    """Decode and authenticate a token, or raise ``email_token_invalid``."""
    invalid = ValidationError("the link is not valid", code="email_token_invalid")
    if not token or len(token) > _MAX_TOKEN:
        raise invalid
    try:
        sealed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        user_id, email, expiry = box_for(PURPOSE).decrypt(sealed).decode().split("|")
        expires_at = datetime.fromtimestamp(int(expiry), tz=UTC)
    except (CryptoError, binascii.Error, UnicodeDecodeError, ValueError):
        raise invalid from None
    return VerifyClaim(user_id=user_id, email=email, expires_at=expires_at)
