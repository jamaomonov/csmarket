"""A keyset cursor over rewards, newest delivery first: ``(delivered_at DESC, tie DESC)``.

The tie-breaker is the order id for the admin and ``md5(order id)`` for the partner, whose
views carry no order identity — not even inside the cursor. The token is the last row's two
keys, JSON then base64url without padding; a token this module did not issue is 422 ``cursor``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Text, and_, cast, func, or_
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.errors import ValidationError
from csmarket.modules.referrals.models import ReferralReward

_TIE = re.compile(r"^[0-9a-f-]{32,36}$")


class RewardCursor(NamedTuple):
    """The last row of a page."""

    at: datetime
    tie: str


def admin_tie() -> ColumnElement[str]:
    """The admin's tie-breaker: the order id."""
    return cast(ReferralReward.order_id, Text)


def partner_tie() -> ColumnElement[str]:
    """The partner's tie-breaker: an md5 of the order id, so the cursor names no order."""
    return func.md5(cast(ReferralReward.order_id, Text))


def masked(order_id: str) -> str:
    """:func:`partner_tie` in Python, for the last row of a page."""
    return hashlib.md5(order_id.encode(), usedforsecurity=False).hexdigest()


def encode(at: datetime, tie: str) -> str:
    """The opaque token for the page after ``(at, tie)``."""
    raw = json.dumps([at.isoformat(), tie], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str) -> RewardCursor:
    """Inverse of :func:`encode`.

    Raises:
        ValidationError: ``code="cursor"`` — not a token this module issued.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        stamp, tie = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(tie, str) or not _TIE.fullmatch(tie):
            raise ValueError("tie")
        return RewardCursor(datetime.fromisoformat(stamp), tie)
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError, AttributeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


def after(token: str | None, tie: ColumnElement[str]) -> ColumnElement[bool] | None:
    """The rows past ``token`` in ``(delivered_at DESC, tie DESC)``; ``None`` for page 1."""
    if token is None:
        return None
    c = decode(token)
    r = ReferralReward
    return or_(r.delivered_at < c.at, and_(r.delivered_at == c.at, tie < c.tie))


__all__ = [
    "RewardCursor",
    "admin_tie",
    "after",
    "decode",
    "encode",
    "masked",
    "partner_tie",
]
