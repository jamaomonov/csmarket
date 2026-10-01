"""Purpose-separated at-rest encryption."""

from __future__ import annotations

import base64
import secrets

import pytest
from csmarket.core import crypto
from csmarket.core.config import Settings


def test_round_trip_under_one_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crypto, "get_settings", lambda: Settings(environment="test"))
    crypto.box_for.cache_clear()
    ct, nonce = crypto.encrypt("trade-token-redrawn", purpose="csmarket:test:v1")
    assert crypto.decrypt(ct, nonce, purpose="csmarket:test:v1") == "trade-token-redrawn"
    assert len(nonce) == crypto.NONCE_SIZE


def test_two_purposes_do_not_share_a_key() -> None:
    ikm = secrets.token_bytes(32)
    assert crypto.derive_key(ikm, "a:v1") != crypto.derive_key(ikm, "b:v1")


def test_prod_without_a_key_refuses() -> None:
    with pytest.raises(RuntimeError, match="CSMARKET_APP_ENC_KEY"):
        crypto.input_key_material(Settings(environment="prod", app_enc_key=""))


def test_a_configured_key_must_be_32_bytes() -> None:
    short = base64.b64encode(b"x" * 16).decode()
    with pytest.raises(RuntimeError, match="32 bytes"):
        crypto.input_key_material(Settings(environment="prod", app_enc_key=short))
    good = base64.urlsafe_b64encode(b"y" * 32).decode().rstrip("=")
    assert len(crypto.input_key_material(Settings(environment="prod", app_enc_key=good))) == 32
