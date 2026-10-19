# Admin Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin «Аналитика» page — gross profit by day and period in soʻm and USD, a month
calendar, and breakdowns by market, channel, payment, category, skin, buyer, buy-back,
refunds and «Продано в минус».

**Architecture:** A read-only backend module `analytics` builds one per-order subquery
(`order_lines`: revenue, the market's actual cost, the order's own CBU rate, day, flags) and
groups it per block in SQL; buy-back comes from the `sales` module's P&L over a
`(since, until)` window. Answers are cached in Redis. The admin SPA gets a page with two tabs
and recharts charts. The dashboard moves to the same cost function.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Postgres 16, Redis 7, pytest + testcontainers;
React 19, TanStack Query 5, recharts 2.15, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-19-analytics-design.md`

## Global Constraints

- Money: `Decimal` in Python, digit strings on the wire; soʻm whole (`core.money.wire_uzs`),
  USD six places (`admin.order_query.usd` style), percent one decimal.
- Days are Tashkent days: `func.timezone("Asia/Tashkent", col)` cast to `Date` in SQL; window
  edges `datetime.combine(d, time(0), tzinfo=TASHKENT)` (`orders.api.TASHKENT`).
- Cost USD = `COALESCE(skin_trades.bought_units/1000, skinslink_purchases.amount_units/1000,
lisskins_purchases.amount_units/1000, orders.cost_usd)`; cost soʻm = cost USD ×
  `fx_snapshots.usd_uzs` of `orders.fx_snapshot_id`, rounded to whole soʻm.
- A counted order: `paid_at` in the window, `refunded_at IS NULL`; earned = `status='delivered'`.
- Window ≤ 366 days (422 `analytics_window`); admin only (`require_admin`).
- Module rules (AGENTS.md §4): import other modules only via their `api.py`; mount the router
  in `api/v1/router.py`; a new dependency needs an ADR; mypy --strict, ruff, files ≤ 400 LOC.
- Copy: Russian in the admin, short; skin names stay English.
- Commit after every task (Conventional Commits, scope `api/analytics`, `admin/analytics`, …),
  trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Docker is off on the laptop: integration tests run on CI; locally run ruff, mypy, unit
  tests, eslint, tsc, vitest. If Docker is up, run the integration tests too.

## Review Focus

1. An order refunded **after** its paid day: it must leave that day's profit and appear in
   «Возвраты» on the refund day, never both counted as profit.
2. A Skinslink / LIS-SKINS order whose purchase has no `amount_units` yet: cost falls back to
   `orders.cost_usd`, and it is «в пути», not a loss.
3. A day boundary at 23:59 / 00:01 Tashkent, and a window `until` that is today (open day).
4. `channel=api` with buy-back: buy-back is site-only, so it shows zeros, not the site's.
5. An old rate: an order from a week ago is costed at its own snapshot, not today's rate.

---

## File Structure

Backend (`apps/api/src/csmarket/`):

- `modules/orders/costing.py` — **new**: `spent()` (Python) and `spent_usd_sql()` (SQL), the
  one cost rule. `orders/api.py` exports both; `admin/order_query.py` re-exports `spent`.
- `modules/orders/dashboard.py` — modify: cost via `spent_usd_sql()` with all three joins.
- `modules/sales/pnl.py`, `pnl_query.py` — modify: `income_uzs` / `profit_uzs`, and
  `sales_pnl_between(db, since, until)`; `sales_pnl` delegates. `sales/api.py` exports it.
- `modules/sales/models.py` + `migrations/versions/0037_sales_credited_at.py` — index.
- `modules/analytics/` — **new**: `window.py` (dates, previous period, TTL), `lines.py`
  (`order_lines` subquery), `business.py` (tiles + by-day), `blocks.py` (breakdowns),
  `calendar.py`, `losses.py`, `cache.py`, `schemas.py`, `routes.py`, `api.py`, `README.md`.
- `api/v1/router.py` — mount; `migrations/env.py` needs nothing (no models).

Admin (`apps/admin/src/`):

- `features/analytics/` — **new**: `api.ts`, `keys.ts`, `AnalyticsPage.tsx`, `BusinessTab.tsx`,
  `Tiles.tsx`, `blocks/*.tsx`, `CalendarTab.tsx`, `charts/DayChart.tsx`, `charts/BarList.tsx`,
  `period.ts`, tests.
- `app/router.tsx`, `app/Layout.tsx` — route and menu item.
- `features/dashboard/DashboardPage.tsx` — a link «Аналитика →».

Docs: `docs/decisions/00NN-recharts.md`, `modules/analytics/README.md`,
`docs/architecture/module-map.md`, `docs/architecture/cache-keys.md`, `docs/api/openapi.json`.

---

### Task 1: One cost rule for the dashboard and the analytics

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/costing.py`
- Modify: `apps/api/src/csmarket/modules/orders/api.py`, `modules/orders/dashboard.py:104-124,151`,
  `modules/admin/order_query.py:92-98`
- Test: `apps/api/tests/integration/test_admin_dashboard.py`, `apps/api/tests/unit/test_orders_costing.py`

**Interfaces:**

- Produces: `spent(order, trade, bought) -> Decimal` (moved, same behaviour);
  `spent_usd_sql() -> ColumnElement[Decimal]` — valid in a statement that outer-joins
  `SkinTrade`, `SkinslinkPurchase`, `LisskinsPurchase` on `order_id == Order.id`.

- [ ] **Step 1: Write the failing dashboard test**

Append to `test_admin_dashboard.py`:

```python
async def test_the_margin_uses_what_skinslink_and_lisskins_really_charged(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    paid = NOW - timedelta(hours=1)
    # Checkout agreed $9; the markets charged $8.5 (Skinslink) and $8 (LIS-SKINS).
    await make_skinslink_order(
        db_session,
        status="delivered",
        amount_units=8_500,
        order={"paid_at": paid, "price_usd": Decimal("10"), "cost_usd": Decimal("9")},
    )
    await make_lisskins_order(
        db_session,
        status="delivered",
        amount_units=8_000,
        order={"paid_at": paid, "price_usd": Decimal("10"), "cost_usd": Decimal("9")},
    )
    body = await _get(integration_client, headers, 1)
    assert Decimal(body["sales"]["cost_usd"]) == Decimal("16.5")
    assert Decimal(body["sales"]["margin_usd"]) == Decimal("3.5")
```

If `make_skinslink_order` has no `order=` override (it takes `**purchase` only), add one in
`tests/integration/skinslink_factory.py` exactly like `make_lisskins_order`'s `order:
dict[str, object] | None = None`, merged into the `make_order` call.

- [ ] **Step 2: Run it — expect FAIL** (cost 18: the checkout cost)

Run: `cd apps/api && uv run pytest tests/integration/test_admin_dashboard.py -k really_charged -q --no-cov`
Expected: FAIL `assert Decimal('18') == Decimal('16.5')` (CI if Docker is off).

- [ ] **Step 3: Create `orders/costing.py`**

```python
"""What an order really cost: the market's charge once it says, the agreed cost until then.

One rule for every reader (the admin order page, the dashboard, the analytics): Waxpeer's
``skin_trades.bought_units``, else the Skinslink / LIS-SKINS purchase's ``amount_units``
(USD × 1000), else ``orders.cost_usd`` from checkout.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ColumnElement, func

from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.sources import PurchaseRow
from csmarket.modules.skinslink.api import SkinslinkPurchase

_UNITS = Decimal(1000)


def spent(order: Order, trade: SkinTrade | None, bought: PurchaseRow | None) -> Decimal:
    """What the market charged, USD; the agreed cost until it says."""
    if trade is not None and trade.bought_units is not None:
        return Decimal(trade.bought_units) / _UNITS
    if bought is not None and bought.amount_units is not None:
        return Decimal(bought.amount_units) / _UNITS
    return order.cost_usd


def spent_usd_sql() -> ColumnElement[Decimal]:
    """:func:`spent` in SQL, for a statement outer-joining the trade and both purchases."""
    return func.coalesce(
        SkinTrade.bought_units / _UNITS,
        SkinslinkPurchase.amount_units / _UNITS,
        LisskinsPurchase.amount_units / _UNITS,
        Order.cost_usd,
    )


__all__ = ["spent", "spent_usd_sql"]
```

Check where `PurchaseRow` lives (`grep -n "PurchaseRow" modules/orders/*.py`) and import it
from there. Add `spent` and `spent_usd_sql` to `orders/api.py` (import + `__all__`). In
`admin/order_query.py` delete the local `spent` and import it: `from csmarket.modules.orders.api import Order, PurchaseRow, SkinTrade, spent` (keep the name in that module's exports so
`orders_service` keeps working).

- [ ] **Step 4: Use it in the dashboard**

In `orders/dashboard.py::_by_day`, replace the `cost = func.coalesce(...)` line with
`cost = spent_usd_sql()` and add the two joins after the `SkinTrade` one:

```python
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
```

Import `from csmarket.modules.orders.costing import spent_usd_sql`. Update the module
docstring's cost line to «cost = what the market charged (`costing.spent`)».

- [ ] **Step 5: Unit test for `spent`**

`apps/api/tests/unit/test_orders_costing.py`:

```python
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from csmarket.modules.orders.costing import spent


def _o(cost: str) -> Any:
    return SimpleNamespace(cost_usd=Decimal(cost))


def test_the_market_charge_wins_over_the_agreed_cost() -> None:
    assert spent(_o("9"), SimpleNamespace(bought_units=8_200), None) == Decimal("8.2")
    assert spent(_o("9"), None, SimpleNamespace(amount_units=8_500)) == Decimal("8.5")


def test_the_agreed_cost_stands_until_the_market_says() -> None:
    assert spent(_o("9"), SimpleNamespace(bought_units=None), None) == Decimal("9")
    assert spent(_o("9"), None, SimpleNamespace(amount_units=None)) == Decimal("9")
```

- [ ] **Step 6: Run** `uv run pytest apps/api/tests/unit/test_orders_costing.py -q --no-cov`
      (PASS), `uv run ruff check apps/api && uv run mypy apps/api/src` (clean), and the
      dashboard + admin orders integration tests when Docker is up (PASS).

- [ ] **Step 7: Commit** — `fix(api/orders): cost the dashboard at what every market charged`

---

### Task 2: Buy-back P&L over any window, in soʻm too

**Files:**

- Modify: `modules/sales/pnl.py` (`SalePnl.income_uzs`), `modules/sales/pnl_query.py`
  (`PnlDay.profit_uzs`, `SalesPnl.income_uzs/profit_uzs`, `sales_pnl_between`),
  `modules/sales/api.py`, `modules/admin/dashboard_schemas.py` (if it maps fields one by one)
- Test: `apps/api/tests/unit/test_sales_pnl.py` (exists? else create), `apps/api/tests/integration/test_sales_pnl_window.py`

**Interfaces:**

- Produces: `sales_pnl_between(db, *, since: datetime, until: datetime) -> SalesPnl`
  (`until` exclusive, `by_day` one row per Tashkent day in `[since, until)`);
  `SalesPnl.income_uzs`, `SalesPnl.profit_uzs`, `PnlDay.profit_uzs` (whole soʻm).

- [ ] **Step 1: Failing unit test** (in `test_sales_pnl.py`):

```python
def test_income_in_som_is_the_credit_at_the_cbu_rate() -> None:
    row = PnlRow(
        payout_to="balance", status="credited", attention_reason=None,
        quoted_usd=Decimal("10"), amount_usd=Decimal("10"), items_uzs=Decimal(120_000),
        payout_uzs=Decimal(120_000), rate=Decimal("12000"), cbu_rate=Decimal("12650.5"),
    )
    p = sale_pnl(row, Decimal("0.5"))
    assert p.income_uzs == Decimal(126_505)
```

- [ ] **Step 2: Run — FAIL** (`SalePnl` has no `income_uzs`).

- [ ] **Step 3: Implement.** In `pnl.py` add `income_uzs: Decimal = _ZERO` to `SalePnl` and in
      `sale_pnl`: `income = _income(row)`; `income_uzs=(income * rate).quantize(Decimal(1))`.
      In `pnl_query.py`: add `"income_uzs"` to `_total`'s keys; `PnlDay.profit_uzs`;
      `SalesPnl.profit_uzs = income_uzs − cost_uzs`. Split `sales_pnl`:

```python
async def sales_pnl_between(db: AsyncSession, *, since: datetime, until: datetime) -> SalesPnl:
    """The skin-sales P&L of ``[since, until)``, one row per Tashkent day. Reads only."""
    pct = (await read_sale_settings(db)).bank_fee_pct
    day_of = cast(func.timezone("Asia/Tashkent", DONE_AT), Date)
    stmt = (
        select(Sale, PayoutRequest, _cbu_rate(), day_of)
        .outerjoin(PayoutRequest, PayoutRequest.sale_id == Sale.id)
        .where(DONE_AT >= since, DONE_AT < until)
    )
    per_day: dict[date, list[SalePnl]] = {}
    for sale, request, cbu, day in (await db.execute(stmt)).all():
        per_day.setdefault(day, []).append(sale_pnl(_row(sale, request, cbu), pct))
    days = (until.astimezone(TASHKENT).date() - since.astimezone(TASHKENT).date()).days
    return _summed(per_day, since.astimezone(TASHKENT).date(), days)


async def sales_pnl(db: AsyncSession, *, days: Days, at: datetime) -> SalesPnl:
    """The dashboard's window: the ``days`` Tashkent days ending at ``at``."""
    since = window_start(at, days)
    return await sales_pnl_between(db, since=since, until=at + timedelta(microseconds=1))
```

Move the summing loop of the old `sales_pnl` into `_summed(per_day, first, days)` unchanged
except the new soʻm fields. `until` for the dashboard is `at` inclusive, hence `+1 µs`.
Import `TASHKENT` from `orders.api`. Export `sales_pnl_between` from `sales/api.py`.

- [ ] **Step 4: Integration test** `test_sales_pnl_window.py`: two sales credited on
      2026-10-01 23:30 and 2026-10-02 00:30 Tashkent (`make_sale(..., status="credited",
credited_at=…, amount_usd=Decimal("10"))`); `sales_pnl_between(since=Oct 2 00:00 TASHKENT,
until=Oct 3 00:00)` → `count == 1`, one `by_day` row, `profit_uzs ==
income_uzs − cost_uzs`.
- [ ] **Step 5: Run** unit tests (PASS), ruff, mypy; integration on CI.
- [ ] **Step 6: Commit** — `feat(api/sales): the buy-back p&l over any window, in soʻm too`

---

### Task 3: Index for the buy-back day

**Files:** `modules/sales/models.py:178`, `migrations/versions/0037_sales_credited_at.py`

- [ ] **Step 1:** In `Sale.__table_args__` add
      `Index("ix_sales_credited_at", "credited_at", postgresql_where=text("credited_at IS NOT NULL")),`.
- [ ] **Step 2:** Migration:

```python
"""sales: an index on credited_at for the analytics' buy-back days

Revision ID: 0037_sales_credited_at
Revises: 0036_kassa_fee
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_sales_credited_at"
down_revision: str | None = "0036_kassa_fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index ``sales.credited_at`` (set rows only)."""
    op.create_index(
        "ix_sales_credited_at",
        "sales",
        ["credited_at"],
        postgresql_where=sa.text("credited_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the index."""
    op.drop_index("ix_sales_credited_at", table_name="sales")
```

- [ ] **Step 3:** The migrations test (`tests/integration/test_migrations*.py`, models vs
      head) passes on CI. **Commit** — `feat(api/sales): index sales.credited_at`

---

### Task 4: `analytics` module — window, per-order lines, business totals

**Files:**

- Create: `modules/analytics/{__init__,window,lines,business,schemas,api}.py`
- Test: `apps/api/tests/unit/test_analytics_window.py`, `apps/api/tests/integration/test_analytics_business.py`, `apps/api/tests/integration/analytics_world.py` (fixtures)

**Interfaces:**

- Produces:
  - `Window(since: date, until: date)` (frozen; `until` inclusive), `.start`/`.end`
    (datetimes, `end` exclusive), `.days`, `.previous()`, `.ttl(today) -> int`;
    `parse_window(since, until) -> Window` raising `ValidationError(code="analytics_window")`.
  - `Channel = Literal["all", "site", "api"]`.
  - `order_lines(w: Window, channel: Channel) -> Subquery` with columns `order_id, number,
user_id, day, earned (bool), source, channel, api_key_id, paid_with, skin_item_id,
name, revenue_uzs, revenue_usd, cost_usd, cost_uzs, profit_uzs, profit_usd`.
  - `totals(db, w, channel) -> Totals` and `by_day(db, w, channel) -> list[DayOut]`.

- [ ] **Step 1: Unit tests for the window** (`test_analytics_window.py`):

```python
from datetime import date

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.analytics.window import parse_window


def test_until_is_inclusive_and_the_previous_period_has_the_same_length() -> None:
    w = parse_window(date(2026, 10, 1), date(2026, 10, 7))
    assert w.days == 7
    assert (w.previous().since, w.previous().until) == (date(2026, 9, 24), date(2026, 9, 30))
    assert w.end.isoformat() == "2026-10-08T00:00:00+05:00"


def test_a_window_past_366_days_or_backwards_is_refused() -> None:
    for since, until in ((date(2025, 1, 1), date(2026, 1, 3)), (date(2026, 10, 2), date(2026, 10, 1))):
        with pytest.raises(ValidationError) as e:
            parse_window(since, until)
        assert e.value.code == "analytics_window"


def test_a_settled_window_is_cached_long() -> None:
    w = parse_window(date(2026, 9, 1), date(2026, 9, 30))
    assert w.ttl(date(2026, 10, 19)) == 3600
    assert w.ttl(date(2026, 10, 5)) == 120
```

- [ ] **Step 2: Run — FAIL** (module missing).
- [ ] **Step 3: `window.py`**

```python
"""An analytics window: Tashkent dates, ``until`` inclusive (spec 2026-10-19-analytics)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from csmarket.core.errors import ValidationError
from csmarket.modules.orders.api import TASHKENT

Channel = Literal["all", "site", "api"]
MAX_DAYS = 366
#: Past Steam's 7-day protection a day no longer moves.
SETTLED_AFTER = timedelta(days=8)
SHORT_TTL, LONG_TTL = 120, 3600


class Window(BaseModel):
    """``[since, until]`` in Tashkent days."""

    model_config = ConfigDict(frozen=True)

    since: date
    until: date

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1

    @property
    def start(self) -> datetime:
        return datetime.combine(self.since, time(0), tzinfo=TASHKENT)

    @property
    def end(self) -> datetime:
        """Exclusive: 00:00 Tashkent after ``until``."""
        return datetime.combine(self.until + timedelta(days=1), time(0), tzinfo=TASHKENT)

    def previous(self) -> Window:
        """The same length right before ``since``."""
        return Window(since=self.since - timedelta(days=self.days), until=self.since - timedelta(days=1))

    def ttl(self, today: date) -> int:
        """Seconds to cache an answer: long once the window has settled."""
        return LONG_TTL if self.until + SETTLED_AFTER < today else SHORT_TTL


def parse_window(since: date, until: date) -> Window:
    """A checked window. Raises ``ValidationError`` ``analytics_window``."""
    if until < since or (until - since).days + 1 > MAX_DAYS:
        raise ValidationError(
            f"the window must be 1..{MAX_DAYS} days, since <= until", code="analytics_window"
        )
    return Window(since=since, until=until)


__all__ = ["Channel", "MAX_DAYS", "Window", "parse_window"]
```

- [ ] **Step 4: `lines.py`** — the per-order subquery every block groups:

```python
"""One row per counted order of a window: revenue, real cost, profit, in soʻm and USD.

A counted order is paid in the window and not refunded; ``earned`` = delivered. Cost is
``orders.api.spent_usd_sql`` (the market's charge, else the agreed cost); soʻm at the order's
own CBU snapshot (``fx_snapshots.usd_uzs``), rounded to whole soʻm.
"""

from __future__ import annotations

from sqlalchemy import Date, Subquery, cast, func, select

from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import Order, SkinTrade, spent_usd_sql
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.skinslink.api import SkinslinkPurchase


def order_lines(w: Window, channel: Channel) -> Subquery:
    """The window's counted orders (see the module docstring)."""
    cost_usd = spent_usd_sql()
    cost_uzs = func.round(cost_usd * FxSnapshot.usd_uzs)
    stmt = (
        select(
            Order.id.label("order_id"),
            Order.number.label("number"),
            Order.user_id.label("user_id"),
            cast(func.timezone("Asia/Tashkent", Order.paid_at), Date).label("day"),
            Order.paid_at.label("paid_at"),
            (Order.status == "delivered").label("earned"),
            Order.source.label("source"),
            Order.channel.label("channel"),
            Order.api_key_id.label("api_key_id"),
            Order.paid_with.label("paid_with"),
            Order.skin_item_id.label("skin_item_id"),
            Order.market_hash_name.label("name"),
            SkinItem.category.label("category"),
            Order.price_uzs.label("revenue_uzs"),
            Order.price_usd.label("revenue_usd"),
            cost_usd.label("cost_usd"),
            cost_uzs.label("cost_uzs"),
            (Order.price_uzs - cost_uzs).label("profit_uzs"),
            (Order.price_usd - cost_usd).label("profit_usd"),
        )
        .select_from(Order)
        .join(FxSnapshot, FxSnapshot.id == Order.fx_snapshot_id)
        .outerjoin(SkinItem, SkinItem.id == Order.skin_item_id)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
        .where(Order.paid_at >= w.start, Order.paid_at < w.end, Order.refunded_at.is_(None))
    )
    if channel != "all":
        stmt = stmt.where(Order.channel == channel)
    return stmt.subquery("lines")


__all__ = ["order_lines"]
```

Check `FxSnapshot` is exported by `fx/api.py` and `SkinItem` by `skins/api.py` (both are).

- [ ] **Step 5: `schemas.py`** (wire shapes; money as strings):

```python
class Money(BaseModel):
    uzs: str
    usd: str


class Totals(BaseModel):
    orders: int
    revenue: Money
    cost: Money
    profit: Money
    #: Profit / revenue (soʻm), one decimal; "0" without revenue.
    margin_percent: str
    #: Delivered part of ``profit`` and the part still in flight.
    earned_profit_uzs: str
    in_flight_profit_uzs: str
    in_flight_orders: int
    average_check_uzs: str
    buyback_profit_uzs: str
    buyback_profit_usd: str
    refunds: int
    refunds_uzs: str
    new_buyers: int
    #: Orders profit + buy-back profit, soʻm.
    gross_profit_uzs: str


class DayOut(BaseModel):
    day: date
    orders: int
    revenue_uzs: str
    earned_profit_uzs: str
    in_flight_profit_uzs: str
    buyback_profit_uzs: str
```

(The breakdown shapes come in Task 5; `BusinessOut` there wraps `totals`, `previous`,
`by_day` and the blocks.)

- [ ] **Step 6: `business.py`** — totals and by-day from `order_lines`, buy-back from
      `sales.api.sales_pnl_between`, refunds and new buyers from `orders`:

```python
async def _orders_by_day(db: AsyncSession, w: Window, channel: Channel) -> dict[date, _Day]:
    lines = order_lines(w, channel)
    earned = case((lines.c.earned, lines.c.profit_uzs), else_=0)
    flying = case((lines.c.earned, 0), else_=lines.c.profit_uzs)
    rows = await db.execute(
        select(
            lines.c.day,
            func.count(),
            func.sum(lines.c.revenue_uzs),
            func.sum(lines.c.revenue_usd),
            func.sum(lines.c.cost_uzs),
            func.sum(lines.c.cost_usd),
            func.sum(earned),
            func.sum(flying),
            func.count().filter(~lines.c.earned),
        ).group_by(lines.c.day)
    )
    return {r[0]: _Day.of(r) for r in rows.all()}
```

`_Day` is a frozen model of those nine numbers (Decimal, zero for NULL sums). `totals()` sums
the days, adds: buy-back (`channel == "api"` → zeros, else `sales_pnl_between(db,
since=w.start, until=w.end)`), refunds (`count`, `Σ price_uzs` of orders with
`refunded_at` in `[start, end)`, the channel filter applied), new buyers:

```python
first_paid = (
    select(Order.user_id, func.min(Order.paid_at).label("first"))
    .where(Order.paid_at.is_not(None))
    .group_by(Order.user_id)
    .subquery()
)
new = await db.scalar(
    select(func.count()).select_from(first_paid)
    .where(first_paid.c.first >= w.start, first_paid.c.first < w.end)
)
```

(with the channel: restrict to users having a counted order of that channel in the window —
`first_paid.c.user_id.in_(select(lines.c.user_id))`). `average_check_uzs` = revenue / orders
rounded; `margin_percent` = profit_uzs / revenue_uzs × 100, one decimal. `by_day()` returns
every day of the window (zeros filled) with the buy-back `profit_uzs` of that day from
`SalesPnl.by_day`.

- [ ] **Step 7: Integration test world** `tests/integration/analytics_world.py` — builds, on
      fixed dates around `NOW = 2026-10-10 07:00 UTC` (12:00 Tashkent), with `make_item_and_rate`'s
      rate 12 650.5:
  - A: Waxpeer, delivered, paid Oct 9 10:00, price 150 000 / $11, cost $10 agreed,
    `bought_units=9_000` → cost $9 = 113 855 сум (9 × 12 650.5 = 113 854.5 → 113 855
    with `round`; assert what Postgres `round` gives: half away from zero → 113 855),
    profit 36 145.
  - B: Skinslink, `trade_sent`, paid Oct 10 09:00, price 130 000 / $10, cost $9, no
    `amount_units` → in flight, cost 113 855, profit 16 145.
  - C: LIS-SKINS, delivered, paid Oct 9 18:59 UTC (= Oct 9 23:59 Tashkent), price
    100 000 / $8, `amount_units=8_400` → loss: cost 106 264 (8.4 × 12 650.5 = 106 264.2),
    profit −6 264.
  - D: Waxpeer, paid Oct 9, refunded Oct 10 (`refunded_at`, `refunded_to="balance"`) — not
    counted; in refunds on Oct 10.
  - E: API channel order (`channel="api"`, an `ApiKey` via `public_api` factory) delivered
    Oct 9, price 50 000 / $4, cost $3.5 → profit 5 723 (50 000 − round(3.5 × 12 650.5 =
    44 276.75) = 50 000 − 44 277).
  - A buyer with an order on Sep 1 (returning) and a buyer whose first order is A (new).
- [ ] **Step 8: Integration tests** `test_analytics_business.py` (call the functions directly
      with `db_session`; routes come in Task 6):

```python
async def test_profit_splits_earned_and_in_flight_and_skips_refunds(db_session) -> None:
    await build_world(db_session)
    t = await totals(db_session, parse_window(date(2026, 10, 9), date(2026, 10, 10)), "all")
    assert t.orders == 4  # A, B, C, E — D was refunded
    assert t.profit.uzs == str(36_145 + 16_145 - 6_264 + 5_723)
    assert t.in_flight_profit_uzs == "16145" and t.in_flight_orders == 1
    assert (t.refunds, t.refunds_uzs) == (1, "<D's price>")


async def test_a_23_59_order_stays_on_its_tashkent_day(db_session) -> None:
    await build_world(db_session)
    days = {d.day: d for d in await by_day(db_session, parse_window(date(2026, 10, 9), date(2026, 10, 10)), "all")}
    assert days[date(2026, 10, 9)].orders == 3  # A, C, E


async def test_the_api_channel_has_no_buy_back(db_session) -> None: ...
async def test_an_old_order_is_costed_at_its_own_rate(db_session) -> None:
    # A second FxSnapshot at 13 000 inserted after the orders must not change A's cost.
    ...
```

Write each `...` body in full with the world's numbers (same pattern as above).

- [ ] **Step 9: Run** unit tests (PASS), ruff, mypy; integration on CI.
- [ ] **Step 10: Commit** — `feat(api/analytics): the window, per-order lines and the totals`

---

### Task 5: Breakdown blocks

**Files:**

- Create: `modules/analytics/blocks.py`, `modules/analytics/buyers.py`
- Modify: `modules/analytics/schemas.py`
- Test: `apps/api/tests/integration/test_analytics_blocks.py`

**Interfaces:**

- Consumes: `order_lines`, `Window`, `Channel`, `sales_pnl_between`.
- Produces (all `async (db, w, channel) -> …`):
  - `by_source -> list[Slice]`, `by_channel -> list[Slice]` (API slices per key owner:
    `key` = owner's display name), `by_payment -> list[Slice]`,
    `by_category -> list[Slice]` — `Slice(key: str, orders: int, revenue_uzs, profit_uzs,
profit_usd, margin_percent)`;
  - `kassa_fees -> list[FeeOut(provider, payments, fee_uzs)]` — succeeded payments with
    `succeeded_at` in the window, all channels;
  - `top_skins -> list[SkinOut(name, image_url, orders, revenue_uzs, profit_uzs)]` (10, by
    profit desc);
  - `buyers -> BuyersOut(new: Count, returning: Count, top: list[BuyerOut])` —
    `BuyerOut(id, display_name, avatar_url, orders, revenue_uzs, profit_uzs)`;
  - `refunds -> RefundsOut(count, amount_uzs, by_source: list[KeyCount], by_reason:
list[KeyCount])` (`failure_reason` NULL → `"other"`);
  - `buyback -> BuybackOut` mapped from `SalesPnl` (count, income_usd, to_cards_uzs,
    to_balances_uzs, to_pay_uzs, profit_uzs, profit_usd).

- [ ] **Step 1: Failing tests** in `test_analytics_blocks.py` against `build_world` (Task 4):
  - `by_source` → waxpeer (A, E) orders 2, lisskins (C) profit "-6264", skinslink (B) 1;
  - `by_channel` → site 3, api 1 with the key owner's name;
  - `by_payment` keys are `paid_with` values;
  - `by_category` → "rifles" (the factory's category) holds all four;
  - `top_skins[0]` is A's name; a loss is last;
  - `buyers.new.count == 1`, `returning.count >= 1`, `top[0].id` the biggest spender;
  - `refunds.by_source == [{"key": "waxpeer", "count": 1}]`;
  - `kassa_fees`: a succeeded Payme payment with `fee_uzs=1500` in the window → `[("payme",
1, "1500")]`, a failed one ignored.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** each as one grouped statement over `order_lines(w, channel)`,
      e.g.:

```python
async def by_source(db: AsyncSession, w: Window, channel: Channel) -> list[Slice]:
    """Orders, revenue and profit per market, biggest revenue first."""
    lines = order_lines(w, channel)
    return await _slices(db, lines, lines.c.source)


async def _slices(db: AsyncSession, lines: Subquery, key: ColumnElement[Any]) -> list[Slice]:
    rows = await db.execute(
        select(
            func.coalesce(key, "other"),
            func.count(),
            func.sum(lines.c.revenue_uzs),
            func.sum(lines.c.profit_uzs),
            func.sum(lines.c.profit_usd),
        )
        .group_by(1)
        .order_by(func.sum(lines.c.revenue_uzs).desc())
    )
    return [Slice.of(*r) for r in rows.all()]
```

`by_channel` keys API rows by the key owner: outer-join `ApiKey` (`public_api.api`) and
`User` (`users.api`) on `lines.c.api_key_id`, key = `case((lines.c.channel == "site", "Сайт"), else_=func.coalesce(User.display_name, "API"))`. `top_skins` groups by `name`, joins
`SkinItem.image_url` via `skin_item_id` (`func.max(lines.c.skin_item_id)`), limit 10.
`buyers.top` groups by `user_id`, joins `User` for name and avatar, limit 10. Keep
`blocks.py` under 400 lines (buyers and refunds in `buyers.py` if needed).

- [ ] **Step 4: Run** (CI), ruff, mypy. **Commit** — `feat(api/analytics): the breakdown blocks`

---

### Task 6: Routes, calendar, losses, cache

**Files:**

- Create: `modules/analytics/{calendar,losses,cache,routes}.py`, `modules/analytics/README.md`
- Modify: `api/v1/router.py` (mount `analytics_router` with the admin routers),
  `infra/prometheus/alerts/api.yml` only if a latency regex lists admin routes explicitly
  (check; the analytics reads only the DB — no carve-out)
- Test: `apps/api/tests/integration/test_analytics_routes.py`

**Interfaces:**

- Produces:
  - `GET /api/v1/admin/analytics/business?since=YYYY-MM-DD&until=YYYY-MM-DD&channel=all|site|api` → `BusinessOut {window, totals, previous: Totals, by_day, sources,
channels, payments, kassa_fees, categories, top_skins, buyers, refunds, buyback}`;
  - `GET /api/v1/admin/analytics/calendar?month=YYYY-MM&channel=` → `CalendarOut {month,
days: list[DayOut]}` (one per day of the month; future days zero);
  - `GET /api/v1/admin/analytics/losses?since=&until=&channel=` → `LossesOut {items:
list[LossOut(number, name, paid_at, source, revenue_uzs, cost_uzs, profit_uzs)]}`
    — delivered lines with `profit_uzs < 0`, worst first, at most 200.
  - `cached(redis, key, ttl, build)` in `cache.py`: JSON in Redis under
    `csmarket:analytics:v1:<endpoint>:<since>:<until>:<channel>`.

- [ ] **Step 1: Failing route tests:**

```python
BASE = "/api/v1/admin/analytics"


async def test_business_answers_the_window_and_its_previous(integration_client, admin_headers, db_session) -> None:
    await build_world(db_session)
    r = await integration_client.get(f"{BASE}/business", params={"since": "2026-10-09", "until": "2026-10-10"}, headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["orders"] == 4
    assert body["previous"]["orders"] == 0
    assert [d["day"] for d in body["by_day"]] == ["2026-10-09", "2026-10-10"]


async def test_a_window_past_366_days_is_422(integration_client, admin_headers) -> None:
    r = await integration_client.get(f"{BASE}/business", params={"since": "2025-01-01", "until": "2026-10-10"}, headers=await admin_headers())
    assert (r.status_code, r.json()["code"]) == (422, "analytics_window")


async def test_the_calendar_has_every_day_of_the_month(...) -> None:
    # month=2026-10 → 31 rows; Oct 9 profit matches the world.


async def test_losses_list_only_delivered_negatives(...) -> None:
    # C only.


async def test_analytics_is_admin_only(integration_client, customer_headers) -> None:
    for path in ("business?since=2026-10-01&until=2026-10-01", "calendar?month=2026-10", "losses?since=2026-10-01&until=2026-10-01"):
        assert (await integration_client.get(f"{BASE}/{path}", headers=await customer_headers())).status_code == 403


async def test_a_second_call_is_served_from_the_cache(...) -> None:
    # call business; add an order in the window; call again → same totals; delete the
    # Redis key → the new order counts.
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** `routes.py` (parse and dispatch only — `since`/`until` as `date`
      query params, `month` as `str` matched `^\d{4}-\d{2}$` → `Window(first, last day)`;
      `channel: Channel = "all"`), `cache.py`:

```python
async def cached[T: BaseModel](
    redis: Redis, key: str, ttl: int, model: type[T], build: Callable[[], Awaitable[T]]
) -> T:
    """``build()``'s answer, kept ``ttl`` seconds under ``key``."""
    hit = await redis.get(key)
    if hit is not None:
        return model.model_validate_json(hit)
    value = await build()
    await redis.set(key, value.model_dump_json(), ex=ttl)
    return value
```

`today` for the TTL is `now().astimezone(TASHKENT).date()` (`core.clock.now`). Mount the
router in `api/v1/router.py` beside `admin_dashboard_router`. Write `README.md` (what it
owns: nothing; what it reads; the formulas = the spec's Definitions table by reference; the
cache keys; the endpoints).

- [ ] **Step 4: Run** (CI), ruff, mypy, `make gen-api` (commit `docs/api/openapi.json` and the
      client). **Commit** — `feat(api/analytics): business, calendar and losses endpoints`

---

### Task 7: recharts and the admin API client

**Files:**

- Create: `docs/decisions/00NN-recharts-for-admin-charts.md` (next free number:
  `ls docs/decisions | tail -2`), `apps/admin/src/features/analytics/{api,keys,period}.ts`,
  `apps/admin/src/features/analytics/period.test.ts`
- Modify: `apps/admin/package.json`, `pnpm-lock.yaml`

- [ ] **Step 1:** `pnpm add --filter @csmarket/admin recharts@2.15.4` (React 19 is supported
      from 2.15; commit the lockfile).
- [ ] **Step 2: ADR** — context (charts for analytics; YuPay uses recharts), decision
      (recharts 2.15, admin only, lazy-loaded with the page via `React.lazy` so other admin pages
      do not pay its ~100 KB gz), consequences (one dependency; the storefront unaffected).
- [ ] **Step 3: `period.ts` + test** — `type Period = {kind: "days", days: 7|30|90} | {kind:
"month", month: string} | {kind: "range", since: string, until: string}`;
      `windowOf(p, today) -> {since, until}` (Tashkent dates as `YYYY-MM-DD`); `toParams` /
      `fromParams` for the URL (`?p=30`, `?m=2026-10`, `?from=…&to=…`, `?ch=api`). Tests: 30 days
      ending today; a month's first and last day (Feb 2028 → 29); a bad `from` falls back to 30
      days.
- [ ] **Step 4: `api.ts`** — interfaces mirroring Task 4–6 schemas (money as `string`),
      `getBusiness(since, until, channel)`, `getCalendar(month, channel)`, `getLosses(since,
until, channel)` via `session.apiGet`; `keys.ts` — `["admin", "analytics", …]`.
- [ ] **Step 5: Run** `cd apps/admin && npx vitest run src/features/analytics && npx tsc
--noEmit -p .` (PASS). **Commit** — `feat(admin/analytics): recharts, the api client and periods`

---

### Task 8: «Бизнес» tab

**Files:**

- Create: `features/analytics/{AnalyticsPage,BusinessTab,Tiles}.tsx`,
  `features/analytics/charts/{DayChart,BarList}.tsx`,
  `features/analytics/blocks/{Sources,Channels,Payments,Categories,TopSkins,Buyers,Buyback,Refunds,Losses}.tsx`,
  `features/analytics/BusinessTab.test.tsx`, `features/analytics/fixtures.ts`
- Modify: `app/router.tsx` (`{ path: "/analytics", element: <AnalyticsPage /> }` lazy),
  `app/Layout.tsx` (NAV after «Дашборд»: `{ to: "/analytics", label: "Аналитика" }`),
  `features/dashboard/DashboardPage.tsx` (a «Аналитика →» link in the header actions)

**Interfaces:**

- Consumes: `api.ts`, `period.ts`, `@/components/{Section,DataTable,UserCell,SkinThumb,Money,Tabs}`,
  `@/lib/format` (`formatSum`, `formatUsd`).

- [ ] **Step 1: Failing tests** (mock `./api`; fixture `BUSINESS` with the world's numbers):
  - the tiles show «Оборот», «Валовая прибыль» with the soʻm and the USD line, and «▲ +12 %»
    when `previous` is lower (and «▼» when higher, «—» when the previous is 0);
  - changing the period to «90 дней» calls `getBusiness` with the 90-day window;
  - the channel switch «API» calls with `channel=api`;
  - «Площадки» lists Waxpeer, Skinslink, LIS-SKINS with their profit;
  - «Покупатели» links a top buyer to `/users/{id}`;
  - «Продано в минус» shows the empty text «Нет — так и должно быть.» when the list is empty
    and an order link otherwise;
  - the chart container renders (`data-testid="day-chart"`); recharts is not asserted on.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement.**
  - `AnalyticsPage`: `PageHeader title="Аналитика"`, `Tabs` «Бизнес» / «Календарь» kept in
    `?tab=`, the period and channel read and written through `useUrlParams` (the existing
    hook) and `period.ts`.
  - `Tiles`: a grid `grid-cols-2 sm:grid-cols-4`, each tile value + `Delta` (`(cur − prev) /
|prev|`, one decimal, green up for money and orders, red up for refunds).
  - `DayChart`: recharts `ResponsiveContainer` + `ComposedChart` — bars `earned_profit_uzs`
    and `in_flight_profit_uzs` stacked, a line `revenue_uzs` on a right axis; colours from
    CSS variables (`var(--color-accent)`, `var(--color-fg-muted)`); tooltip with `formatSum`.
  - `BarList`: a plain list of rows with a proportional bar (div width %), key, orders,
    revenue, profit, margin — used by Sources, Channels, Payments, Categories (no recharts).
  - Blocks wrap `Section`; tables via `DataTable` with `mobileCard`.
  - Losses block fetches `getLosses` for the same window (its own query).
- [ ] **Step 4: Run** `npx vitest run src/features/analytics && npx eslint src --max-warnings
0 && npx tsc --noEmit -p .` (PASS). **Commit** — `feat(admin/analytics): the business tab`

---

### Task 9: «Календарь» tab

**Files:**

- Create: `features/analytics/CalendarTab.tsx`, `features/analytics/CalendarTab.test.tsx`

- [ ] **Step 1: Failing tests:**
  - October 2026 renders 31 day cells, the first in the Thursday column (Monday first);
  - a cell shows revenue and profit (`formatSum`), a loss day has `data-tone="loss"`, a day
    without orders `data-tone="empty"`;
  - ‹ › change the month and call `getCalendar("2026-09")`;
  - a click on the 9th switches to «Бизнес» with `from=2026-10-09&to=2026-10-09`; a click on
    the 9th then the 12th selects `from=2026-10-09&to=2026-10-12`; the chip «← к месяцу»
    returns to the calendar.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — a 7-column grid; tint by `profit / max profit of the month`
      (accent with opacity 0.15..1), red tint for a negative day; on a phone (`useNarrow`) cells
      show profit only.
- [ ] **Step 4: Run** (PASS). **Commit** — `feat(admin/analytics): the calendar tab`

---

### Task 10: Docs and the finish

**Files:** `docs/architecture/module-map.md`, `docs/architecture/cache-keys.md`,
`AGENTS.md` §0 one line («Аналитика» in the admin, spec link), `docs/runbooks/` none (no new
operational concern).

- [ ] **Step 1:** module-map: `analytics` — reads `orders`, `sales`, `payments`, `fx`,
      `skins`, `users`, `public_api`; owns nothing. cache-keys: the key pattern, TTLs 120 s /
      3600 s, invalidation: none (short TTL; a settled window cannot change).
- [ ] **Step 2:** `make gen-api`; `npx prettier --check .` from the repo root;
      `uv run ruff check apps/api && uv run mypy apps/api/src apps/api/tests`;
      `cd apps/admin && npx vitest run && npx eslint src --max-warnings 0 && npx tsc --noEmit -p .`.
- [ ] **Step 3: Commit** — `docs(analytics): module map, cache keys and the status line`

---

## Self-review

- **Spec coverage:** rulings 1–2 (soʻm + USD, order's own rate) → Task 4 `order_lines`;
  ruling 3 (paid day, earned / in flight, refunds out) → Task 4; ruling 5 (all breakdowns,
  previous period) → Tasks 4–5, 8; ruling 6 (losses) → Task 6, 8; ruling 7 (recharts, ADR)
  → Task 7; calendar → Tasks 6, 9; dashboard cost alignment → Task 1; buy-back window and
  soʻm → Task 2; index → Task 3; cache → Task 6; docs → Tasks 6, 10.
- **Types:** `Window`, `Channel`, `order_lines`, `Totals`, `DayOut`, `Slice`, `BusinessOut`
  are named the same in every task.
- **Review Focus** items 1–5 each have a test: refund-after-paid (Task 4 world D), Skinslink
  without `amount_units` (world B), 23:59 (world C), api without buy-back (Task 4 test),
  old rate (Task 4 test).
