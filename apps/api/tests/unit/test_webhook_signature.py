"""The partner webhook signature (plan C, Task 3; Review Focus 3)."""

from __future__ import annotations

import hashlib
import hmac

from csmarket.modules.public_api.webhook_sender import sign

KEY = hashlib.sha256(b"csm_fake_token_for_tests").hexdigest()
BODY = b'{"event":"order.paid","order":{"order_id":"a"}}'


def test_sign_is_hex_hmac_sha256_over_timestamp_dot_body() -> None:
    expected = hmac.new(KEY.encode(), b"1760000000." + BODY, hashlib.sha256).hexdigest()
    assert sign(KEY, 1760000000, BODY) == expected
    assert len(sign(KEY, 1760000000, BODY)) == 64


def test_one_changed_body_byte_fails_verification() -> None:
    signature = sign(KEY, 1760000000, BODY)
    for i in range(len(BODY)):
        tampered = BODY[:i] + bytes([BODY[i] ^ 0x01]) + BODY[i + 1 :]
        assert not hmac.compare_digest(sign(KEY, 1760000000, tampered), signature)


def test_the_timestamp_and_the_key_are_covered() -> None:
    signature = sign(KEY, 1760000000, BODY)
    assert sign(KEY, 1760000001, BODY) != signature
    other = hashlib.sha256(b"csm_other_fake_token").hexdigest()
    assert sign(other, 1760000000, BODY) != signature
