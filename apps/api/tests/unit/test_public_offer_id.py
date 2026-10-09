"""The sealed offer id: opaque, bound to its item, tamper-proof."""

from __future__ import annotations

import base64

from csmarket.modules.public_api.offers import open_offer_id, seal_offer_id


def test_round_trip() -> None:
    token = seal_offer_id("item1", "sl:abc123")
    assert open_offer_id(token, "item1") == "sl:abc123"


def test_another_item_is_refused() -> None:
    assert open_offer_id(seal_offer_id("item1", "ls:5"), "item2") is None


def test_flipped_byte_is_refused() -> None:
    raw = bytearray(base64.urlsafe_b64decode(seal_offer_id("item1", "ls:5") + "=="))
    raw[-1] ^= 1
    token = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    assert open_offer_id(token, "item1") is None


def test_garbage_is_refused() -> None:
    for junk in ("", "!!!", "abc", "A" * 200):
        assert open_offer_id(junk, "item1") is None


def test_token_hides_the_source() -> None:
    token = seal_offer_id("item1", "sl:abc123")
    assert "sl:" not in token
    assert "ls:" not in token
    assert "=" not in token
