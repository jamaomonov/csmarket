"""A fixed world for the analytics tests, every number worked out by hand.

All orders share the factory's CBU rate, 12 650.5 soʻm per dollar; Postgres ``round`` rounds
half away from zero.

| Order | Market    | Status        | Paid (Tashkent)  | Price, сум | Cost, $      | Cost, сум | Profit, сум |
| ----- | --------- | ------------- | ---------------- | ---------- | ------------ | --------- | ----------- |
| A     | Waxpeer   | delivered     | Oct 9 10:00      | 150 000    | 9 (bought)   | 113 855   | 36 145      |
| B     | Skinslink | trade_sent    | Oct 10 09:00     | 130 000    | 9 (agreed)   | 113 855   | 16 145 ✈    |
| C     | LIS-SKINS | delivered     | Oct 9 23:59      | 100 000    | 8.4 (charged)| 106 264   | −6 264      |
| D     | Waxpeer   | refunded 10th | Oct 9 11:00      | 90 000     | —            | —         | not counted |
| E     | API key   | delivered     | Oct 9 12:00      | 50 000     | 3.5 (agreed) | 44 277    | 5 723       |

C's buyer also bought on Sep 1 (returning); A and D share a buyer; new buyers: A's, B's, E's.
A buy-back sale was credited on Oct 9 (site only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from csmarket.modules.orders.models import Order
from csmarket.modules.public_api import keys
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.lisskins_factory import make_lisskins_order
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import make_sale
from tests.integration.skinslink_factory import make_skinslink_order


def utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A UTC instant in 2026 (Tashkent is UTC+5)."""
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


@dataclass(frozen=True)
class World:
    """The orders and buyers built by :func:`build_world`."""

    a: Order
    b: Order
    c: Order
    d: Order
    e: Order
    a_buyer: User
    c_buyer: User
    e_owner: User


PROFIT = {"a": 36_145, "b": 16_145, "c": -6_264, "e": 5_723}
REVENUE = 150_000 + 130_000 + 100_000 + 50_000


def _money(price_uzs: int, price_usd: str, cost_usd: str) -> dict[str, object]:
    return {
        "price_uzs": Decimal(price_uzs),
        "price_usd": Decimal(price_usd),
        "cost_usd": Decimal(cost_usd),
    }


async def build_world(db: AsyncSession) -> World:
    """Build the table above (see the module docstring)."""
    a_buyer = await make_user(db)
    c_buyer = await make_user(db)
    e_owner = await make_user(db)
    a = await make_order(
        db,
        user=a_buyer,
        status="delivered",
        paid_with="payme",
        paid_at=utc(10, 9, 5),
        **_money(150_000, "11", "10"),
    )
    await make_trade(db, a, bought_units=9_000, status=5)
    b, _ = await make_skinslink_order(
        db, status="trade_sent", order={"paid_at": utc(10, 10, 4), **_money(130_000, "10", "9")}
    )
    await make_order(
        db,
        user=c_buyer,
        status="delivered",
        paid_with="click",
        paid_at=utc(9, 1, 5),
        **_money(60_000, "5", "4"),
    )
    c, _ = await make_lisskins_order(
        db,
        status="delivered",
        amount_units=8_400,
        order={"user_id": c_buyer.id, "paid_at": utc(10, 9, 18, 59), **_money(100_000, "8", "8.2")},
    )
    d = await make_order(
        db,
        user=a_buyer,
        status="delivered",
        paid_with="payme",
        paid_at=utc(10, 9, 6),
        refunded_at=utc(10, 10, 6),
        refunded_to="balance",
        **_money(90_000, "7", "6"),
    )
    key, _ = await keys.issue(db, user=e_owner)
    await db.commit()
    e = await make_order(
        db,
        user=e_owner,
        status="delivered",
        paid_with="usd_wallet",
        paid_at=utc(10, 9, 7),
        channel="api",
        api_key_id=key.id,
        **_money(50_000, "4", "3.5"),
    )
    await make_sale(db, status="credited", credited_at=utc(10, 9, 8), amount_usd=Decimal("10"))
    return World(a=a, b=b, c=c, d=d, e=e, a_buyer=a_buyer, c_buyer=c_buyer, e_owner=e_owner)
