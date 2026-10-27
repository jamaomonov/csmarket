"""A keyset cursor over rewards, newest delivery first: ``(delivered_at DESC, order_id DESC)``.

The token is the last row's two keys, JSON then base64url without padding; a token this
module did not issue is 422 ``cursor``.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.errors import ValidationError
from csmarket.modules.referrals.models import ReferralReward


class RewardCursor(NamedTuple):
    """The last row of a page."""

    at: datetime
    order_id: str


def encode(at: datetime, order_id: str) -> str:
    """The opaque token for the page after ``(at, order_id)``."""
    raw = json.dumps([at.isoformat(), order_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str) -> RewardCursor:
    """Inverse of :func:`encode`.

    Raises:
        ValidationError: ``code="cursor"`` — not a token this module issued.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        stamp, order_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        return RewardCursor(datetime.fromisoformat(stamp), str(uuid.UUID(order_id)))
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError, AttributeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


def after(token: str | None) -> ColumnElement[bool] | None:
    """The rows past ``token`` in ``(delivered_at DESC, order_id DESC)``; ``None`` for page 1."""
    if token is None:
        return None
    c = decode(token)
    r = ReferralReward
    return or_(r.delivered_at < c.at, and_(r.delivered_at == c.at, r.order_id < c.order_id))


__all__ = ["RewardCursor", "after", "decode", "encode"]
