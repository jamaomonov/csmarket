"""Keyset cursors over ``(created_at DESC, id DESC)``, shared by every newest-first list.

A cursor is the last row's ``created_at`` and ``id``, JSON-encoded and base64url-encoded
without padding: opaque to the client, cheap to decode, and a token this module did not
issue is a 422 (``code="cursor"``), never a 500.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime

from csmarket.core.errors import ValidationError


def encode_cursor(created_at: datetime, row_id: str) -> str:
    """The opaque token for the page that follows the row ``(created_at, row_id)``."""
    raw = json.dumps([created_at.isoformat(), row_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[datetime, str]:
    """Inverse of :func:`encode_cursor`.

    Raises:
        ValidationError: ``token`` is not one this module issued (``code="cursor"``).
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        stamp, row_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(stamp), str(uuid.UUID(row_id))
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError, AttributeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


__all__ = ["decode_cursor", "encode_cursor"]
