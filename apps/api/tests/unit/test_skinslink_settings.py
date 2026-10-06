"""Skinslink settings: off by default, active only with the switch and both keys."""

from __future__ import annotations

from csmarket.core.config import Settings


def test_disabled_by_default() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.skinslink_enabled is False
    assert s.skinslink_active is False
    assert s.skinslink_base_url == "https://api.skinslink.com/api/v1"
    assert s.skinslink_mirror_stale_minutes == 10


def test_active_needs_switch_and_both_keys() -> None:
    def make(**kw: object) -> Settings:
        return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]

    assert make(skinslink_enabled=True).skinslink_active is False
    assert make(skinslink_enabled=True, skinslink_api_key="k").skinslink_active is False
    assert (
        make(skinslink_enabled=True, skinslink_api_key="k", skinslink_secret="s").skinslink_active
        is True
    )
