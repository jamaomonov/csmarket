"""Rows for orders tests: an order with its item and rate, a trade, a buyer with a saved
trade link, and a stub of the live-listings read (shared by the M4a suites).

Import as ``from tests.integration.orders_factory import make_order``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
from csmarket.core import clock
from csmarket.core.ids import new_id
from csmarket.core.numbers import allocate, order_number
from csmarket.core.redis import get_redis
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.orders.api import ORDERS_CHANNEL
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

#: A trade link shaped like Steam's; the partner and token are fake.
FAKE_TRADE_LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE"


async def make_item_and_rate(db: AsyncSession) -> tuple[SkinItem, FxSnapshot]:
    """A committed catalogue item and USD/UZS rate an order can point at."""
    suffix = uuid4().hex[:6]
    item = SkinItem(
        id=new_id(),
        # Unique per call (``uq_skin_items_name_phase``): one test may make several.
        market_hash_name=f"AK-47 | Redline {suffix} (Field-Tested)",
        phase="",
        slug=f"ak-47-redline-field-tested-{suffix}",
        category="rifles",
        search_text="ak 47 redline field tested",
    )
    fx = FxSnapshot(id=new_id(), usd_uzs=Decimal("12650.5"), source="cbu")
    db.add_all([item, fx])
    await db.commit()
    return item, fx


async def build_order(
    db: AsyncSession,
    *,
    user: User,
    item: SkinItem,
    fx: FxSnapshot,
    **overrides: object,
) -> Order:
    """An order added to ``db`` but not flushed (``overrides`` replace any column)."""
    values: dict[str, object] = {
        "id": new_id(),
        "number": await allocate(db, Order.number, order_number),
        "user_id": user.id,
        "status": "pending",
        "skin_item_id": item.id,
        "market_hash_name": item.market_hash_name,
        "slug": item.slug,
        "listing_id": 9_100_200_300,
        "cost_units": 12_345,
        "cost_usd": Decimal("12.345"),
        "price_usd": Decimal("13.580000"),
        "price_uzs": Decimal(171_800),
        "fx_snapshot_id": fx.id,
        "trade_link": FAKE_TRADE_LINK,
        "idempotency_key": f"test-{uuid4()}",
        "expires_at": clock.now() + timedelta(minutes=15),
    }
    values.update(overrides)
    order = Order(**values)
    db.add(order)
    return order


async def make_order(db: AsyncSession, *, user: User | None = None, **overrides: object) -> Order:
    """A committed order (a new user's unless ``user``) for a new item and rate."""
    owner = user or await make_user(db)
    item, fx = await make_item_and_rate(db)
    order = await build_order(db, user=owner, item=item, fx=fx, **overrides)
    await db.commit()
    return order


async def make_trade(db: AsyncSession, order: Order, **overrides: object) -> SkinTrade:
    """A committed ``skin_trades`` row for ``order`` (``overrides`` replace any column)."""
    values: dict[str, object] = {
        "order_id": order.id,
        "project_id": order.id,
        "listing_id": order.listing_id,
        "paid_units": order.cost_units,
        "seller": {},
    }
    values.update(overrides)
    trade = SkinTrade(**values)
    db.add(trade)
    await db.commit()
    return trade


async def cancel_while_held(db: AsyncSession, order: Order) -> None:
    """Cancel ``order`` while a kassa still holds its attempt; commit.

    The expiry sweep never does this (it keeps a kassa-held order), so this stands in for
    any other cancel: a late settle of the held attempt must still be refused.
    """
    await db.execute(
        update(Order)
        .where(Order.id == order.id)
        .values(status="cancelled", cancelled_at=clock.now())
    )
    await db.commit()


async def saved_trade_link(
    db: AsyncSession,
    steam_id: str,
    *,
    link: str | None = FAKE_TRADE_LINK,
    verdict: str | None = "ok",
    reason: str | None = None,
) -> User:
    """Give the account ``steam_id`` a saved trade link and check verdict; commit."""
    user = await db.scalar(select(User).where(User.steam_id == steam_id))
    assert user is not None, "sign the account in first"
    user.trade_link, user.trade_link_verdict, user.trade_link_reason = link, verdict, reason
    await db.commit()
    return user


async def make_user_with_link(
    db: AsyncSession, *, verdict: str | None = "ok", reason: str | None = None
) -> User:
    """A committed user with the fake trade link saved and ``verdict`` recorded."""
    user = await make_user(db)
    return await saved_trade_link(db, user.steam_id, verdict=verdict, reason=reason)


class StubListings:
    """Stands in for the Waxpeer live-listings client (``skins.listings.SearchClient``).

    ``await stub.set(slug, [(listing_id, price_units), ...])`` sets the auto offers of the
    item registered under ``slug`` and drops that item's cached listings, so the next read
    asks the stub again.
    """

    def __init__(self) -> None:
        self.names: dict[str, str] = {}
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.calls = 0
        #: When set, every read waits here — lines concurrent requests up at the read.
        self.barrier: asyncio.Barrier | None = None

    def register(self, item: SkinItem) -> None:
        """Answer for ``item`` (by its Waxpeer name)."""
        self.names[item.slug] = item.market_hash_name

    async def set(self, slug: str, offers: Sequence[tuple[int, int]]) -> None:
        """Make ``offers`` the live auto listings of ``slug``."""
        self.rows[self.names[slug]] = [
            {"item_id": listing_id, "price": units, "auto": True} for listing_id, units in offers
        ]
        await get_redis().delete(f"skins:listings:{slug}", f"skins:listings:{slug}:stale")

    # Any: raw Waxpeer JSON rows, as the real client returns them.
    async def search_listings(
        self, names: Sequence[str], *, game: str = "csgo"
    ) -> dict[str, list[dict[str, Any]]]:
        """The configured rows of each name asked for."""
        self.calls += 1
        if self.barrier is not None:
            await self.barrier.wait()
        return {name: list(self.rows.get(name, [])) for name in names}


class OrdersListener:
    """The payloads ``NOTIFY orders`` delivered to a raw asyncpg connection (as the worker
    listens). :meth:`drain` makes every notification committed so far visible."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self.payloads: list[str] = []

    def on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        """asyncpg's listener callback."""
        self.payloads.append(payload)

    async def drain(self) -> list[str]:
        """One round trip: the server sends pending notifications before it answers."""
        await self._conn.execute("SELECT 1")
        await asyncio.sleep(0.05)
        return list(self.payloads)


@asynccontextmanager
async def listen_orders() -> AsyncIterator[OrdersListener]:
    """LISTEN on the orders channel on its own connection for the ``with`` block."""
    dsn = os.environ["CSMARKET_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    listener = OrdersListener(conn)
    await conn.add_listener(ORDERS_CHANNEL, listener.on_notify)
    try:
        yield listener
    finally:
        await conn.close()
