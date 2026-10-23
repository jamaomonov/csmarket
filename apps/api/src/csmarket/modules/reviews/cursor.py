"""A keyset cursor over ``(rank ASC, created_at DESC, id DESC)``.

``rank`` puts one group first (the visitor's locale on the public page, unresolved bad reviews
in the admin's «Плохие»); within a group, newest first. The token is the last row's three keys,
JSON then base64url without padding; a token this module did not issue is 422 ``cursor``.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import SQLColumnExpression, and_, or_
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.errors import ValidationError


class RankCursor(NamedTuple):
    """The last row of a page."""

    rank: int
    at: datetime
    row_id: str


def encode_rank_cursor(rank: int, at: datetime, row_id: str) -> str:
    """The opaque token for the page after the row ``(rank, at, row_id)``."""
    raw = json.dumps([rank, at.isoformat(), row_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_rank_cursor(token: str) -> RankCursor:
    """Inverse of :func:`encode_rank_cursor`.

    Raises:
        ValidationError: ``code="cursor"`` — not a token this module issued.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        rank, stamp, row_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        return RankCursor(int(rank), datetime.fromisoformat(stamp), str(uuid.UUID(row_id)))
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError, AttributeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


def after(
    rank: SQLColumnExpression[int],
    at: SQLColumnExpression[datetime],
    row_id: SQLColumnExpression[str],
    c: RankCursor,
) -> ColumnElement[bool]:
    """Rows after ``c`` in ``rank ASC, at DESC, id DESC`` order."""
    return or_(
        rank > c.rank,
        and_(rank == c.rank, or_(at < c.at, and_(at == c.at, row_id < c.row_id))),
    )


__all__ = ["RankCursor", "after", "decode_rank_cursor", "encode_rank_cursor"]
