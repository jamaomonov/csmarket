"""The Skinslink deposit client, as FastAPI dependencies — one per route's timeout.

``GET /sell/inventory`` waits :attr:`Settings.sales_inventory_timeout_seconds` (6 s),
``POST /sell`` :attr:`Settings.sales_deposit_timeout_seconds` (10 s): ADR-0016. Tests
override both with a fake.
"""

from __future__ import annotations

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.api import DepositClient, deposit_client_for


def inventory_client() -> DepositClient:
    """The client ``GET /sell/inventory`` reads the inventory with."""
    settings = get_settings()
    return deposit_client_for(settings, timeout_seconds=settings.sales_inventory_timeout_seconds)


def deposit_client() -> DepositClient:
    """The client ``POST /sell`` creates the deposit with."""
    settings = get_settings()
    return deposit_client_for(settings, timeout_seconds=settings.sales_deposit_timeout_seconds)


__all__ = ["deposit_client", "inventory_client"]
