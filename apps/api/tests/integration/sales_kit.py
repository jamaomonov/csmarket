# apps/api/tests/integration/sales_kit.py
"""Shared set-up for the sales route tests: switches on, a seller with a link, a rate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.sales.clients import deposit_client, inventory_client
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.fake_deposit_client import FakeDepositClient
from tests.integration.orders_factory import saved_trade_link
from tests.integration.sales_factory import RATE, enable_sales

SECRET = "test-secret-not-real"
Headers = Callable[[], Awaitable[dict[str, str]]]


@pytest.fixture
def sales_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``CSMARKET_SALES_ENABLED`` with both Skinslink credentials."""
    for name, value in {
        "SALES_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": SECRET,
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def add_rate(db: AsyncSession) -> None:
    """A fresh CBU snapshot at :data:`RATE`."""
    db.add(FxSnapshot(id=new_id(), usd_uzs=RATE, source="cbu"))
    await db.commit()


async def ready_seller(db: AsyncSession, customer_headers: Headers) -> dict[str, str]:
    """The customer signed in with the fake trade link; selling on; a rate. Their headers."""
    headers = await customer_headers()
    await saved_trade_link(db, CUSTOMER_STEAM_ID)
    await enable_sales(db)
    await add_rate(db)
    return headers


def use_client(app: FastAPI, client: FakeDepositClient) -> None:
    """Route both deposit-client dependencies to ``client``."""
    app.dependency_overrides[inventory_client] = lambda: client
    app.dependency_overrides[deposit_client] = lambda: client
