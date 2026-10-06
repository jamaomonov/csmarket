# Module map

Backend modules live in `apps/api/src/csmarket/modules/<name>/` (`core` sits beside them at
`apps/api/src/csmarket/core/`). Each module owns its tables; other modules call its `api.py`,
never its models. Sources are YuPay paths under `apps/api/src/yupay/` (read-only, ported by
allow-list — ADR-0002). Tables and columns are spec §5; scope per module is spec §3.2.

| Module          | Tables                                                                          | Arrives in                                                                                                     | Ported from                                                                                                                                                                                                                                                                                                                                                    |
| --------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core`          | `idempotent_responses`                                                          | M0                                                                                                             | `core/` — config, logging, clock, ids, observability, errors, cache_headers, client_ip, metrics, money, db, redis, idempotency, events, crypto, health. Not `outbound*`, not `outbox`                                                                                                                                                                          |
| `auth`          | `refresh_tokens`                                                                | M1 (built)                                                                                                     | `modules/auth/` — `steam.py`, `jwt.py`, `cookies.py`, `deps.py`, `security.py`, `ip_guard.py`, `service.py`. Not Google, Telegram, passwords. Dev login is csmarket's own (ADR-0004)                                                                                                                                                                           |
| `users`         | `users`                                                                         | M1 (built)                                                                                                     | `modules/users/` — `steam_id` is the identity; trade link lives here                                                                                                                                                                                                                                                                                           |
| `admin`         | `admin_audit_log` (M2, built)                                                   | M1 (gate), M2 (audit log), M3 (users, payments, audit read), M4a (orders, trades; built)                       | `modules/admin/` (deps) + the skins admin routes; M1 ships the role gate and `GET /admin/me`, M2 the audit log with the catalogue actions (hide an item, search aliases), M3 the users API (list, card, ban/unban, balance adjustment), M4a the orders and trades API (search, order page, attention queue; resolve, refund, retry), pages with each milestone |
| `skins`         | `skin_items`, `skin_pricing_rules`, `skin_search_aliases`                       | M1 (Waxpeer client), M2 (catalogue), M4a (purchase client, dev fake; built), ADR-0010 (offers of both sources) | `modules/skins/` + the Waxpeer client (M1: `check_tradelink` only), listings, trades and sweeps from `modules/fulfillment/` + scheduler jobs `skins_*.py`; since ADR-0010 `/{slug}/listings` and checkout merge Waxpeer's live listings with Skinslink's mirror (`skins.offers`: `wx:` / `sl:` offer ids), and the price sync prices from the cheaper source   |
| `fx`            | `fx_snapshots`                                                                  | M2 (built)                                                                                                     | new, small (not a port) — CBU rate, `fx_snapshots`, Redis copy `fx:usd_uzs`; hourly scheduler job `fx.refresh`; M4a orders point at a snapshot                                                                                                                                                                                                                 |
| `wallet`        | `wallet_accounts`, `wallet_transactions`, `wallet_postings` (R1)                | M3 (built)                                                                                                     | `modules/wallet/` — double-entry ledger, `NORMAL_SIDE` per kind, `post()` invariant, `credit_topup` / `reverse_topup`; UZS only, whole soʻm                                                                                                                                                                                                                    |
| `payments`      | `payments`, `wallet_topups`                                                     | M3 (built)                                                                                                     | `modules/payments/` — top-ups (a payable), attempts, FSM, payable resolver, provider hooks, gateways (base, click, payme, uzum, mock). Not paynet, octo; paying from the balance (`provider="wallet"`) lives in `orders.paying` (M4a)                                                                                                                          |
| `click`         | `click_transactions`                                                            | M3 (built)                                                                                                     | `modules/click/` — Click Shop API (prepare / complete, MD5 sign), 30-min timeout sweep; money through `payments` hooks                                                                                                                                                                                                                                         |
| `payme`         | `payme_transactions`                                                            | M3 (built)                                                                                                     | `modules/payme/` — Payme Merchant API (JSON-RPC, seven methods), 12-h timeout sweep; money through `payments` hooks                                                                                                                                                                                                                                            |
| `uzum`          | `uzum_transactions`                                                             | M3 (built)                                                                                                     | `modules/uzum/` — Uzum Merchant API (check / create / confirm / reverse / status), its state machine, 30-min timeout sweep; money through `payments` hooks                                                                                                                                                                                                     |
| `orders`        | `orders` (the queue), `skin_trades`                                             | M4a (built: tables, FSM, checkout, reads, pay, refunds, buying, sweeps)                                        | **new, thin** — one skin, one offer; statuses (`orders.fsm`), money, the Waxpeer purchase and trade (`skin_trades`, YuPay's load-bearing columns, R2); since ADR-0010 a second source: `orders.source` routes the buy to Waxpeer or Skinslink (`orders/skinslink_*.py`, the purchase in `skinslink_purchases`)                                                 |
| `realtime`      | —                                                                               | M4b (built)                                                                                                    | `modules/realtime/` — order nudges over `WS /api/v1/realtime/orders` (first-message auth); one Postgres `LISTEN order_events` connection per API process fans `pg_notify` from `orders` out to the owner's sockets (ADR-0008)                                                                                                                                  |
| `notifications` | `email_outbox`                                                                  | M4b (built)                                                                                                    | `modules/notifications/` — email only (receipt, trade sent, refunded, verify): an outbox written in the event's transaction, drained by the worker's `emails` queue; Resend in prod, Redis dev transport locally (ADR-0008)                                                                                                                                    |
| `skinslink`     | `skinslink_items`, `skinslink_state`, `skinslink_purchases`, `skinslink_checks` | ADR-0010 (branch `skinslink-buy`; built, not deployed)                                                         | **new** (not a port) — the second buy source: client, a mirror of its CS2 stock (scheduler `skinslink.mirror`), the roll-up onto `skin_items`, offers from the mirror, the signed status webhook (enqueues a check only), the balance read. The buy and status flow that move orders live in `orders`                                                          |
| `sell`          | —                                                                               | after MVP                                                                                                      | not ported — skinslink sell side; the MVP only reserves the slot and the `sell_payout` ledger kind                                                                                                                                                                                                                                                             |

`skin_trades` is keyed by `order_id` and owned by `orders` (M4a plan); `payments.order_id`
points at `orders` (migration `0013_orders_skin_trades`).

Not ported from YuPay, by design: `catalog`, `gifts`, `blog`, `merchants`, `integrations`,
`sourcing`, `inventory`, `promo`, `promotions`, `affiliate`, `reviews`, `broadcasts`, `stats`,
`delivery`, `evidence`, `storage`, `paynet`, `pricing` (skins has its own).

## Built in M1

`auth`, `users` and the gate of `admin`; `skins` had the Waxpeer client only
(`check_tradelink`). Their routers are collected in
`apps/api/src/csmarket/api/v1/router.py` from each module's `routes.py` — not from a package
`__init__` (import cycle; `tests/unit/test_import_order.py`). Flows:
[`sequence-diagrams/steam-sign-in.mmd`](./sequence-diagrams/steam-sign-in.mmd),
[`sequence-diagrams/trade-link-check.mmd`](./sequence-diagrams/trade-link-check.mmd). Redis
keys: [`cache-keys.md`](./cache-keys.md). Decision: [ADR-0004](../decisions/0004-steam-auth-and-sessions.md).

## Built in M2

- **`skins`** — the catalogue: `skin_items`, `skin_pricing_rules`, `skin_search_aliases`; the
  ByMykel import, the Waxpeer price sync with stored sell prices, the public read API
  (`/skins/catalog`, `/facets`, `/suggest`, `/{slug}`, `/{slug}/listings`, `/seo/slugs`) and the
  admin catalogue routes. Buying (`orders`, trades) is M4. It reaches `fx` only through
  `fx.api` and never imports another module's models.
- **`fx`** — the USD/UZS rate only (`fx_snapshots`, CBU fetch, Redis copy, hourly job).
  Order-time snapshots are M4.
- **`admin`** — the role gate plus `admin_audit_log`, written by `admin.api.record()`; no
  audit UI yet. M3 adds the users API (`admin.users_routes`: list, card, ban/unban, audited
  balance adjustment), the payments API (`admin.payments_routes`: search, detail with the
  Click / Payme / Uzum transactions) and the audit-log read (`admin.audit_routes`); `admin`
  imports `users`, `wallet`, `payments`, `click`, `payme`, `uzum`, `auth`, never the reverse.

Flows: [`sequence-diagrams/skins-price-sync.mmd`](./sequence-diagrams/skins-price-sync.mmd),
[`../product/flows/skins-browse.md`](../product/flows/skins-browse.md). Runbook:
[`../runbooks/skins-catalogue.md`](../runbooks/skins-catalogue.md). Decision:
[ADR-0005](../decisions/0005-skins-catalogue-fx-and-indexing.md).

## Built in M3

- **`wallet`** — the double-entry ledger (`wallet_accounts`, `wallet_transactions`,
  `wallet_postings`); `post()` is the only writer; customer balance and history routes; the
  audited admin adjustment (never below zero).
- **`payments`** — top-ups (`wallet_topups`, numbers `T…`) and their attempts (`payments`),
  the FSM, the payable resolver, the provider hooks (`settle`, `reverse`, `cancel_pending`)
  and the gateways (`click`, `payme`, `uzum`, dev-only `mock`). It imports `wallet`, never the
  reverse.
- **`click`**, **`payme`**, **`uzum`** — each kassa's callback server and its transaction
  table; every money move goes through the `payments` hooks, never `wallet` directly. Each
  has a timeout sweep in the scheduler. Lock order everywhere: top-up (or, from M4a, order)
  → kassa row → payment → user wallet.
- **`admin`** — aggregates the users API (list, card, ban/unban, balance adjustment), the
  payments API (search, detail with each kassa's transactions) and the audit-log read. It
  imports `users`, `wallet`, `payments`, `click`, `payme`, `uzum` and `auth` through their
  `api.py`; none of them imports `admin`.

Flow: [`sequence-diagrams/topup.mmd`](./sequence-diagrams/topup.mmd),
[`../product/flows/balance-topup.md`](../product/flows/balance-topup.md). Runbooks:
[`kassa-setup`](../runbooks/kassa-setup.md), [`click`](../runbooks/click.md),
[`payme`](../runbooks/payme.md), [`uzum`](../runbooks/uzum.md),
[`wallet`](../runbooks/wallet.md). Metric: [`metrics.md`](./metrics.md). Decision:
[ADR-0006](../decisions/0006-wallet-payments-topups.md).

## Built in M4a

- **`orders`** — `orders` (the customer's purchase and the worker's queue) and `skin_trades`
  (the Waxpeer purchase and Steam trade behind one order); the order FSM in `orders.fsm` is
  the only place an order's status changes. `orders` may import `payments`, `wallet`,
  `skins`, `users` and `fx`; `payments` reaches `orders` only through `orders.api` (its
  models module imports `orders.models` once, to register the `payments.order_id` target);
  `wallet` imports neither. The ledger gains the `purchase` and `refund` kinds. Checkout
  (`POST /orders`) re-prices through `skins`' listings read (`skins.api.search_client`,
  `listings_for`) and the rate through `fx.api`; the order reads (`GET /orders/{number}`,
  `GET /me/orders`) carry the buyer's trade view. Paying (`POST /orders/{number}/pay`,
  `orders.paying`) books the balance through `wallet.api.debit_purchase` (R8) or opens a
  kassa attempt through `payments.api`; `orders.api` never exports `paying` (it imports
  `payments`). Refunds (`orders.refunds`, exported by `orders.api`) book through
  `wallet.api.credit_order_refund` and never import `payments`; `wallet`'s entries read the
  order number through a bare `table("orders")`. Buying (`orders.buying`, the worker's
  `orders` queue) reads `skins.api` (the purchase client `trade_client`, `listings_for` for
  a substitute) and `users.api.parse_tradelink`, and refunds through `orders.refunds`.
  The trade sweeps (`orders.sweeps`: reconcile, unpaid-order expiry, protection watch,
  history audit) are timed by the scheduler; the expiry imports `payments.api.cancel_pending`
  inside the function (the import-time direction stays payments → orders).
- **`payments` learns orders** — the payable resolver reads a non-`T` number as an order;
  the hooks pay an attempt's _owner_ (top-up or order): `settle` on an order calls
  `orders.api.mark_paid` (`paid`, `NOTIFY orders`), `reverse` on an order raises
  `OrderReversalRefusedError` (a `ReversalRefusedError`, like `TopupSpentError`: Payme
  −31007, Uzum 10017 — ruling R7). The kassas' timeout sweeps cover order attempts and lock
  the owner first, `SKIP LOCKED`, per row. Lock order for orders: order → kassa row →
  payment → wallet. The admin payment detail carries an `order` block.
- **`admin` learns orders** — `admin.orders_routes` (`/admin/orders`, `/admin/trades`):
  search, the order page (trade link masked), the trades page with its attention queue, and
  three audited, idempotent actions — resolve, refund to the balance, retry the buy. The
  writes are `orders`' own (`orders.admin_actions`, exported by `orders.api`: lock order →
  trade, refused while a buy attempt holds the lease); `admin` reads `orders.api`,
  `payments.api` and `fx.api`, and `orders` never imports `admin`. The admin user card lists
  the user's latest 20 orders.
- **Processes** — the worker's `orders` queue buys paid orders; the scheduler runs the trade
  sweeps and the `orders.health` gauges; both expose `/metrics` (ports 9101 / 9102, not
  published) for Prometheus (`infra/prometheus/alerts/orders.yml`).

Flows: [`sequence-diagrams/checkout.mmd`](./sequence-diagrams/checkout.mmd),
[`sequence-diagrams/buy.mmd`](./sequence-diagrams/buy.mmd),
[`sequence-diagrams/trade-reconcile.mmd`](./sequence-diagrams/trade-reconcile.mmd),
[`../product/flows/buy.md`](../product/flows/buy.md). Runbooks:
[`orders`](../runbooks/orders.md), [`waxpeer`](../runbooks/waxpeer.md). Metrics:
[`metrics.md`](./metrics.md). Decision: [ADR-0007](../decisions/0007-orders-buying-trades.md).
**M4b:** `realtime` (WebSocket order pushes), `notifications` (email, Resend), the pricing
editor and the dashboard.

## Skinslink as a buy source (ADR-0010)

- **`skinslink`** — owns the mirror (`skinslink_items`, `skinslink_state`), the purchase
  records (`skinslink_purchases`) and the check queue (`skinslink_checks`); migration
  `0018_skinslink`. Imports `skins.api` (the catalogue item, `Offer`, `canonical_name`) and
  `orders.models.ATTENTION_REASONS`; everyone else imports `skinslink.api`. It never moves an
  order.
- **`skins`** — the price sync calls `skinslink.api.rollup` (cost = the cheaper source, count =
  the sum); `/{slug}/listings` merges `skinslink.api.offers_for` with Waxpeer's listings
  (`skins.offers`). No new external call on a request: Skinslink offers come from the mirror.
- **`orders`** — `orders.source` (`waxpeer` | `skinslink`) and `offer_id`; checkout merges both
  sources; `drain_paid` routes by source; `orders/skinslink_buying.py`, `skinslink_writes.py`,
  `skinslink_status.py` and `skinslink_reconcile.py` buy, apply statuses and reconcile through
  `skinslink.api`. The renamed codes `source_low_balance` / `source_forbidden` cover both.
- **`admin`** — the order page shows the source and the Skinslink purchase; the dashboard shows
  the Skinslink balance (`orders.dashboard` reads
  `skinslink.api.skinslink_cached_balance`). The attention queue and the
  actions stay Waxpeer-only for now (`docs/tech-debt.md`).
- **Processes** — the worker's `skinslink` queue (`orders.api.drain_checks`); the scheduler's
  `skinslink.mirror` (15 s), `skinslink.reconcile` (30 s), `skinslink.balance` (5 min).

Flow: [`sequence-diagrams/skinslink-buy.mmd`](./sequence-diagrams/skinslink-buy.mmd). Runbook:
[`skinslink`](../runbooks/skinslink.md). Decision:
[ADR-0010](../decisions/0010-skinslink-buy-source.md).

## Processes outside the API

| App              | Package              | Arrives in | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------- | -------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/worker`    | `csmarket_worker`    | M0 (shell) | `consumer._queues()`: `orders` (M4a, two drainers) — `orders.api.drain_paid` claims paid orders and buys them at Waxpeer (`docs/architecture/sequence-diagrams/buy.mmd`); `emails` (M4b, one drainer) — `notifications.api.drain_emails` sends due outbox letters; `skinslink` (ADR-0010, one drainer) — `orders.api.drain_checks` asks Skinslink about the purchases its webhook named                                                                                                                                                                                                                            |
| `apps/scheduler` | `csmarket_scheduler` | M0 (shell) | Jobs: `purge_stale_refresh_tokens` (M1, daily); `fx.refresh` (M2, hourly); `skins.catalog_import` (M2, daily), `skins.price_sync` (M2, every 5 min); `wallet.topup_expiry`, `click.timeout`, `payme.timeout`, `uzum.timeout` (M3, every 5 min); `orders.expiry` (M4a, every 60 s), `trades.reconcile` (M4a, every 10 s), `trades.protection` (M4a, hourly), `trades.audit` (M4a, daily 23:30 UTC), `orders.health` (M4a, every 60 s; gauges); `orders.erase_trade_links` (M4b, daily 22:00 UTC); `skinslink.mirror` (every 15 s), `skinslink.reconcile` (every 30 s), `skinslink.balance` (every 5 min) — ADR-0010 |
| `apps/web`       | `@csmarket/web`      | M0 (hello) | Catalogue, item pages, landings, sitemaps (M2); account M1; balance and top-ups M3; buy panel, order page, «Мои заказы» M4a (built); WS order pushes M4b                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `apps/admin`     | `@csmarket/admin`    | M0 (shell) | Steam sign-in and role gate (M1); catalogue page (M2); users, balance adjustment, payments, audit log M3; orders, trades M4a (built); pricing, dashboard M4b                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
