"""Access-token issuance and verification (EdDSA / Ed25519).

Access tokens are short-lived (``jwt_access_ttl_seconds``, 15 min) and carry the ``sid``
of the ``refresh_tokens`` row they were minted from. This module is intentionally thin —
it does **no** session lookups and **no** revocation checks; those live in
:mod:`csmarket.modules.auth.service`.

Keys: the configured pair wins. Outside prod an empty pair falls back to a process-local
Ed25519 pair (ruling P7) — access tokens die with the process, sessions survive through
the refresh cookie. Prod without keys refuses to mint or verify.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, cast

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jwt.exceptions import InvalidTokenError

from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import UnauthorizedError
from csmarket.core.ids import new_id

ALG: Final[str] = "EdDSA"

TokenKind = Literal["access"]

_EPHEMERAL: tuple[str, str] | None = None


@dataclass(frozen=True)
class Claims:
    """Decoded access-token payload, narrowed to the fields csmarket uses."""

    sub: str
    kind: TokenKind
    jti: str
    iat: datetime
    exp: datetime
    sid: str


def _settings_or(settings: Settings | None) -> Settings:
    return settings if settings is not None else get_settings()


def _ephemeral_pair() -> tuple[str, str]:
    """A process-local Ed25519 pair for dev/test when no keys are configured (ruling P7)."""
    global _EPHEMERAL
    if _EPHEMERAL is None:
        key = Ed25519PrivateKey.generate()
        private = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        public = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        _EPHEMERAL = (private, public)
    return _EPHEMERAL


def _keys(settings: Settings) -> tuple[str, str]:
    """(private, public). Configured keys win; prod without them refuses."""
    if settings.jwt_private_key and settings.jwt_public_key:
        return settings.jwt_private_key, settings.jwt_public_key
    if settings.is_prod:
        raise RuntimeError(
            "CSMARKET_JWT_PRIVATE_KEY / CSMARKET_JWT_PUBLIC_KEY are not configured — "
            "refusing to mint or verify. Generate with ./scripts/gen-secret.sh jwt."
        )
    return _ephemeral_pair()


def _encode(payload: dict[str, Any], *, settings: Settings) -> str:  # Any: JSON claim values
    return jwt.encode(
        payload,
        _keys(settings)[0],
        algorithm=ALG,
        headers={"kid": settings.jwt_kid},
    )


def _base_payload(
    *,
    sub: str,
    kind: TokenKind,
    ttl_seconds: int,
    settings: Settings,
) -> dict[str, Any]:  # Any: JSON claim values
    issued = now()
    return {
        "iss": settings.jwt_issuer,
        "sub": sub,
        "kind": kind,
        "jti": new_id(),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl_seconds)).timestamp()),
    }


def mint_access(*, sub: str, sid: str, settings: Settings | None = None) -> str:
    """Issue a short-lived access JWT for a signed-in user.

    Args:
        sub: The ``users`` row id.
        sid: The ``refresh_tokens`` row this token belongs to. The caller is responsible
            for it being non-revoked.
        settings: Overrides the process settings; for tests.

    Returns:
        The encoded JWT.

    Raises:
        RuntimeError: In prod when the key pair is not configured.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub, kind="access", ttl_seconds=s.jwt_access_ttl_seconds, settings=s
    )
    payload["sid"] = sid
    return _encode(payload, settings=s)


def verify(
    token: str,
    *,
    expected_kind: TokenKind = "access",
    settings: Settings | None = None,
) -> Claims:
    """Decode and validate a JWT: signature, ``iss``, ``exp``, required claims, ``kind``.

    Args:
        token: The encoded JWT.
        expected_kind: The ``kind`` claim the caller accepts.
        settings: Overrides the process settings; for tests.

    Returns:
        The decoded claims.

    Raises:
        UnauthorizedError: On a bad signature, expiry, wrong issuer, a missing required
            claim (``sid`` included) or a kind mismatch.
        RuntimeError: In prod when the key pair is not configured.
    """
    s = _settings_or(settings)
    public_key = _keys(s)[1]
    try:
        raw = jwt.decode(
            token,
            public_key,
            algorithms=[ALG],
            issuer=s.jwt_issuer,
            # ``sid`` too: a token without one could not be revoked with its session.
            options={"require": ["iat", "exp", "iss", "sub", "jti", "sid"]},
        )
    except InvalidTokenError as exc:
        raise UnauthorizedError("invalid token") from exc

    kind = raw.get("kind")
    if kind != expected_kind:
        raise UnauthorizedError("wrong token kind")

    return Claims(
        sub=str(raw["sub"]),
        kind=cast(TokenKind, kind),
        jti=str(raw["jti"]),
        iat=datetime.fromtimestamp(int(raw["iat"]), tz=now().tzinfo),
        exp=datetime.fromtimestamp(int(raw["exp"]), tz=now().tzinfo),
        sid=str(raw["sid"]),
    )
