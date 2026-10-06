"""The Skinslink status webhook's signature (spec 2026-10-06 §6).

``sign = base64(sha256(str(id) + secret))`` covers the id only — never the status — so the
body is not trusted: a valid signature only says "ask Skinslink about purchase N".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from typing import Any


def expected_sign(id_: int, secret: str) -> str:
    """The signature Skinslink puts on a webhook about ``id_``."""
    return base64.b64encode(hashlib.sha256((str(id_) + secret).encode()).digest()).decode()


def verify(body: Mapping[str, Any], *, secret: str) -> int | None:  # Any: the webhook's JSON
    """The purchase (or deposit) id the signature vouches for, or ``None``."""
    raw = body.get("purchase_id", body.get("trade_id"))
    sign = body.get("sign")
    if isinstance(raw, bool) or not isinstance(raw, int) or not isinstance(sign, str):
        return None
    if not secret:
        return None
    return raw if hmac.compare_digest(expected_sign(raw, secret), sign) else None


__all__ = ["expected_sign", "verify"]
