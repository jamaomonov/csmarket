# Module map

Backend modules live in `apps/api/src/csmarket/modules/<name>/` (`core` sits beside them at
`apps/api/src/csmarket/core/`). Each module owns its tables; other modules call its `api.py`,
never its models. Sources are YuPay paths under `apps/api/src/yupay/` (read-only, ported by
allow-list — ADR-0002). Tables and columns are spec §5; scope per module is spec §3.2.

| Module          | Tables                                                    | Arrives in                   | Ported from                                                                                                                                                                           |
| --------------- | --------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core`          | `idempotent_responses`                                    | M0                           | `core/` — config, logging, clock, ids, observability, errors, cache_headers, client_ip, metrics, money, db, redis, idempotency, events, crypto, health. Not `outbound*`, not `outbox` |
| `auth`          | `refresh_tokens`                                          | M1 (built)                   | `modules/auth/` — `steam.py`, `jwt.py`, `cookies.py`, `deps.py`, `security.py`, `ip_guard.py`, `service.py`. Not Google, Telegram, passwords. Dev login is csmarket's own (ADR-0004)  |
| `users`         | `users`                                                   | M1 (built)                   | `modules/users/` — `steam_id` is the identity; trade link lives here                                                                                                                  |
| `admin`         | `admin_audit_log` (with the first admin action, M3)       | M1 (gate) →                  | `modules/admin/` (deps) + the skins admin routes; M1 ships the role gate and `GET /admin/me`, the audit log comes with the first admin action, pages with each milestone              |
| `skins`         | `skin_items`, `skin_pricing_rules`, `skin_search_aliases` | M1 (Waxpeer client only), M2 | `modules/skins/` + the Waxpeer client (M1: `check_tradelink` only), listings, trades and sweeps from `modules/fulfillment/` + scheduler jobs `skins_*.py`                             |
| `fx`            | `fx_snapshots`                                            | M3                           | `modules/fx/` — CBU rate, a snapshot per order                                                                                                                                        |
| `wallet`        | `wallet_accounts`, `ledger_entries`, `wallet_topups`      | M3                           | `modules/wallet/` — double-entry ledger, `NORMAL_SIDE` per kind, `post()` invariant                                                                                                   |
| `payments`      | `payments`                                                | M3                           | `modules/payments/` — FSM, idempotency, gateways (base, click, payme, uzum, wallet, mock). Not paynet, octo                                                                           |
| `click`         | `click_webhooks`                                          | M3                           | `modules/click/` — webhook twin                                                                                                                                                       |
| `payme`         | `payme_transactions`                                      | M3                           | `modules/payme/` — webhook twin                                                                                                                                                       |
| `uzum`          | `uzum_transactions`                                       | M3                           | `modules/uzum/` — webhook twin                                                                                                                                                        |
| `orders`        | `orders` (the queue), `skin_trades`                       | M4                           | **new, thin** — one skin, one offer; statuses, money, trade                                                                                                                           |
| `realtime`      | —                                                         | M4                           | `modules/realtime/` — WebSocket order status                                                                                                                                          |
| `notifications` | —                                                         | M4                           | `modules/notifications/` — email only (receipt, trade sent, refunded)                                                                                                                 |
| `sell`          | —                                                         | after MVP                    | not ported — skinslink sell side; the MVP only reserves the slot and the `sell_payout` ledger kind                                                                                    |

`skin_trades` is keyed by `order_id`; whether `orders` or `skins` owns the model is settled by
the M4 plan.

Not ported from YuPay, by design: `catalog`, `gifts`, `blog`, `merchants`, `integrations`,
`sourcing`, `inventory`, `promo`, `promotions`, `affiliate`, `reviews`, `broadcasts`, `stats`,
`delivery`, `evidence`, `storage`, `paynet`, `pricing` (skins has its own).

## Built in M1

`auth`, `users` and the gate of `admin` are built; `skins` has the Waxpeer client only
(`check_tradelink`), the catalogue arrives in M2. Their routers are collected in
`apps/api/src/csmarket/api/v1/router.py` from each module's `routes.py` — not from a package
`__init__` (import cycle; `tests/unit/test_import_order.py`). Flows:
[`sequence-diagrams/steam-sign-in.mmd`](./sequence-diagrams/steam-sign-in.mmd),
[`sequence-diagrams/trade-link-check.mmd`](./sequence-diagrams/trade-link-check.mmd). Redis
keys: [`cache-keys.md`](./cache-keys.md). Decision: [ADR-0004](../decisions/0004-steam-auth-and-sessions.md).

## Processes outside the API

| App              | Package              | Arrives in | Notes                                                                                                          |
| ---------------- | -------------------- | ---------- | -------------------------------------------------------------------------------------------------------------- |
| `apps/worker`    | `csmarket_worker`    | M0 (shell) | `consumer._queues()` is empty until M4 adds the `orders` queue                                                 |
| `apps/scheduler` | `csmarket_scheduler` | M0 (shell) | Jobs: `purge_stale_refresh_tokens` (M1, daily); catalogue import, price sync (M2); expire, trades, audits (M4) |
| `apps/web`       | `@csmarket/web`      | M0 (hello) | Catalogue M2, account M1, wallet M3, orders M4                                                                 |
| `apps/admin`     | `@csmarket/admin`    | M0 (shell) | Steam sign-in and role gate (M1); catalogue M2; users, wallet, payments M3; trades, pricing M4                 |
