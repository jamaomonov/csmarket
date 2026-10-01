# Module map

Backend modules live in `apps/api/src/csmarket/modules/<name>/` (`core` sits beside them at
`apps/api/src/csmarket/core/`). Each module owns its tables; other modules call its `api.py`,
never its models. Sources are YuPay paths under `apps/api/src/yupay/` (read-only, ported by
allow-list — ADR-0002). Tables and columns are spec §5; scope per module is spec §3.2.

| Module          | Tables                                                           | Arrives in                                                         | Ported from                                                                                                                                                                                                                                                       |
| --------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core`          | `idempotent_responses`                                           | M0                                                                 | `core/` — config, logging, clock, ids, observability, errors, cache_headers, client_ip, metrics, money, db, redis, idempotency, events, crypto, health. Not `outbound*`, not `outbox`                                                                             |
| `auth`          | `refresh_tokens`                                                 | M1 (built)                                                         | `modules/auth/` — `steam.py`, `jwt.py`, `cookies.py`, `deps.py`, `security.py`, `ip_guard.py`, `service.py`. Not Google, Telegram, passwords. Dev login is csmarket's own (ADR-0004)                                                                              |
| `users`         | `users`                                                          | M1 (built)                                                         | `modules/users/` — `steam_id` is the identity; trade link lives here                                                                                                                                                                                              |
| `admin`         | `admin_audit_log` (M2, built)                                    | M1 (gate), M2 (audit log), M3 (users, payments, audit read; built) | `modules/admin/` (deps) + the skins admin routes; M1 ships the role gate and `GET /admin/me`, M2 the audit log with the catalogue actions (hide an item, search aliases), M3 the users API (list, card, ban/unban, balance adjustment), pages with each milestone |
| `skins`         | `skin_items`, `skin_pricing_rules`, `skin_search_aliases`        | M1 (Waxpeer client), M2 (catalogue, built); buying M4              | `modules/skins/` + the Waxpeer client (M1: `check_tradelink` only), listings, trades and sweeps from `modules/fulfillment/` + scheduler jobs `skins_*.py`                                                                                                         |
| `fx`            | `fx_snapshots`                                                   | M2 (built)                                                         | new, small (not a port) — CBU rate, `fx_snapshots`, Redis copy `fx:usd_uzs`; hourly scheduler job `fx.refresh`; M4 orders point at a snapshot                                                                                                                     |
| `wallet`        | `wallet_accounts`, `wallet_transactions`, `wallet_postings` (R1) | M3 (built)                                                         | `modules/wallet/` — double-entry ledger, `NORMAL_SIDE` per kind, `post()` invariant, `credit_topup` / `reverse_topup`; UZS only, whole soʻm                                                                                                                       |
| `payments`      | `payments`, `wallet_topups`                                      | M3 (built)                                                         | `modules/payments/` — top-ups (a payable), attempts, FSM, payable resolver, provider hooks, gateways (base, click, payme, uzum, mock). Not paynet, octo; the balance gateway arrives with orders (M4)                                                             |
| `click`         | `click_transactions`                                             | M3 (built)                                                         | `modules/click/` — Click Shop API (prepare / complete, MD5 sign), 30-min timeout sweep; money through `payments` hooks                                                                                                                                            |
| `payme`         | `payme_transactions`                                             | M3 (built)                                                         | `modules/payme/` — Payme Merchant API (JSON-RPC, seven methods), 12-h timeout sweep; money through `payments` hooks                                                                                                                                               |
| `uzum`          | `uzum_transactions`                                              | M3 (built)                                                         | `modules/uzum/` — Uzum Merchant API (check / create / confirm / reverse / status), its state machine, 30-min timeout sweep; money through `payments` hooks                                                                                                        |
| `orders`        | `orders` (the queue), `skin_trades`                              | M4a (built: tables, FSM, checkout, reads)                          | **new, thin** — one skin, one offer; statuses (`orders.fsm`), money, the Waxpeer purchase and trade (`skin_trades`, YuPay's load-bearing columns, R2)                                                                                                             |
| `realtime`      | —                                                                | M4                                                                 | `modules/realtime/` — WebSocket order status                                                                                                                                                                                                                      |
| `notifications` | —                                                                | M4                                                                 | `modules/notifications/` — email only (receipt, trade sent, refunded)                                                                                                                                                                                             |
| `sell`          | —                                                                | after MVP                                                          | not ported — skinslink sell side; the MVP only reserves the slot and the `sell_payout` ledger kind                                                                                                                                                                |

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
  has a timeout sweep in the scheduler. Lock order everywhere: top-up → kassa row → payment →
  user wallet.
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
  `GET /me/orders`) carry the buyer's trade view. Payment, buying, trades and refunds land
  in the following M4a tasks.

## Processes outside the API

| App              | Package              | Arrives in | Notes                                                                                                                                                                                                                                                                       |
| ---------------- | -------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/worker`    | `csmarket_worker`    | M0 (shell) | `consumer._queues()` is empty until M4 adds the `orders` queue                                                                                                                                                                                                              |
| `apps/scheduler` | `csmarket_scheduler` | M0 (shell) | Jobs: `purge_stale_refresh_tokens` (M1, daily); `fx.refresh` (M2, hourly); `skins.catalog_import` (M2, daily), `skins.price_sync` (M2, every 5 min); `wallet.topup_expiry`, `click.timeout`, `payme.timeout`, `uzum.timeout` (M3, every 5 min); expire, trades, audits (M4) |
| `apps/web`       | `@csmarket/web`      | M0 (hello) | Catalogue, item pages, landings, sitemaps (M2); account M1; balance and top-ups M3 (built); orders M4                                                                                                                                                                       |
| `apps/admin`     | `@csmarket/admin`    | M0 (shell) | Steam sign-in and role gate (M1); catalogue page (M2); users, balance adjustment, payments, audit log M3 (built); trades, pricing M4                                                                                                                                        |
