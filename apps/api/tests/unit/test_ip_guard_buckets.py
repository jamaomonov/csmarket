"""Per-bucket thresholds and key shapes for the IP guard.

Crowd buckets (Steam sign-in, the trade-link check) sit behind carrier NAT, where many
customers share one address and spend a budget collectively; an unlisted bucket keeps
the tight shared default. The guard is Redis-backed, so these tests call the pure
pieces (``bucket_limit``, the key builders); ``test_auth_ip_guard.py`` covers the wiring.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.core.config import get_settings
from csmarket.core.logging import hash_short
from csmarket.modules.auth.ip_guard import bucket_limit, ip_key, subject_key


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_unlisted_bucket_keeps_the_shared_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_MAX", "10")
    assert bucket_limit(get_settings(), "something-else") == 10


def test_crowd_buckets_are_looser_than_the_shared_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_MAX", "10")
    s = get_settings()
    for bucket in ("steam-login", "trade-link-check", "dev-login"):
        assert bucket_limit(s, bucket) > bucket_limit(s, "something-else"), bucket


def test_an_operator_can_retune_one_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"steam-login": 45}')
    s = get_settings()
    assert bucket_limit(s, "steam-login") == 45
    assert bucket_limit(s, "trade-link-check") == 10


def test_a_bucket_can_be_tightened_below_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overrides are not "raise only" -- an abused bucket must be squeezable."""
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"trade-link-check": 3}')
    assert bucket_limit(get_settings(), "trade-link-check") == 3


def test_a_malformed_override_never_disables_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 would read as "allow nothing" and a negative, past ``count > limit``, as
    "allow everything" — both land on the default instead."""
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"steam-login": 0, "dev-login": -5}')
    s = get_settings()
    assert bucket_limit(s, "steam-login") == 10
    assert bucket_limit(s, "dev-login") == 10


def test_keys_carry_a_hash_of_the_ip_never_the_ip() -> None:
    ip = "203.0.113.7"
    assert ip_key("steam-login", ip) == f"auth:ipguard:steam-login:{hash_short(ip)}"
    sk = subject_key("steam-login", ip, "76561198000000001")
    assert sk.startswith(f"auth:ipguard:steam-login:{hash_short(ip)}:s:")
    assert ip not in sk
    assert "76561198000000001" not in sk
