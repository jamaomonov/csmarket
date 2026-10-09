"""Per-key limits: a key's own value beats the default (spec v1.1 §3)."""

from __future__ import annotations

import pytest
from csmarket.modules.public_api.limits import LIMITS, Bucket, effective_limits, limit_for
from csmarket.modules.public_api.models import ApiKey


def _key(**limits: int | None) -> ApiKey:
    return ApiKey(user_id="u", token_hash="h", **limits)


def test_defaults() -> None:
    assert LIMITS == {"read": 60, "order": 10, "feed": 1, "check": 30}


@pytest.mark.parametrize(
    ("bucket", "column"),
    [
        ("read", "read_per_min"),
        ("order", "orders_per_min"),
        ("feed", "feed_per_min"),
        ("check", "check_per_min"),
    ],
)
def test_key_value_beats_default(bucket: Bucket, column: str) -> None:
    assert limit_for(_key(**{column: 600}), bucket) == 600


def test_null_falls_back_to_default() -> None:
    key = _key()
    assert {b: limit_for(key, b) for b in LIMITS} == LIMITS


def test_effective_limits() -> None:
    assert effective_limits(_key(read_per_min=600, orders_per_min=30)) == {
        "read": 600,
        "order": 30,
        "feed": 1,
        "check": 30,
    }
