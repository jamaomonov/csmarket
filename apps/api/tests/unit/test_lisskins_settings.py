"""LIS-SKINS settings: off by default, active only with the switch and the key."""

from __future__ import annotations

from decimal import Decimal

import csmarket.modules.lisskins.api as lisskins_api
from csmarket.core.config import Settings
from csmarket.core.logging import REDACTED_KEYS


def _make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def test_disabled_by_default() -> None:
    s = _make()
    assert s.lisskins_enabled is False
    assert s.lisskins_active is False
    assert s.lisskins_base_url == "https://api.lis-skins.com/v1"
    assert s.lisskins_export_url == ("https://lis-skins.com/market_export_json/api_csgo_full.json")
    assert (s.lisskins_stale_minutes, s.lisskins_request_timeout_seconds) == (20, 10.0)
    assert (s.lisskins_buy_timeout_seconds, s.lisskins_check_timeout_seconds) == (35.0, 4.0)
    assert s.lisskins_balance_alert_usd == Decimal(100)


def test_active_needs_the_switch_and_the_key() -> None:
    assert _make(lisskins_enabled=True).lisskins_active is False
    assert _make(lisskins_api_key="k").lisskins_active is False
    assert _make(lisskins_enabled=True, lisskins_api_key="k").lisskins_active is True


def test_the_key_is_redacted() -> None:
    assert "lisskins_api_key" in REDACTED_KEYS


def test_the_module_has_a_public_interface() -> None:
    assert isinstance(lisskins_api.__all__, list)
