"""Refresh-token minting and hashing."""

from csmarket.modules.auth.security import hash_token, new_refresh_token, sha256_hex


def test_new_refresh_token_is_43_urlsafe_chars_and_unique() -> None:
    tokens = {new_refresh_token() for _ in range(50)}
    assert len(tokens) == 50
    for t in tokens:
        assert len(t) == 43
        assert set(t) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_hash_token_is_sha256_hex() -> None:
    assert hash_token("abc") == sha256_hex(b"abc")
    assert hash_token("abc") == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    assert len(hash_token(new_refresh_token())) == 64
