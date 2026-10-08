"""Sales settings: off by default; active only with the switch and both Skinslink credentials."""

from __future__ import annotations

import csmarket.modules.sales.api as sales_api
from csmarket.core.config import Settings
from csmarket.core.logging import REDACTED_KEYS


def _make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def test_off_by_default() -> None:
    s = _make()
    assert s.sales_enabled is False
    assert s.sales_active is False
    assert (s.sales_inventory_timeout_seconds, s.sales_deposit_timeout_seconds) == (6.0, 10.0)
    assert s.auth_ip_guard_bucket_max["sell-inventory"] == 60
    assert s.auth_ip_guard_bucket_max["sell-create"] == 60


def test_active_needs_the_switch_the_key_and_the_secret() -> None:
    assert _make(sales_enabled=True).sales_active is False
    assert _make(sales_enabled=True, skinslink_api_key="k").sales_active is False
    assert _make(skinslink_api_key="k", skinslink_secret="s").sales_active is False
    on = _make(sales_enabled=True, skinslink_api_key="k", skinslink_secret="s")
    assert on.sales_active is True


def test_card_numbers_are_redacted() -> None:
    assert {"card_number", "number_enc", "new_card", "pan"} <= REDACTED_KEYS


def test_the_module_has_a_public_interface() -> None:
    assert isinstance(sales_api.__all__, list)
