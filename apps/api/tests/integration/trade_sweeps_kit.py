"""Fixtures and helpers for the trade sweep suites (``test_orders_trades.py``,
``test_orders_sweeps.py``): orders at each in-flight stage, a settable clock, and one-call
runs of each sweep against a scripted Waxpeer.

A test module imports the ``*_fixture`` functions (``# noqa: F401``); pytest registers
each under its short name (``db``, ``fake``, ``clock``, ``buying_order``, …).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.sweeps import audit_recent, reconcile, watch_protected
from csmarket.modules.skins.api import WaxpeerTrade
from csmarket.modules.wallet.api import user_balance
from prometheus_client import REGISTRY
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.fake_trade_client import FakeTradeClient, waxpeer_trade
from tests.integration.orders_factory import make_order, make_trade

PRICE = Decimal(171_800)
COST = 12_345
#: The Waxpeer id our buy recorded (redrawn).
WAXPEER_ID = 60_000_001
#: When Steam's protection ends for an accepted trade.
RELEASE = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class Clock:
    """``core.clock`` pinned to a moment the test moves by hand."""

    def __init__(self) -> None:
        self._at = datetime.now(UTC)

    def now(self) -> datetime:
        """The pinned moment."""
        return self._at

    def advance(self, **delta: float) -> None:
        """Move the clock forward by ``timedelta(**delta)``."""
        self._at += timedelta(**delta)


@pytest.fixture(name="clock")
def clock_fixture() -> Iterator[Clock]:
    pinned = Clock()
    core_clock.set_clock(pinned.now)
    try:
        yield pinned
    finally:
        core_clock.reset_clock()


@pytest.fixture(name="db")
def db_fixture(db_session: AsyncSession) -> AsyncSession:
    return db_session


@pytest.fixture(name="fake")
def fake_fixture() -> FakeTradeClient:
    return FakeTradeClient()


def sweep_settings(**update: Any) -> Settings:
    """Settings with a (fake) Waxpeer key: live listings allowed, the fake answers."""
    return get_settings().model_copy(update={"waxpeer_api_key": "test-key-not-real", **update})


async def order_in(db: AsyncSession, order_status: str, /, **trade: object) -> Order:
    """A kassa-paid order in ``order_status`` with its bought trade (``trade`` overrides
    the trade's columns)."""
    order = await make_order(
        db, status=order_status, paid_with="payme", paid_at=core_clock.now(), price_uzs=PRICE
    )
    values: dict[str, object] = {"waxpeer_id": WAXPEER_ID, "status": 0, "bought_units": COST}
    values.update(trade)
    await make_trade(db, order, **values)
    return order


@pytest.fixture(name="buying_order")
async def buying_order_fixture(db: AsyncSession) -> Order:
    """Bought at Waxpeer (status 0), the seller has not sent the offer yet."""
    return await order_in(db, "buying")


@pytest.fixture(name="trade_sent_order")
async def trade_sent_order_fixture(db: AsyncSession) -> Order:
    """The offer is out (status 4, no ``release_date``)."""
    return await order_in(db, "trade_sent", status=4, trade_id="7700112233")


@pytest.fixture(name="delivered_order")
async def delivered_order_fixture(db: AsyncSession) -> Order:
    """Accepted: status 4 with ``release_date``, in Steam's protection."""
    return await order_in(
        db,
        "delivered",
        status=4,
        trade_id="7700112233",
        release_date=RELEASE,
        accepted_at=RELEASE - timedelta(days=7),
    )


async def set_trade(db: AsyncSession, order: Order, **values: object) -> None:
    """Overwrite columns of ``order``'s trade; commit."""
    await db.execute(update(SkinTrade).where(SkinTrade.order_id == order.id).values(**values))
    await db.commit()


async def set_order(db: AsyncSession, order: Order, **values: object) -> None:
    """Overwrite columns of ``order``; commit."""
    await db.execute(update(Order).where(Order.id == order.id).values(**values))
    await db.commit()


async def load(db: AsyncSession, order: Order) -> tuple[Order, SkinTrade]:
    """The order and its trade as committed."""
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert trade is not None
    return row, trade


def trade(*, project_id: str, status: int, **over: Any) -> WaxpeerTrade:
    """Our trade as a lookup reports it (Waxpeer id :data:`WAXPEER_ID` unless overridden)."""
    return waxpeer_trade(project_id, status=status, **{"id": WAXPEER_ID, **over})


def factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Sessions on ``db``'s engine, as the scheduler's factory."""
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


async def reconcile_once(db: AsyncSession, fake: FakeTradeClient, **settings: Any) -> int:
    """One reconcile tick."""
    return await reconcile(factory(db), fake, settings=sweep_settings(**settings))


async def watch_once(db: AsyncSession, fake: FakeTradeClient) -> int:
    """One protection watch, on a session of its own."""
    async with factory(db)() as session:
        return await watch_protected(session, fake)


async def audit_once(db: AsyncSession, fake: FakeTradeClient, **kwargs: Any) -> int:
    """One history audit, on a session of its own."""
    async with factory(db)() as session:
        return await audit_recent(session, fake, **kwargs)


async def balance(db: AsyncSession, order: Order) -> Decimal:
    """The buyer's balance."""
    value = await user_balance(db, order.user_id)
    await db.commit()
    return value


def attentions(reason: str) -> float:
    """``csmarket_trade_attention_total{reason}`` so far."""
    value = REGISTRY.get_sample_value("csmarket_trade_attention_total", {"reason": reason})
    return value or 0.0


__all__ = [
    "COST",
    "PRICE",
    "RELEASE",
    "WAXPEER_ID",
    "Clock",
    "attentions",
    "audit_once",
    "balance",
    "buying_order_fixture",
    "clock_fixture",
    "db_fixture",
    "delivered_order_fixture",
    "factory",
    "fake_fixture",
    "load",
    "order_in",
    "reconcile_once",
    "set_order",
    "set_trade",
    "sweep_settings",
    "trade",
    "trade_sent_order_fixture",
    "watch_once",
]
