"""Small cryptographic helpers for refresh tokens.

Anything that has to be replay-safe lives here so the service and HTTP layers cannot
re-implement it differently. Nothing password-related: Steam is the only sign-in.
"""

from __future__ import annotations

import hashlib
import secrets


def sha256_hex(data: bytes) -> str:
    """Return a hex-encoded SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def hash_token(token: str) -> str:
    """Hash a refresh token for storage. Never store plaintext tokens."""
    return sha256_hex(token.encode("utf-8"))


def new_refresh_token() -> str:
    """Mint a fresh, URL-safe refresh token (43 chars, 256 bits of entropy)."""
    return secrets.token_urlsafe(32)
