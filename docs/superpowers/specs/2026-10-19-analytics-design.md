# Admin analytics

Approved in conversation with the owner on 2026-10-14 (scope: «вариант 2») and 2026-10-19
(everything below). Kassa fees, its prerequisite, shipped first
(`2026-10-14-kassa-fee-design.md`). Business expenses (servers, ads, salaries, taxes) are a
second stage with their own spec; this page shows **gross** profit.

## Goal

The owner sees what the business earns per day and per any period, the skin sales and the
buy-back (выкуп) apart, finds good and bad days, and sees where the money comes from: market,
channel, payment method, category, skin, buyer. Accuracy over simplicity: every order is
costed at what the market actually charged, at the rate the order itself was priced with.

## Owner rulings

1. **Currency:** soʻm first, dollars beside them (smaller). Money comes in soʻm and goes to
   the markets in dollars, so both are shown.
2. **Rate:** a dollar cost becomes soʻm at the **CBU rate fixed in the order**
   (`orders.fx_snapshot_id → fx_snapshots.usd_uzs`), without our uplift; what the uplift
   earns is part of the profit. A buy-back sale: the CBU rate at the sale, as the «Выкуп» block
   already does.
3. **When an order counts:** on its payment day (Tashkent), split into **«заработано»**
   (delivered) and **«в пути»** (paid, not delivered yet: buying, trade sent, Steam's
   protection). A refund takes the order out of the profit.
4. **Expenses:** later, a second stage.
5. **Breakdowns:** all of them (below), each figure compared with the previous period of the
   same length.
6. **No «top losing skins»:** a normal buy cannot lose (the worker never pays a market more
   than the cost agreed at checkout). The page lists **«Продано в минус»** instead — delivered
   orders with a negative margin, which only a manual price rule, a market keeping money for a
   failed trade, or a partner key priced at cost can produce. An empty list is the normal day.
7. **Charts:** recharts (as in YuPay), with an ADR.

## Definitions

An order is **paid** when `paid_at` is set; its day is `paid_at` in Asia/Tashkent.

| Term            | Rule                                                                                                                                                                                                                                                                                                                 |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Counted order   | paid in the window, `refunded_at IS NULL`                                                                                                                                                                                                                                                                            |
| Заработано      | a counted order with `status = 'delivered'`                                                                                                                                                                                                                                                                          |
| В пути          | a counted order not delivered (`paid`, `buying`, `trade_sent`)                                                                                                                                                                                                                                                       |
| Revenue, сум    | `orders.price_uzs` (the kassa fee is not ours: the buyer pays it to the kassa)                                                                                                                                                                                                                                       |
| Revenue, USD    | `orders.price_usd`                                                                                                                                                                                                                                                                                                   |
| Cost, USD       | what the market charged: Waxpeer `skin_trades.bought_units / 1000`, Skinslink / LIS-SKINS the purchase's `amount_units / 1000`; until the market answers, `orders.cost_usd` (the agreed cost). One function, `spent()` (today in `admin/order_query.py`), moved where both the dashboard and the analytics import it |
| Cost, сум       | cost USD × `fx_snapshots.usd_uzs` of the order, rounded to whole soʻm                                                                                                                                                                                                                                                |
| Profit          | revenue − cost, in soʻm and in USD; margin % = profit / revenue (soʻm)                                                                                                                                                                                                                                               |
| Refund          | an order with `refunded_at` in the window, on that day; count, soʻm, by market and by `failure_reason`                                                                                                                                                                                                               |
| Kassa fees      | Σ `payments.fee_uzs` of succeeded payments in the window, per kassa (top-ups and orders); shown, never subtracted                                                                                                                                                                                                    |
| New buyer       | a user whose first paid order is in the window; **returning**: paid before the window too                                                                                                                                                                                                                            |
| Продано в минус | a delivered counted order with profit (soʻm) < 0                                                                                                                                                                                                                                                                     |
| Buy-back        | the existing sales P&L (`sales/pnl_query.py`): income = what Skinslink credited, cost = the payout (balance, card + bank fee, rejected), CBU rate at the sale, day = `COALESCE(credited_at, to_pay_at)` in Tashkent                                                                                                  |
| Previous period | the same length immediately before `since`                                                                                                                                                                                                                                                                           |
| Channel         | `orders.channel`: `site` or `api` (partner keys); buy-back is always `site`                                                                                                                                                                                                                                          |

## The page — admin «Аналитика»

A menu item; two tabs.

**«Бизнес».** Period: 7 / 30 / 90 days, a calendar month, or a custom range (≤ 366 days);
channel: all / site / API.

- **Tiles**, each with ▲/▼ % against the previous period: оборот (сум); валовая прибыль (сум,
  USD under it); маржа %; заказов; средний чек; выкуп — прибыль; возвраты (count, сум); новых
  покупателей.
- **Chart by day:** revenue and profit; profit split «заработано» / «в пути».
- **Blocks:**
  - **Площадки** — Waxpeer, Skinslink, LIS-SKINS: orders, revenue, profit, margin %.
  - **Каналы** — site / API: the same, API split by key owner.
  - **Оплата** — balance (сум), USD wallet, Click, Payme, Uzum: orders, revenue; the kassa
    fees collected per kassa.
  - **Категории** — `skin_items.category` (knives, gloves, rifles…): orders, revenue, profit.
  - **Топ-10 скинов** by profit (name, orders, revenue, profit).
  - **Покупатели** — new and returning (count and revenue each); top 10 by revenue (avatar,
    name, orders, revenue, profit), linked to the user card.
  - **Выкуп** — sales, credited USD, payouts to the balance and to cards, profit (сум, USD),
    and «к выплате».
  - **Возвраты** — count, сум, by market, by reason.
  - **Продано в минус** — order number (linked), skin, price, cost, profit, market, paid day.

**«Календарь».** A month grid, Monday first, ‹ › month stepper. A day cell: revenue, profit
(сум), and a tint by profit (more profit, brighter; a loss tinted red; a day without orders
dimmed). A click opens «Бизнес» for that day; two clicks select a span; a chip «← вернуться
к месяцу» goes back.

The dashboard stays the «today» summary and links to the page. On a phone every block is one
column; the calendar cells show profit only.

## Backend — module `analytics`

Reads other modules' tables through their `api.py`; owns no table and no write.

| Endpoint                                               | Answer                                                                                                                                           |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /admin/analytics/business?since=&until=&channel=` | tiles (this period and the previous), by-day series, every block above. `since`/`until` are Tashkent dates, `until` inclusive; 422 past 366 days |
| `GET /admin/analytics/calendar?month=YYYY-MM&channel=` | per day of the month: revenue, profit, earned, in flight, orders, buy-back profit                                                                |
| `GET /admin/analytics/losses?since=&until=&channel=`   | «Продано в минус» rows                                                                                                                           |

- One query per block, grouped in SQL (`func.timezone('Asia/Tashkent', paid_at)::date`), the
  cost expression and the rate join shared by all of them — a page is a handful of statements
  whatever the period.
- **Buy-back:** `sales_pnl` takes a `(since, until)` window instead of `days` (the dashboard
  keeps calling it with its window); the analytics imports it from `sales.api`.
- **Cache:** Redis, keyed by endpoint + window + channel; 2 minutes, 1 hour for a window that
  ended more than 8 days ago (past Steam's protection, nothing in it moves any more). Listed
  in `docs/architecture/cache-keys.md`.
- **Index:** `orders(paid_at)` and `orders(refunded_at)` exist; the migration adds one on
  `sales.credited_at`.
- **Dashboard:** its margin moves to the same cost (`spent()` — the market's actual charge
  for Skinslink and LIS-SKINS too, not the checkout cost), so the dashboard and the analytics
  agree.

## Admin SPA

`features/analytics/`: `AnalyticsPage` (tabs, period, channel), `BusinessTab`,
`CalendarTab`, blocks as small components, `charts/` (a by-day line/area chart and a
horizontal bar), colours from the design tokens. Numbers through the existing `formatSum` /
USD formatters. Users in the top list through `UserCell`, skins through `SkinThumb`.

## Testing

Integration (testcontainers), one fixture world with known numbers:

- delivered vs in flight vs refunded; a refund on a later day lands in that day's «Возвраты»
  and leaves the paid day's profit;
- cost: Waxpeer `bought_units`, Skinslink and LIS-SKINS `amount_units`, the agreed cost before
  the market answers; soʻm at the order's own CBU rate, not today's;
- Tashkent day boundaries (23:59 / 00:01);
- new vs returning buyers across the window edge;
- previous-period comparison; the channel filter; the 366-day limit; admin only;
- «Продано в минус» lists only delivered negatives;
- the dashboard's margin now equals the analytics' for the same window.

Admin: Vitest for each tab and block, the calendar click-through, empty states.

## Docs

This spec, an ADR for recharts, `modules/analytics/README.md`, `docs/architecture/module-map.md`,
`cache-keys.md`, `make gen-api`.

## Out of scope

Business expenses and net profit (second stage). Exports (CSV). Per-admin dashboards.
Forecasts.
