"""EdDSA access tokens: round trip, rejection paths, ephemeral dev keys (ruling P7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth import jwt as authjwt
from csmarket.modules.auth.jwt import mint_access, verify


@pytest.fixture
def settings() -> Settings:
    """Fresh settings for each test (the suite's configured key pair)."""
    get_settings.cache_clear()
    return get_settings()


def _other_private_pem() -> str:
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def test_mint_and_verify_access_round_trip(settings: Settings) -> None:
    token = mint_access(sub="user-1", sid="sess-1", settings=settings)
    claims = verify(token, expected_kind="access", settings=settings)
    assert claims.sub == "user-1"
    assert claims.sid == "sess-1"
    assert claims.kind == "access"
    assert claims.jti
    assert claims.exp - claims.iat == timedelta(seconds=settings.jwt_access_ttl_seconds)


def test_header_carries_alg_and_kid(settings: Settings) -> None:
    header = pyjwt.get_unverified_header(mint_access(sub="u", sid="s", settings=settings))
    assert header["alg"] == "EdDSA"
    assert header["kid"] == settings.jwt_kid


def test_verify_rejects_garbage(settings: Settings) -> None:
    with pytest.raises(UnauthorizedError):
        verify("not.a.jwt", settings=settings)


def test_verify_rejects_expired_token(settings: Settings) -> None:
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    clock.set_clock(lambda: fixed)
    try:
        token = mint_access(sub="u", sid="s", settings=settings)
    finally:
        clock.reset_clock()
    with pytest.raises(UnauthorizedError):
        verify(token, settings=settings)


def test_verify_rejects_a_tampered_token(settings: Settings) -> None:
    token = mint_access(sub="u", sid="s", settings=settings)
    header, payload, signature = token.split(".")
    forged = pyjwt.encode(
        {**pyjwt.decode(token, options={"verify_signature": False}), "sub": "admin"},
        _other_private_pem(),
        algorithm="EdDSA",
    ).split(".")[1]
    with pytest.raises(UnauthorizedError):
        verify(f"{header}.{forged}.{signature}", settings=settings)


def test_verify_rejects_a_token_signed_by_another_key(settings: Settings) -> None:
    now = int(datetime.now(UTC).timestamp())
    token = pyjwt.encode(
        {
            "iss": settings.jwt_issuer,
            "sub": "u",
            "kind": "access",
            "jti": "j",
            "sid": "s",
            "iat": now,
            "exp": now + 60,
        },
        _other_private_pem(),
        algorithm="EdDSA",
    )
    with pytest.raises(UnauthorizedError):
        verify(token, settings=settings)


def test_verify_rejects_wrong_issuer(settings: Settings) -> None:
    other = settings.model_copy(update={"jwt_issuer": "someone-else"})
    token = mint_access(sub="u", sid="s", settings=other)
    with pytest.raises(UnauthorizedError):
        verify(token, settings=settings)


def test_verify_rejects_a_kind_mismatch(settings: Settings) -> None:
    now = int(datetime.now(UTC).timestamp())
    token = pyjwt.encode(
        {
            "iss": settings.jwt_issuer,
            "sub": "u",
            "kind": "refresh",
            "jti": "j",
            "sid": "s",
            "iat": now,
            "exp": now + 60,
        },
        settings.jwt_private_key,
        algorithm="EdDSA",
    )
    with pytest.raises(UnauthorizedError, match="kind"):
        verify(token, settings=settings)


def test_verify_rejects_alg_none(settings: Settings) -> None:
    now = int(datetime.now(UTC).timestamp())
    token = pyjwt.encode(
        {
            "iss": settings.jwt_issuer,
            "sub": "u",
            "kind": "access",
            "jti": "j",
            "iat": now,
            "exp": now + 60,
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(UnauthorizedError):
        verify(token, settings=settings)


def test_prod_without_keys_refuses() -> None:
    with pytest.raises(RuntimeError, match="CSMARKET_JWT_PRIVATE_KEY"):
        mint_access(
            sub="u",
            sid="s",
            settings=Settings(environment="prod", jwt_private_key="", jwt_public_key=""),
        )


def test_prod_without_keys_refuses_to_verify(settings: Settings) -> None:
    token = mint_access(sub="u", sid="s", settings=settings)
    with pytest.raises(RuntimeError, match="CSMARKET_JWT_PUBLIC_KEY"):
        verify(
            token,
            settings=Settings(environment="prod", jwt_private_key="", jwt_public_key=""),
        )


def test_dev_without_keys_uses_a_stable_ephemeral_pair() -> None:
    s = Settings(environment="dev", jwt_private_key="", jwt_public_key="")
    token = mint_access(sub="u1", sid="s1", settings=s)
    assert verify(token, settings=s).sub == "u1"
    assert authjwt._ephemeral_pair() is authjwt._ephemeral_pair()


def test_a_half_configured_pair_is_not_used() -> None:
    """Only a full pair wins; one key alone outside prod falls back to the ephemeral pair."""
    s = Settings(environment="dev", jwt_private_key=_other_private_pem(), jwt_public_key="")
    assert authjwt._keys(s) == authjwt._ephemeral_pair()
