"""Rows for orders tests: an order with its item and rate (shared by the M4a suites).

Import as ``from tests.integration.orders_factory import make_order``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from csmarket.core import clock
from csmarket.core.ids import new_id
from csmarket.core.numbers import allocate, order_number
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

#: A trade link shaped like Steam's; the partner and token are fake.
FAKE_TRADE_LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE"


async def make_item_and_rate(db: AsyncSession) -> tuple[SkinItem, FxSnapshot]:
    """A committed catalogue item and USD/UZS rate an order can point at."""
    item = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug=f"ak-47-redline-field-tested-{uuid4().hex[:6]}",
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
