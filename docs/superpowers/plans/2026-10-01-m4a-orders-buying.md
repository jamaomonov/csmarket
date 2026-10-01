# M4a — Orders: Checkout, Payment, Buying at Waxpeer, Trades and Refunds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in buyer with a working trade link picks an offer on an item page, pays from the
balance or through Click / Payme / Uzum, and receives the skin as a Steam trade offer bought at
Waxpeer; a declined or failed trade puts the money back on the balance; the order page shows every
step; an admin sees every order and trade, resolves what needs attention and refunds what is safe to
refund.

**Architecture:** A new thin `orders` module owns the `orders` table (it is also the queue, ADR-0064
shape: `paid` rows are claimable, the transaction that writes `paid` sends `NOTIFY orders`) and
`skin_trades`. The Waxpeer purchase calls (`buy-one-p2p`, `check-many-project-id`, `user`) join the
M2 client in `skins`. `payments` learns the order branch of its payable resolver and hooks; a
`wallet` provider pays from the balance in one transaction. The worker drains `paid → buying` and
buys; scheduler sweeps reconcile trades, expire unpaid orders, watch delivered trades and audit
history. Storefront gets the buy panel and the order page (polling — the WebSocket arrives in M4b);
admin gets Orders and Trades.

**Tech Stack:** FastAPI · SQLAlchemy 2 async · Alembic · Postgres 16 (`FOR UPDATE SKIP LOCKED` +
`LISTEN/NOTIFY`) · Redis 7 · APScheduler · httpx · prometheus_client · pytest + testcontainers +
respx + hypothesis · Next.js 15 + next-intl · Vite + React 19 + TanStack Query · Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md` — §2 (decisions 3, 11 and the
inherited Waxpeer decisions), §3.2 (`orders`, `skins`, `payments`, `wallet`), §5 (`orders`,
`skin_trades`, `payments`, ledger kinds `purchase`, `refund`), §6, §7.2 (trade-hold = `bad`, owner
2026-10-01), §7.4–§7.8, §8, §9, §10 (`/item` buy panel, `/account/orders`, `/orders/[number]`,
admin Orders / Trades), §12 (alerts), §13, §14, §15 row M4. Rulebook: `AGENTS.md` (§4–§12, §14).

**Source material (read-only):** `/Users/macbook_uz/Projects/yupay` — never write there. Backend
modules under `yupay:apps/api/src/yupay/modules/` are written `ym:<module>/<file>`; tests under
`yupay:apps/api/tests/`. Python files go through the rename filter from the repo root:
`sed -f scripts/port-rename.sed <yupay file> > <dst>`, then the task's deltas. YuPay's skins design:
`yupay:docs/decisions/0093-cs2-skins-via-waxpeer.md` (with both 2026-09-29 amendments),
`yupay:docs/runbooks/skins-purchase.md`, `yupay:docs/product/flows/skins-buy.md`.
**YuPay test constants:** the `LINK` / `partner` / `token` / `for_steamid64` values in YuPay's skins
tests and `tests/contract/test_waxpeer_client_purchase.py` may be the owner's real ones — never copy
them; use csmarket's fake `https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12`
and invented Steam IDs.

## Global Constraints

- **Owner decisions (2026-10-01, in conversation):** (D1) M4 is split: **M4a** (this plan) is the sale end to end with a polling order page; **M4b** brings the WebSocket, email (Resend), the pricing editor and the dashboard. (D2) A trade link with a Steam trade hold is **refused** (verdict `bad`), as in YuPay. (D3) Email provider is Resend (M4b). (D4) The owner can give a Waxpeer key whitelisted for their local IP — it goes into the owner's local `.env` by the owner, **never into chat, the repo or a file an agent writes**.
- **Money:** `Decimal`; soʻm whole units `numeric(14,0)`; USD `numeric(12,6)`; Waxpeer units are integers, **1000 = $1**; never floats. (spec §5, AGENTS §10)
- **Ledger:** every balance change is one `wallet.post()` with ≥ 2 balanced legs; a purchase is booked once per order (key `purchase:order:{order_id}`), a refund once per order (key `refund:order:{order_id}`); the balance is never driven below zero by our code.
- **One skin per order. An order is bought at most once at Waxpeer:** `project_id = order.id`; every buy is preceded by a `check-many-project-id` lookup; a lost or ambiguous answer is resolved by lookup, **never by buying again**.
- **Refunds go to the balance only** (spec §7.8). An order whose outcome is unknown (lost buy answer, ambiguous lookup) or whose skin may have been delivered is **never refunded automatically**.
- **No lock held across a Waxpeer call:** read unlocked → call Waxpeer → `FOR UPDATE` re-read → re-check → write. Lock order for orders: **order row → kassa transaction row → payment → user wallet** (the M3 top-up order with the order in the top-up's place).
- **Idempotency:** `POST /orders` and `POST /orders/{number}/pay` require `Idempotency-Key` (16–160 chars) and persist by it; a replayed order key returns the stored order whatever the body says; admin writes as in M3 (`Idempotency-Key`, audit, replay row). (AGENTS §10)
- **Rate limits:** `ip_guard` bucket `order-create` (60/min per IP, 10/min per IP + account) on `POST /orders`; `order-pay` (same ceilings) on `POST /orders/{number}/pay`. (AGENTS §10)
- **Never log PII or secrets:** Steam ID, email, IP, the trade link and its `partner`/`token`, Waxpeer's `for_steamid64`, the Waxpeer key and any URL that carries it (the key and the trade link travel as query parameters — never log a Waxpeer URL or body). Money log lines carry the order number, amounts and outcome codes, never a user id. (AGENTS §10)
- **Copy (owner):** short sentences; outcome, not mechanism; no Waxpeer / seller-marketplace / refund internals for customers («Waxpeer» never appears in customer copy or anything a browser receives); «вы»; ru / uz / en, every key in all three; UZ uses ʻ (U+02BB) after o/g and ʼ (U+02BC) elsewhere; admin copy is Russian; skin names stay English. (AGENTS §12)
- **Forbidden tokens** in `apps/*/src`, `packages/*/src`: `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`, `merchant_api`, `voucher`, `game_id` — YuPay's `supplier_low_balance` becomes `waxpeer_low_balance`; "fulfil…" identifiers become "buy…"/"trade…". (AGENTS §6)
- **Routers mount in `apps/api/src/csmarket/api/v1/router.py`**; `tests/unit/test_import_order.py` lists every new module; `orders` may import `payments`, `wallet`, `skins`, `users`, `fx`; `payments` reaches orders only through `csmarket.modules.orders.api` (lazy import inside functions where a cycle would form); `wallet` imports neither. Every route change regenerates `docs/api/openapi.json` + the client (`make gen-api`) in the same commit.
- **Scheduler jobs** only time work; `first_run_after(n)` staggered ≥ 15 s from the existing 20, 60, 120, 140, 160, 180, 200, 300 s. M4a takes 220 (expiry), 240 (reconcile), 260 (stuck/health gauges), 280 (protection watch), 320 (history audit).
- **Coverage:** `orders`, `payments`, `wallet`, `skins` ≥ 95 % each (AGENTS §9); every Waxpeer call path has success, retryable failure and idempotent re-call tests.
- **Dev ports** api 8100, web 3100, admin 3102; never touch `yupay*` containers or testcontainers you did not start; kill processes by PID only.
- **Commits:** Conventional Commits, scopes `api/orders`, `api/skins`, `api/payments`, `api/wallet`, `api/users`, `api/admin`, `worker`, `scheduler`, `infra`, `web/item`, `web/orders`, `web/account`, `admin/orders`, `e2e`, `docs`; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push.

## Rulings taken while planning (owner may veto)

- **R1 — Order FSM** (`orders.fsm`, one place, like `payments.fsm`): `pending → paid | cancelled`; `paid → buying`; `buying → trade_sent | delivered | failed | returned`; `trade_sent → delivered | returned`. `delivered`, `cancelled`, `failed`, `returned` are terminal. `buying → delivered/returned` exists because one reconcile tick can see Waxpeer go from 0 to 4-accepted or 6 at once. `failed` and `returned` always come with the refund in the same transaction (spec §5) — except R3's cases, which never reach them automatically.
- **R2 — `skin_trades` carries YuPay's load-bearing columns** beyond spec §5: `listing_id`, `waxpeer_id` (spec's `waxpeer_trade_id`), `paid_units` (the cap we agreed to pay), `bought_units`, `accepted_at`, `seller jsonb`, `buy_pending bool`, `buy_unconfirmed_at`, `attention_reason`, `audit_verdict`, `resolved_by`, `resolved_note`; spec's `seller_name/avatar/level/since` live in `seller` (one jsonb, parsed by `parse_trade`). `escrow_status` is stored as received (YuPay never parsed it). `attention` is derived (`attention_reason IS NOT NULL AND resolved_at IS NULL`), not a stored bool.
- **R3 — Unknown and spent outcomes never auto-refund.** A lost buy answer still unseen after 10 min (`buy_unconfirmed`), an ambiguous lookup (`ambiguous_trade`), or a status 6 after acceptance / with penalties (`rolled_back`) set `skin_trades.attention_reason`; the order keeps its status (`buying` or `delivered`); an alert fires; an admin decides (resolve, then refund if the money is ours). The buyer sees «мы проверяем покупку», never a refund promise.
- **R4 — Substitution (spec §7.4/§7.6 as written, YuPay's ceiling rule):** at checkout, a chosen offer that is gone is replaced by the cheapest `auto` offer of the same item whose price is ≤ the price the buyer was shown × 1.03 ("paid price + 3 %"); the buyer is billed the lower of that offer's price and the shown price — never more than they saw (we absorb up to 3 %); none → 409 `offer_gone` with the next offer. In the worker, a buy refused on price or because the listing sold is retried **once** with the cheapest other `auto` listing under the same ceiling (`skin_trades.paid_units` × 1.03); `new_price` from Waxpeer is never accepted blindly.
- **R5 — Trade reconcile every 10 s, not every 2–3 min** (spec §7.7 cadence): the buyer has 30 min to accept and the order page's «обмен отправлен» rides this sweep; one `check-many-project-id` call covers ≤ 100 orders, so 10 s is ≤ 6 calls/min. Protection watch hourly (spec: daily), history audit daily at 04:30 Tashkent over 14 days using `check-many-project-id` (spec: `my-history`, whose shape was never captured — the orphan-buy probe moves to M4b with the owner's local key).
- **R6 — Waxpeer buy errors are classified, not lumped as "sold out":** `200 success:false` with `new_price` or a gone listing → substitute once (R4) then `failed` + refund (`sold_out`); a refusal that names low balance, **or any refusal while `GET /v1/user` shows a balance below the price**, → `failed` + refund (`waxpeer_low_balance`) + alert (owner's YuPay choice: refund at once, never stall); HTTP 403 (IP not whitelisted) → **no substitute, no refund**, order stays `buying` with `buy_pending`, metric + alert `WaxpeerForbidden` (a config error must not refund the whole shop as "sold out"); 429 → `buy_pending`, retried next tick; network error / 5xx → `buy_unconfirmed_at` (resolve by lookup, R3 after 10 min).
- **R7 — A kassa can never reverse an order payment.** The skin is bought at payment and refunds go to the balance; Payme `CancelTransaction` on a performed order transaction answers −31007, Uzum `/reverse` 10017, Click has no reversal of a completed payment. `payments.hooks.reverse` raises `ReversalRefusedError` (new base class; M3's `TopupSpentError` becomes its subclass, so the kassas catch one type).
- **R8 — Pay from the balance** (`provider="wallet"`): `POST /orders/{number}/pay {provider: "wallet"}` in one transaction locks the order, locks the wallet, books `purchase` (C `user_wallet` / D `house_payments_received`), writes a `payments` row (`provider="wallet"`, `status="succeeded"`), moves the order to `paid` and sends `NOTIFY orders`; a short balance is 409 `balance_too_low` and changes nothing. No mixed payment.
- **R9 — Refund legs:** a balance-paid order refunds D `user_wallet` / C `house_payments_received`; a kassa-paid order refunds D `user_wallet` / C `provider_clearing:<provider>` (the M3 top-up shape: the kassa's money becomes balance). The payment row stays `succeeded` (the money stays with us); `orders.refunded_at`, `refunded_to='balance'` record it.
- **R10 — Trade-link gate at checkout:** `POST /orders` refuses a missing link (409 `trade_link_missing`) and a link whose stored verdict is `bad` (409 `trade_link_bad`, `reason` = `invalid|private|trade_ban|hold`); an unchecked or `unavailable` verdict passes (the check is advisory and the buy panel runs it before submitting). `PUT /me/trade-link` already clears the verdict on a new link.
- **R11 — Checkout re-prices from the cached listings read** (`skins.listings.listings_for`, 90 s fresh / 1 h stale, budgeted, 4 s timeout): a new synchronous Waxpeer read on the money path, recorded as a carve-out in ADR-0007 and AGENTS §11, and added to the `ApiHighLatency` / `ApiWaxpeerLatency` handler regexes. A degraded (snapshot) answer is accepted: the worker's price cap is the money guard.
- **R12 — `skins_buy_enabled`** (default `false`; dev compose sets `true`) switches buying on: off → the item page shows no buy panel (`SkinDetailOut.buy_enabled`) and `POST /orders` answers 409 `buying_disabled`. Prod turns it on at launch (M5).
- **R13 — Dev Waxpeer fake** (`CSMARKET_WAXPEER_FAKE=true`; refused at startup in prod): the worker, scheduler and API use an in-process fake whose trades live in Redis, so local runs and e2e can buy without spending money. The fake sends the offer by itself a few seconds after the buy; a dev-only `POST /api/v1/dev/orders/{number}/trade {action: accept|decline|rollback}` drives the rest. With the owner's real key and the fake off, local buys are real purchases — the runbook says so in bold.
- **R14 — Ops signals through Prometheus, not an app-level Telegram bot:** the worker and scheduler expose `/metrics` (`prometheus_client.start_http_server`, ports `worker_metrics_port=9101`, `scheduler_metrics_port=9102`, not published), Prometheus scrapes them, Alertmanager sends to Telegram (spec §12). A scheduler job sets gauges every minute (stuck orders, attention count, Waxpeer balance).
- **R15 — Not in M4a (M4b):** WebSocket order pushes, email, admin pricing editor and preview, per-item price overrides, dashboard, `my-history` orphan detection, email verification.

## Review Focus

1. **One order, one purchase, one refund.** A double-clicked «Купить», a replayed pay call, a kassa settle retry, the worker draining the same row twice, a lost Waxpeer answer, and the reconcile sweep racing the worker → at most one `buy-one-p2p`, one ledger debit, one refund. → Task 6 `test_wallet_pay_twice_debits_once`, `test_concurrent_wallet_pay_one_payment`; Task 8 `test_lost_answer_is_resolved_by_lookup_never_rebought`, `test_redrain_of_a_buying_order_buys_nothing`; Task 7 `test_refund_twice_credits_once`.
2. **A skin that may have been delivered is never refunded automatically**, and no refund happens while a skin is in flight. → Task 9 `test_unconfirmed_after_10_min_needs_attention_no_refund`, `test_rollback_after_accept_keeps_money_spent`; Task 7 `test_refund_refused_while_in_flight`; Task 12 `test_admin_refund_of_attention_order_needs_resolve`.
3. **A Waxpeer misconfiguration does not refund the shop as "sold out":** HTTP 403 and 429 on buy keep the order in flight. → Task 8 `test_forbidden_buy_keeps_order_buying_and_alerts`, `test_rate_limited_buy_is_retried`.
4. **The buyer pays the price they saw, within the rules:** a moved price beyond ±2 % is refused with the new price; a gone offer is replaced only within cost × 1.03; the trade-hold link is refused. → Task 4 `test_price_moved_beyond_tolerance_is_409`, `test_gone_offer_substituted_within_ceiling`, `test_trade_hold_link_is_refused`.
5. **A kassa cannot take an order's money back after the buy, and an expired or cancelled order cannot be paid.** → Task 5 `test_payme_cancel_of_performed_order_is_31007`, `test_expired_order_is_not_payable`; Task 6 `test_pay_after_expiry_is_409`.

---

## File structure (what M4a creates or changes)

```
apps/api/src/csmarket/
├── core/config.py                                    (T2, T3, T10, T11) order_*, skins_buy_enabled, waxpeer_*, *_metrics_port
├── core/metrics.py                                   (T3, T8, T10) waxpeer calls, buys, refunds, attention, gauges
├── modules/orders/{__init__,api,models,fsm,paid,service,checkout,paying,schemas,routes,trade_view,
│                   refunds,buying,trades,sweeps,health,dev_routes}.py + README.md (T2, T4–T12)
├── modules/skins/{waxpeer_trades,waxpeer_fake}.py, waxpeer.py (params), schemas.py (buy_enabled)  (T3, T4, T11)
├── modules/payments/{payable,hooks,gateways/base,gateways/mock,topups}.py + click/payme/uzum service sweeps (T5)
├── modules/wallet/{service,entries,schemas}.py       (T2, T6, T7) purchase / refund kinds and services
├── modules/users/tradelink.py                        (T1) hold → bad
├── modules/admin/{orders_routes,orders_schemas,orders_service}.py,
│                 users_service.py, payments_service.py                          (T5, T12)
├── api/v1/router.py, bootstrap.py                    (mounts, prod refusal of the fake)
apps/api/migrations/versions/0013_orders_skin_trades.py                          (T2)
apps/worker/src/csmarket_worker/{consumer,metrics}.py                            (T8, T10)
apps/scheduler/src/csmarket_scheduler/jobs/{orders_expiry,trades_reconcile,orders_health,
                                            trades_protection,trades_audit}.py, metrics.py (T9, T10)
infra/prometheus/{prometheus.yml,alerts/orders.yml}, docker-compose{,.prod}.yml (T10)
apps/web/src/lib/{orders,order-key,prefer-balance,order-poll}.ts, components/skins/{SkinBuyPanel,
  PaymentPicker}.tsx, components/order/*, app/[locale]/{orders/[number],account/orders}/page.tsx (T13, T14)
packages/i18n/locales/{ru,uz,en}/web.json                                        (+ web.buy, web.orders)
apps/admin/src/features/{orders,trades}/*                                        (T15)
e2e/tests/{buy,admin-orders}.spec.ts                                             (T16)
docs/: decisions/0007-orders-buying-trades.md, runbooks/{orders,waxpeer}.md, product/flows/buy.md,
       architecture/sequence-diagrams/{checkout,buy,trade-reconcile}.mmd, …       (T17)
```

---

### Task 1: Trade-hold links are refused

**Files:**

- Modify: `apps/api/src/csmarket/modules/users/tradelink.py:143-150`, `apps/web/src/lib/trade-link.ts` (`verdictMessage`), `packages/i18n/locales/{ru,uz,en}/web.json` (`web.account.tradeLink.status.hold` copy), `apps/api/src/csmarket/modules/users/README.md`, `docs/product/flows/trade-link.md`
- Test: `apps/api/tests/unit/test_users_tradelink.py`, `apps/api/tests/integration/test_users_trade_link.py`, `apps/web/src/lib/trade-link.test.ts`

**Interfaces:**

- Produces: `check_trade_link(...)` returns `CheckResult(verdict="bad", reason="hold")` for a non-zero Steam trade hold; web `verdictMessage({verdict:"bad", reason:"hold"})` → `{tone: "bad", key: "hold"}`.

- [ ] **Step 1: Tests first.** In `test_users_tradelink.py` change the hold expectation and add:

```python
async def test_a_trade_hold_is_bad_not_warn(fake_waxpeer_ok, fake_hold_days, redis) -> None:
    fake_hold_days.days = 3
    result = await check_trade_link(LINK, waxpeer=fake_waxpeer_ok, hold=fake_hold_days, redis=redis)
    assert result == CheckResult(verdict="bad", reason="hold")
```

(Use the file's existing fakes and its `LINK` constant; the cached verdict test for `hold` changes the same way.) In `trade-link.test.ts`: `expect(verdictMessage({verdict: "bad", reason: "hold"})).toEqual({tone: "bad", key: "hold"})`, and `warn` no longer maps `hold` (`warn` with any reason → `{tone: "warn", key: "unknown"}` if that key exists; otherwise drop the `warn` branch and its test — `warn` is no longer produced).

- [ ] **Step 2: Implement.** `tradelink.py`: `return CheckResult(verdict="bad", reason="hold")` and update the module docstring ("a hold is refused, owner 2026-10-01"). `trade-link.ts`: the `bad` branch maps `reason === "hold"` to key `hold`. Copy `web.account.tradeLink.status.hold`, ru: «Steam задерживает обмены на этом аккаунте: включите Steam Guard в мобильном приложении. Через 7 дней покупка станет доступна.»; uz and en equivalents. The account page shows it with the `bad` tone.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_users_tradelink.py tests/integration/test_users_trade_link.py tests/contract/test_steam_trade_hold.py -q
cd ../.. && pnpm --filter @csmarket/web test && pnpm --filter @csmarket/i18n test
make lint typecheck
git add -A && git commit -m "feat(api/users): a Steam trade hold makes the trade link bad

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Orders foundation — tables, FSM, ledger kinds, settings

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/{__init__,api,models,fsm}.py`, `modules/orders/README.md`, `apps/api/migrations/versions/0013_orders_skin_trades.py`
- Modify: `core/config.py` (+ settings below), `.env.example`, `infra/secrets-example/api.env`, `docker-compose.yml` (`CSMARKET_SKINS_BUY_ENABLED: "true"` in the dev `x-app-env`), `modules/payments/models.py` (FK + purpose check on `order_id`), `modules/wallet/service.py` (`TX_KINDS`), `modules/wallet/schemas.py` + `modules/admin/users_schemas.py` (entry kind Literals), `apps/web/src/lib/balance.ts` (`EntryKind`), `packages/i18n/locales/{ru,uz,en}/web.json` (`web.balance.kind.purchase|refund`), `apps/admin/src/features/users/labels.ts` (`purchase` «Покупка», `refund` «Возврат на баланс»), `migrations/env.py`, `apps/scheduler/src/csmarket_scheduler/main.py` (model import), integration `conftest.py` (`_EMPTY_IN_ORDER`: `skin_trades`, then `orders` after `payments`), `tests/unit/test_import_order.py`, `docs/architecture/module-map.md`
- Test: `apps/api/tests/unit/test_orders_fsm.py`, `apps/api/tests/integration/test_orders_models.py`, `apps/api/tests/unit/test_config.py` (extend)

**Interfaces:**

- Produces:
  - `orders.models.Order` (`orders`): `id uuid pk`, `number String(8) unique`, `user_id → users.id RESTRICT`, `status String(12)` CHECK in `ORDER_STATUSES`, `skin_item_id → skin_items.id RESTRICT`, `market_hash_name String(255)`, `phase String(16) default ''`, `slug String(160)`, `listing_id BigInteger` (the offer the buyer chose, after any checkout substitution), `cost_units Integer` (Waxpeer units we agreed to pay at checkout), `cost_usd Numeric(12,6)`, `price_usd Numeric(12,6)`, `price_uzs Numeric(14,0)`, `fx_snapshot_id → fx_snapshots.id RESTRICT`, `trade_link Text` (snapshot), `idempotency_key String(160)`, `paid_with String(16) | None` (`wallet|click|payme|uzum|mock`), `created_at`, `updated_at`, `expires_at`, `paid_at`, `delivered_at`, `cancelled_at`, `failed_at`, `refunded_at`, `refunded_to String(8) | None` CHECK `refunded_to IN ('balance')`, `failure_reason String(32) | None`, `claimed_at`, `claimed_by String(64) | None`, `next_check_at | None`; unique `(user_id, idempotency_key)`; indexes `ix_orders_status_next_check (status, next_check_at)`, `ix_orders_user_created (user_id, created_at DESC)`, `ix_orders_number` with `text_pattern_ops` (admin prefix search, like 0012).
  - `orders.models.SkinTrade` (`skin_trades`): `order_id uuid pk → orders.id CASCADE`, `project_id String(64) unique` (= order id), `waxpeer_id BigInteger | None`, `listing_id BigInteger`, `paid_units Integer`, `bought_units Integer | None`, `status SmallInteger | None` (None = never reached Waxpeer), `escrow_status String(32) | None`, `trade_id String(32) | None`, `send_until | None`, `release_date | None`, `is_released bool default false`, `accepted_at | None`, `reason Text | None`, `penalties JSONB | None`, `seller JSONB default {}`, `buy_pending bool default false`, `buy_unconfirmed_at | None`, `attention_reason String(32) | None` CHECK in `ATTENTION_REASONS`, `audit_verdict String(32) | None`, `last_polled_at | None`, `resolved_at | None`, `resolved_by String(64) | None`, `resolved_note Text | None`, `created_at`, `updated_at`; indexes `ix_skin_trades_protection (status, is_released)`, `ix_skin_trades_attention (attention_reason) WHERE attention_reason IS NOT NULL AND resolved_at IS NULL`, `ix_skin_trades_created_at`.
  - `orders.models`: `ORDER_STATUSES = ("pending","paid","buying","trade_sent","delivered","cancelled","failed","returned")`, `TERMINAL = frozenset({"delivered","cancelled","failed","returned"})`, `IN_FLIGHT = frozenset({"paid","buying","trade_sent"})`, `ATTENTION_REASONS = ("buy_unconfirmed","ambiguous_trade","rolled_back","waxpeer_forbidden","audit_divergence")`, `FAILURE_REASONS = ("sold_out","waxpeer_low_balance","invalid_trade_link","not_accepted","admin")`.
  - `orders.fsm`: `TRANSITIONS: dict[str, frozenset[str]]` (R1), `class InvalidOrderTransitionError(ConflictError)`, `move(order: Order, to: str) -> None` (raises on an illegal edge; stamps `updated_at` and the matching `*_at`: `paid_at`, `delivered_at`, `cancelled_at`, `failed_at`; `returned` stamps `failed_at`).
  - `orders.api`: `ORDERS_CHANNEL = "orders"`, `Order`, `SkinTrade`, `ORDER_STATUSES`, `IN_FLIGHT`, `TERMINAL`, `move` (later tasks add their exports here).
  - `payments.models.Payment.order_id` gets `ForeignKey("orders.id", ondelete="RESTRICT")` and CHECK `ck_payments_purpose_order`: `(purpose = 'order') = (order_id IS NOT NULL)`; `provider` gains the value `wallet` (no DB check exists; `gateways` never registers it — R8 writes it directly).
  - `wallet.service.TX_KINDS = ("topup","topup_reversal","admin_adjust","purchase","refund")`; `EntryOut.kind` and `AdminEntryOut.kind` Literals gain `purchase`, `refund`.
  - `Settings`: `skins_buy_enabled: bool = False`, `order_expiry_minutes: int = 15`, `order_price_tolerance: Decimal = Decimal("0.02")`, `order_substitute_ceiling: Decimal = Decimal("0.03")`, `order_unconfirmed_minutes: int = 10`, `trades_reconcile_seconds: int = 10`, `waxpeer_buy_timeout_seconds: float = 20.0`, `waxpeer_fake: bool = False`.

- [ ] **Step 1: FSM tests first**

```python
# apps/api/tests/unit/test_orders_fsm.py
import pytest

from csmarket.modules.orders.fsm import TRANSITIONS, InvalidOrderTransitionError, move
from csmarket.modules.orders.models import ORDER_STATUSES, TERMINAL, Order


def _order(status: str) -> Order:
    return Order(status=status)


@pytest.mark.parametrize(
    ("src", "dst"),
    [("pending", "paid"), ("pending", "cancelled"), ("paid", "buying"),
     ("buying", "trade_sent"), ("buying", "delivered"), ("buying", "failed"),
     ("buying", "returned"), ("trade_sent", "delivered"), ("trade_sent", "returned")],
)
def test_allowed_edges_move_and_stamp(src: str, dst: str) -> None:
    order = _order(src)
    move(order, dst)
    assert order.status == dst
    assert order.updated_at is not None


@pytest.mark.parametrize("src", sorted(TERMINAL))
def test_terminal_states_have_no_exit(src: str) -> None:
    for dst in ORDER_STATUSES:
        with pytest.raises(InvalidOrderTransitionError):
            move(_order(src), dst)


def test_paid_cannot_jump_to_delivered() -> None:
    with pytest.raises(InvalidOrderTransitionError):
        move(_order("paid"), "delivered")


def test_every_status_has_an_entry() -> None:
    assert set(TRANSITIONS) == set(ORDER_STATUSES)


def test_paid_stamps_paid_at_and_returned_stamps_failed_at() -> None:
    a, b = _order("pending"), _order("buying")
    move(a, "paid")
    move(b, "returned")
    assert a.paid_at is not None and b.failed_at is not None
```

- [ ] **Step 2: FSM + models.** `fsm.py`:

```python
"""The order state machine (ruling R1) — the only place an order's status changes."""

from __future__ import annotations

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.modules.orders.models import Order

TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"paid", "cancelled"}),
    "paid": frozenset({"buying"}),
    "buying": frozenset({"trade_sent", "delivered", "failed", "returned"}),
    "trade_sent": frozenset({"delivered", "returned"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "returned": frozenset(),
}

_STAMP = {"paid": "paid_at", "delivered": "delivered_at", "cancelled": "cancelled_at",
          "failed": "failed_at", "returned": "failed_at"}


class InvalidOrderTransitionError(ConflictError):
    """An order was asked to move along an edge the FSM does not have."""

    type_uri = "https://csmarket.uz/errors/invalid-order-transition"
    title = "Invalid order transition"


def move(order: Order, to: str) -> None:
    """Move ``order`` to ``to`` and stamp the matching timestamp.

    Raises:
        InvalidOrderTransitionError: ``to`` is not reachable from the current status.
    """
    if to not in TRANSITIONS.get(order.status, frozenset()):
        raise InvalidOrderTransitionError(
            f"order cannot go from {order.status} to {to}", code="invalid_order_transition"
        )
    at = now()
    order.status = to
    order.updated_at = at
    stamp = _STAMP.get(to)
    if stamp is not None:
        setattr(order, stamp, at)
```

`models.py` declares both tables exactly as **Interfaces** lists (follow `payments/models.py` for naming, `server_default`s, `CheckConstraint` names `ck_orders_status`, `ck_orders_refunded_to`, `ck_skin_trades_attention_reason`). Migration `0013` (`down_revision = "0012_payments_number_pattern_ops"`) creates `orders`, `skin_trades`, adds the FK + `ck_payments_purpose_order` to `payments`; downgrade drops them in reverse. `test_orders_models.py`: an order + trade round-trip; `(user_id, idempotency_key)` unique; `ck_payments_purpose_order` refuses an order payment without `order_id` and a top-up payment with one; the migration drift test (`tests/integration/test_migrations.py`) stays green.

- [ ] **Step 3: Ledger kinds and labels.** `TX_KINDS` + both Literals (drop the `type: ignore` in `EntryOut.of` if the Literal now covers every kind); web `EntryKind`; i18n `web.balance.kind.purchase` ru «Покупка», `refund` ru «Возврат на баланс» (uz/en equivalents); admin labels. Settings + templates (commented defaults; `CSMARKET_SKINS_BUY_ENABLED=false` in `infra/secrets-example/api.env` with the comment "on at launch (M5)"). `orders/README.md`: what the module owns, the FSM table, the lock order, "M4a/M4b". `module-map.md`: `orders` row built (M4a).
- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_orders_fsm.py tests/integration/test_orders_models.py tests/integration/test_migrations.py tests/integration/test_migration_roundtrip.py tests/unit/test_import_order.py -q
uv run pytest -n auto -q && cd ../.. && pnpm --filter @csmarket/web test && pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/i18n test
make lint typecheck
git add -A && git commit -m "feat(api/orders): orders and skin_trades tables, order FSM, purchase and refund ledger kinds

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Waxpeer purchase client

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/waxpeer_trades.py`
- Modify: `apps/api/src/csmarket/modules/skins/waxpeer.py` (`_request` gains `params`), `modules/skins/api.py` (exports), `core/metrics.py` (`csmarket_waxpeer_calls_total`), `core/logging.py` (`for_steamid64`, `seller_steam_id` redaction keys), `docs/architecture/metrics.md`
- Test: `apps/api/tests/contract/test_waxpeer_purchase.py`, `apps/api/tests/unit/test_waxpeer_trade_parse.py`

**Interfaces:**

- Consumes: `WaxpeerClient`, `WaxpeerError`, `WaxpeerUnavailableError`, `WaxpeerRateLimitedError` (`skins/waxpeer.py`).
- Produces (`skins.waxpeer_trades`, re-exported from `skins.api`):
  - Errors: `WaxpeerBuyRefusedError(WaxpeerError)(message, *, new_price_units: int | None, body: str = "")` — 200 `success:false`; `WaxpeerForbiddenError(WaxpeerError)` — HTTP 403 (the IP whitelist); 429 keeps M2's `WaxpeerRateLimitedError`; network / unreadable → `WaxpeerUnavailableError`; HTTP ≥ 500 → `WaxpeerError(status=…)`.
  - `class WaxpeerBuy(BaseModel, frozen)`: `id: int`, `price_units: int`.
  - `class WaxpeerSeller(BaseModel, frozen)`: `name: str | None`, `avatar_url: str | None`, `level: int | None`, `joined_at: datetime | None`.
  - `class WaxpeerTrade(BaseModel, frozen)`: `id: int`, `project_id: str`, `status: int` (−1 when unparsable), `trade_id: str | None`, `done: bool`, `reason: str | None`, `release_date: datetime | None`, `is_released: bool`, `send_until: datetime | None`, `price_units: int`, `penalties: dict[str, Any] | None`, `escrow_status: str | None`, `seller: WaxpeerSeller`. `for_steamid64` is **dropped at parse time** (never stored, never logged).
  - `parse_trade(raw: dict[str, Any]) -> WaxpeerTrade` — `send_until` / `seller_steam_joined` are epoch seconds (string or int); `release_date` ISO 8601 with `Z`; empty `penalties` → `None`.
  - `class TradeClient(Protocol)`: `async buy_one_p2p(*, item_id: int, price_units: int, partner: int, token: str, project_id: str) -> WaxpeerBuy`; `async check_project_ids(project_ids: Sequence[str]) -> list[WaxpeerTrade]` (≤ 100 ids, `GET /v1/check-many-project-id?id=…&id=…`; unknown ids → `[]`); `async balance_units() -> int` (`GET /v1/user` → `user.wallet`); `async search_listings(names: Sequence[str]) -> dict[str, list[dict[str, Any]]]` (M2's).
  - `class WaxpeerTradeClient(WaxpeerClient)` implements `TradeClient`.
  - `trade_client(settings: Settings | None = None) -> TradeClient` — the real client with `timeout_seconds=settings.waxpeer_buy_timeout_seconds` (Task 11 adds the fake branch).
  - Metric `csmarket_waxpeer_calls_total{endpoint="buy|lookup|balance", outcome="ok|refused|forbidden|rate_limited|unavailable|error"}` via `record_waxpeer_call(endpoint, outcome)` (never raises).

- [ ] **Step 1: Contract tests first** — port `yupay:apps/api/tests/contract/test_waxpeer_client_purchase.py` (162 LOC, inline respx recordings captured on YuPay prod 2026-09-28) with **redrawn** `partner`/`token`/Steam IDs, plus:

```python
# apps/api/tests/contract/test_waxpeer_purchase.py (additions to the port)
@respx.mock
async def test_buy_403_is_forbidden_not_a_refusal() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(403, text="You need to whitelist your IP")
    with pytest.raises(WaxpeerForbiddenError):
        await _client().buy_one_p2p(item_id=1, price_units=1000, partner=39734273,
                                    token="AbCdEf12", project_id="o-1")


@respx.mock
async def test_buy_429_is_rate_limited() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(429, headers={"Retry-After": "2"})
    with pytest.raises(WaxpeerRateLimitedError):
        await _client().buy_one_p2p(item_id=1, price_units=1000, partner=39734273,
                                    token="AbCdEf12", project_id="o-1")


@respx.mock
async def test_lookup_sends_repeated_ids_and_drops_the_buyer_steam_id() -> None:
    route = respx.get(f"{BASE}/check-many-project-id").respond(
        200, json={"success": True, "trades": [_trade(status=4, for_steamid64="76561190000000000")]})
    trades = await _client().check_project_ids(["o-1", "o-2"])
    assert route.calls.last.request.url.params.get_list("id") == ["o-1", "o-2"]
    assert "for_steamid64" not in trades[0].model_dump()


@respx.mock
async def test_balance_units_reads_user_wallet() -> None:
    respx.get(f"{BASE}/user").respond(200, json={"success": True, "user": {"wallet": 53300}})
    assert await _client().balance_units() == 53300


@respx.mock
async def test_buy_refusal_carries_new_price() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(
        200, json={"success": False, "msg": "Price changed", "new_price": 9})
    with pytest.raises(WaxpeerBuyRefusedError) as err:
        await _client().buy_one_p2p(item_id=1, price_units=5, partner=39734273,
                                    token="AbCdEf12", project_id="o-1")
    assert err.value.new_price_units == 9


@respx.mock
async def test_no_url_or_body_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(500, text="boom token=AbCdEf12")
    with pytest.raises(WaxpeerError):
        await _client().buy_one_p2p(item_id=1, price_units=5, partner=39734273,
                                    token="AbCdEf12", project_id="o-1")
    assert "AbCdEf12" not in caplog.text and "api=" not in caplog.text
```

(`BASE = "https://api.waxpeer.com/v1"`, `_client()` builds `WaxpeerTradeClient(api_key="k", base_url=BASE, timeout_seconds=1)`, `_trade(**overrides)` returns a dict shaped like the recording.) Unit `test_waxpeer_trade_parse.py`: epoch strings and ints, `Z` dates, naive/bad timestamps → `None`, unparsable status → −1, empty penalties → `None`, seller mapping.

- [ ] **Step 2: Implement.** `waxpeer.py` `_request(method, path, *, json=None, params=None)` (params merged after `api`; list values repeat the key). `waxpeer_trades.py` ports `ym:fulfillment/suppliers/waxpeer_trades.py` (166 LOC) onto csmarket's error types with the deltas above: frozen pydantic models (AGENTS §7), 403 → `WaxpeerForbiddenError`, `balance_units` from `ym:fulfillment/suppliers/waxpeer_client.py:374`, `record_waxpeer_call` on every outcome. Log lines: `skins.waxpeer.call` with `endpoint`, `outcome`, `status` only.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/contract/test_waxpeer_purchase.py tests/unit/test_waxpeer_trade_parse.py tests/contract -q --cov=csmarket.modules.skins.waxpeer_trades --cov-report=term-missing
cd ../.. && make lint typecheck
git add -A && git commit -m "feat(api/skins): Waxpeer purchase client — buy, lookup by project id, balance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Checkout — `POST /orders`, order reads, buyer trade view

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/{checkout,service,schemas,routes,trade_view}.py`
- Modify: `modules/orders/api.py` (exports), `modules/skins/schemas.py` + `skins/routes.py` (`SkinDetailOut.buy_enabled`), `core/config.py` (`auth_ip_guard_bucket_max["order-create"] = 60`, `["order-pay"] = 60`), `api/v1/router.py`, `infra/prometheus/alerts/api.yml` (`ApiHighLatency` / `ApiWaxpeerLatency` handler regexes gain `/orders` POST — R11), `AGENTS.md` §11 (the carve-out line), `docs/api/openapi.json` + client
- Test: `apps/api/tests/integration/test_orders_checkout.py`, `apps/api/tests/integration/test_orders_read.py`, `apps/api/tests/unit/test_order_trade_view.py`, `apps/api/tests/integration/orders_factory.py` (new: `make_order`, `make_trade`, `saved_trade_link`)

**Interfaces:**

- Consumes: `skins.service.get_item(db, slug, *, categories)`, `skins.listings.listings_for(item, *, client, redis, budget_per_minute)`, `skins.pricing.quote`, `skins.pricing.to_uzs`, `skins.settings.load_rules`, `fx.api.current_usd_uzs`, `users.tradelink.parse_tradelink`, `core.numbers.order_number`, `core.numbers.allocate`, `auth.ip_guard.guard_ip`, `core.cursor` (keyset), Task 2 models/FSM, Task 3 `trade_client()` (its `search_listings`).
- Produces:
  - `POST /api/v1/orders` (signed in, `Idempotency-Key` 16–160 required, `guard_ip(bucket="order-create", subject=user.id)`), body `OrderCreateIn{slug: str (1..160), listing_id: int (>0), price_uzs: int (>0, the price the panel showed)}` → `201 OrderOut`; a replayed key → `200`/`201` with the stored order whatever the body.
  - `GET /api/v1/orders/{number}` (owner only; another user's, unknown or malformed → 404) → `OrderOut`.
  - `GET /api/v1/me/orders?cursor=` → `OrdersPage{items: list[OrderOut], next_cursor: str | None}` (20 per page, newest first; hides `cancelled` and an expired unpaid `pending`); trades loaded in **one** query per page (query-count test).
  - `OrderOut{number, status: OrderStatusOut ("pending"|"paid"|"buying"|"trade_sent"|"delivered"|"cancelled"|"failed"|"returned"), slug, name (market_hash_name), phase, image_url, price_uzs: str, price_usd: str, created_at, expires_at, paid_at, delivered_at, paid_with: str | None, refunded_to: "balance" | None, payable: bool, trade: SkinTradeOut | None}` — a `pending` order past `expires_at` reads `cancelled` with `payable=false` before the sweep writes it.
  - `trade_view.SkinTradeOut{state: "buying"|"offer_sent"|"accepted"|"released"|"failed", reason_code: "not_accepted"|"sold_out"|"try_later"|"support"|"other" | None, offer_url: str | None, send_until, release_date, seller: SkinSellerOut{name, avatar_url, level, joined_at} | None, refunded_to: "balance" | None}`; `skin_trade_out(order: Order, trade: SkinTrade | None) -> SkinTradeOut | None` (port of `ym:skins/trade_view.py`, 116 LOC: `None` for `pending`/`cancelled`; `paid` with no trade row → `buying`; state rules: 6 or order `failed`/`returned` → failed; 5 or `is_released` → released; 4 → `accepted` if `release_date` else `offer_sent`; else buying. Reason: an `attention_reason` of `buy_unconfirmed`/`ambiguous_trade`/`waxpeer_forbidden` → `support`; `failure_reason == "waxpeer_low_balance"` → `try_later`; `sold_out` → `sold_out`; `not_accepted` → `not_accepted`; else `other`. `offer_url = https://steamcommunity.com/tradeoffer/{trade_id}/`. `refunded_to` only when the order says so.)
  - `checkout.create_order(db, *, redis, user: User, body: OrderCreateIn, idempotency_key: str, client: SearchClient, settings: Settings) -> tuple[Order, bool]` (bool = created now).
  - Errors (problem+json, `code=`): 409 `buying_disabled`, `trade_link_missing`, `trade_link_bad` (+ `reason`), `price_changed` (+ `price_uzs` new), `offer_gone` (+ `next_offer: {listing_id, price_uzs} | null`); 404 unknown/hidden item; 503 `rate_unavailable` (no fresh soʻm rate).

- [ ] **Step 1: Tests first** (`orders_factory.make_user_with_link(db, verdict="ok")` saves a fake link; listings come from a stub `SearchClient` returning chosen rows; `fx` rate seeded with `record_snapshot`). Required cases, each its own test:

```python
async def test_price_moved_beyond_tolerance_is_409(api, user_headers, stub_listings) -> None:
    stub_listings.set("ak-47-redline-ft", [(111, 10_000)])          # $10.00 cost
    shown = await _shown_price(api, "ak-47-redline-ft", 111)          # what the panel showed
    stub_listings.set("ak-47-redline-ft", [(111, 11_000)])          # cost +10 %
    r = await api.post("/api/v1/orders", headers=_key(user_headers),
                       json={"slug": "ak-47-redline-ft", "listing_id": 111, "price_uzs": shown})
    assert r.status_code == 409 and r.json()["code"] == "price_changed"
    assert int(r.json()["price_uzs"]) > shown


async def test_gone_offer_substituted_within_ceiling(api, user_headers, stub_listings) -> None:
    stub_listings.set("ak-47-redline-ft", [(111, 10_000), (112, 10_200)])
    shown = await _shown_price(api, "ak-47-redline-ft", 111)
    stub_listings.set("ak-47-redline-ft", [(112, 10_200), (113, 12_000)])   # 111 sold
    r = await api.post("/api/v1/orders", headers=_key(user_headers),
                       json={"slug": "ak-47-redline-ft", "listing_id": 111, "price_uzs": shown})
    assert r.status_code == 201
    order = await _order(r.json()["number"])
    assert order.listing_id == 112 and order.cost_units == 10_200
    assert Decimal(r.json()["price_uzs"]) <= shown                  # never more than shown


async def test_gone_offer_without_substitute_is_409_with_next(api, user_headers, stub_listings) -> None:
    stub_listings.set("ak-47-redline-ft", [(111, 10_000)])
    shown = await _shown_price(api, "ak-47-redline-ft", 111)
    stub_listings.set("ak-47-redline-ft", [(113, 12_000)])
    r = await api.post("/api/v1/orders", headers=_key(user_headers),
                       json={"slug": "ak-47-redline-ft", "listing_id": 111, "price_uzs": shown})
    assert r.status_code == 409 and r.json()["code"] == "offer_gone"
    assert r.json()["next_offer"]["listing_id"] == 113


async def test_trade_hold_link_is_refused(api, db, user_with_link) -> None:
    user_with_link.trade_link_verdict, user_with_link.trade_link_reason = "bad", "hold"
    await db.commit()
    r = await _create(api, user_with_link)
    assert r.status_code == 409 and r.json()["code"] == "trade_link_bad"
    assert r.json()["reason"] == "hold"
```

Also: replayed key returns the same order (one row) whatever the body; two concurrent first-time requests with one key → one order (IntegrityError race path re-reads the replay); missing link → `trade_link_missing`; unchecked verdict passes; `buying_disabled` when the setting is off; within ±2 % → server price billed; hidden item 404; rate older than `fx_max_age_days` → 503; `order-create` bucket answers 429 on the 11th call per minute for one account; the order snapshots `trade_link`, `cost_units`, `cost_usd = cost_units / 1000`, `fx_snapshot_id`, `expires_at = now + 15 min`, number from `order_number()` (8 chars, never `T`). Reads: owner gets the order, another user 404, malformed number 404, expired `pending` reads `cancelled`, list hides cancelled/expired and pages by cursor with a constant query count (assert > 0). `test_order_trade_view.py`: every state/reason row of the mapping above, offer URL, `refunded_to` shown only when set (port of `ym` `tests/unit/test_skin_trade_view.py`).

- [ ] **Step 2: Implement `checkout.create_order`** in this order (no lock is held across the Waxpeer read; the read transaction ends before it — copy the scalars you need into a frozen value object first, then `await db.rollback()`):

```python
async def create_order(db, *, redis, user, body, idempotency_key, client, settings):
    existing = await _by_key(db, user.id, idempotency_key)
    if existing is not None:
        return existing, False
    if not settings.skins_buy_enabled:
        raise ConflictError("buying is switched off", code="buying_disabled")
    link = _gate_trade_link(user)                      # R10: missing / bad → 409
    item = await get_item(db, body.slug, categories=enabled_categories(settings))
    rules = await load_rules(db)
    rate = await current_usd_uzs(db, redis, max_age_days=settings.fx_max_age_days)
    if rate is None:
        raise UpstreamUnavailableError("no soʻm rate", code="rate_unavailable")
    snap = _ItemSnapshot.of(item)                      # frozen: id, slug, names, taxonomy, overrides
    await db.rollback()                                # release the connection before Waxpeer
    rows, _degraded = await listings_for(item_view(snap), client=client, redis=redis,
                                         budget_per_minute=_budget(settings))
    priced = [(row, _price(row.price_units, snap, rules, rate)) for row in rows]
    target, price_usd, price_uzs = _choose(priced, body, settings, rate)  # tolerance / R4 / 409s
    order = Order(...)                                 # snapshot every field in Interfaces
    order.number = await allocate(db, Order.number, order_number)
    db.add(order)
    try:
        await db.flush()
    except IntegrityError:                             # same key raced us
        await db.rollback()
        replay = await _by_key(db, user.id, idempotency_key)
        if replay is None:
            raise
        return replay, False
    await db.commit()
    return order, True
```

`_price(units, snap, rules, rate) -> (price_usd, price_uzs)` = `quote(units, rules=rules, category=…, weapon=…, count_auto=…, item_pp=snap.margin_override_pp, fixed_price_usd=snap.fixed_price_usd, steam_price_units=snap.steam_price_units).price_usd` and `to_uzs(price_usd, rate.rate, round_to=rules.uzs_round_to)` — the same functions the item page uses, so the panel's number and the server's agree. `_choose`:

```python
def _choose(priced, body, settings, rate):
    """(listing, price_usd, price_uzs) to bill, or a 409 — R4 and the ±2 % rule."""
    shown = Decimal(body.price_uzs)
    chosen = next((p for p in priced if p[0].listing_id == body.listing_id), None)
    if chosen is not None:
        row, (usd, uzs) = chosen
        if abs(uzs - shown) > shown * settings.order_price_tolerance:
            raise ConflictError("the price has changed", code="price_changed", price_uzs=str(uzs))
        return row, usd, uzs                                     # bill the server price
    ceiling = shown * (1 + settings.order_substitute_ceiling)
    for row, (usd, uzs) in sorted(priced, key=lambda p: p[1][1]):
        if uzs <= ceiling:
            if uzs <= shown:
                return row, usd, uzs                             # cheaper or equal: its own price
            return row, usd_of(shown, rate.rate), shown          # dearer: never more than shown
    nxt = min(priced, key=lambda p: p[1][1], default=None)
    raise ConflictError("this offer was just sold", code="offer_gone",
                        next_offer=None if nxt is None else
                        {"listing_id": nxt[0].listing_id, "price_uzs": str(nxt[1][1])})


def usd_of(uzs: Decimal, rate: Decimal) -> Decimal:
    """The USD a soʻm amount is worth at ``rate``, to 6 places (the order's ``price_usd``)."""
    return (uzs / rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
```

(`usd_of` gets two unit tests: an exact rate and a rounding case.) Routes in `orders/routes.py` parse and dispatch only (`_required_key` as in `payments/routes.py`). `service.py` holds `get_owned(db, user_id, number)`, `list_for_user(db, user_id, cursor)`, `order_out(order, trade, image_url)`. `SkinDetailOut.buy_enabled = settings.skins_buy_enabled`. Add the AGENTS §11 line and the two alert regex additions (R11).

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_checkout.py tests/integration/test_orders_read.py tests/unit/test_order_trade_view.py -q --cov=csmarket.modules.orders --cov-report=term-missing
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/orders): checkout re-prices from live offers, order reads and the buyer trade view

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Payments learn orders — resolver, hooks, kassas, sweeps

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/paid.py` (`mark_paid`)
- Modify: `modules/payments/{payable,hooks,gateways/base,gateways/mock,api}.py`, `modules/click/service.py` (`cancel_stale`), `modules/payme/service.py` (`cancel_stale`, `ReversalRefusedError` catch), `modules/uzum/service.py` (`fail_stale`, catch), `modules/admin/{payments_service,payments_schemas}.py` (order block), module READMEs (payments, click, payme, uzum: "top-up or order"), `docs/api/openapi.json` + client
- Test: `apps/api/tests/integration/test_payable_resolver.py` (extend), `test_payment_hooks.py` (extend), `test_payments_orders_click.py`, `test_payments_orders_payme.py`, `test_payments_orders_uzum.py`, `test_kassa_sweeps_orders.py`, `test_admin_payments.py` (extend)

**Interfaces:**

- Consumes: Task 2 `Order`, `orders.fsm.move`, `orders.api.ORDERS_CHANNEL`.
- Produces:
  - `Payable` gains `order: Order | None` (and `kind="order"` resolves a real order). `resolve(db, account, *, lock=False)`: a non-`T` value that `is_number` loads the order by number (`FOR UPDATE` + `populate_existing` when `lock`); reason: `pending` before `expires_at` → `ok`; `pending` after `expires_at` or `cancelled` → `expired`; any other status → `paid`. `amount_uzs = order.price_uzs`.
  - `orders.paid.mark_paid(db, order: Order, *, provider: str) -> None` — `move(order, "paid")`, `order.paid_with = provider`, `await db.execute(select(func.pg_notify(ORDERS_CHANNEL, order.number)))`; exported from `orders.api`. `orders.api` must **not** import `payments` (a cold-import test asserts `csmarket.modules.payments` is absent from `sys.modules` after `import csmarket.modules.orders.api`).
  - `hooks`: `_lock_owner_then_payment(db, payment) -> WalletTopup | Order` (lock order: the top-up or the order, then the payment); `ensure_attempt` for an order creates `Payment(purpose="order", order_id=…, number=order.number, amount_uzs=order.price_uzs)`; `settle` for an order: payment `succeeded`, then `mark_paid` (an order no longer `pending` → `AlreadyPaidError`, so the kassa refuses the second charge); `reverse` for an order raises `OrderReversalRefusedError`; `cancel_pending` unchanged for orders (the order stays `pending` until the expiry sweep).
  - `class ReversalRefusedError(ConflictError)` (`type_uri …/reversal-refused`); `TopupSpentError(ReversalRefusedError)` keeps its own `type_uri`; `OrderReversalRefusedError(ReversalRefusedError)` (`…/order-reversal-refused`). Payme maps `ReversalRefusedError` → −31007, Uzum → 10017 (R7).
  - `return_url(number, locale) -> str`: a `T…` number → the M3 top-up page; any other → `{web_base_url}[/uz|/en]/orders/{number}`; `MockGateway.intent_url` follows.
  - Kassa timeout sweeps cover order attempts: each sweep scans `pending` attempts older than its timeout for **both** purposes; per row it locks the owner first (`WalletTopup` or `Order`, `FOR UPDATE SKIP LOCKED`), then the kassa row, then cancels the attempt. Order attempts never touch the order's status.
  - Admin `AdminPaymentDetail.order: AdminOrderInfo{number, status, price_uzs} | None`.

- [ ] **Step 1: Tests first.** Resolver: `ok` / `expired` (window passed; cancelled) / `paid` (each later status) / `not_found` / locks. Hooks: order attempt created and reused; settle → payment succeeded + order `paid` + `paid_with` + one `NOTIFY orders` (listen on a raw asyncpg connection in the test, as the worker does); a second settle through another attempt → `AlreadyPaidError` and no second `NOTIFY`; reverse → `OrderReversalRefusedError`; the lock-order two-session test from M3 repeated for an order (no deadlock when a kassa create and a settle race). Per kassa (`test_payments_orders_<kassa>.py`, using M3's request builders): the happy path on an order number pays the order; the amount must equal `price_uzs` (tiyin for Payme/Uzum); a paid order refuses a second charge (Click −4, Payme −31008 at Perform, Uzum 10008); **`test_payme_cancel_of_performed_order_is_31007`** and `test_uzum_reverse_of_confirmed_order_is_10017`; **`test_expired_order_is_not_payable`** (Click −9, Payme −31051, Uzum 10009). Sweeps: a stale order attempt is cancelled and the order stays `pending`; a top-up and an order swept in one pass; the scan skips an order a callback holds (SKIP LOCKED). Admin payment detail shows the order block.
- [ ] **Step 2: Implement** the deltas above; keep every M3 test green unchanged except where it asserted `NotImplementedError` for orders (replace those with the order behaviour and say so in the commit body). Kassa reason mapping already keys on `payable.reason`; check that `_REFUSALS` tables cover `paid` and `expired` for orders without code changes.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration -k "payable or hooks or orders_click or orders_payme or orders_uzum or sweeps_orders or admin_payments" -q
uv run pytest -n auto -q --cov=csmarket.modules.payments --cov=csmarket.modules.click --cov=csmarket.modules.payme --cov=csmarket.modules.uzum --cov-report=term
cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/payments): orders are payable through Click, Payme and Uzum; kassas cannot reverse them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Pay an order — from the balance or through a kassa

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/paying.py`, `modules/orders/dev_routes.py`
- Modify: `modules/wallet/service.py` (`debit_purchase`, `credit_order_refund`), `modules/wallet/api.py`, `modules/orders/routes.py` (`POST /orders/{number}/pay`), `api/v1/router.py` (dev router behind `_dev_gate`), `docs/api/openapi.json` + client
- Test: `apps/api/tests/integration/test_orders_pay.py`, `apps/api/tests/integration/test_wallet_purchase.py`

**Interfaces:**

- Consumes: Task 5 `resolve`, `ensure_attempt`, `get_gateway`, `mark_paid`; `wallet.user_account(lock=True)`, `wallet.post`, `wallet.balance`; `core.idempotency.{load_replay, save_replay}`.
- Produces:
  - `wallet.debit_purchase(db, *, user_id: str, order_id: str, amount: Decimal) -> WalletTransaction` — locks the wallet `FOR UPDATE`; replay of `purchase:order:{order_id}` returns the booked transaction before any balance check; balance < amount → `InsufficientBalanceError(code="balance_too_low")`; legs C `user_wallet` / D `house_payments_received`; reference `("order", order_id)`.
  - `wallet.credit_order_refund(db, *, user_id: str, order_id: str, amount: Decimal, paid_with: str) -> WalletTransaction` — key `refund:order:{order_id}`; legs D `user_wallet` / C `house_payments_received` when `paid_with == "wallet"`, else D `user_wallet` / C `provider_clearing:<paid_with>` (R9).
  - `POST /api/v1/orders/{number}/pay` (owner; `Idempotency-Key` required; `guard_ip(bucket="order-pay", subject=user.id)`), body `OrderPayIn{provider: "wallet"|"click"|"payme"|"uzum"|"mock", locale: "ru"|"uz"|"en"}` → `200 OrderPayOut{order: OrderOut, intent_url: str | None}`; replay scope `orders.pay:{number}` (same key + other body → 409 `idempotency_mismatch`).
  - `paying.pay_order(db, *, user_id, number, provider, locale, idempotency_key) -> OrderPayOut`:
    - `wallet`: lock the order (`resolve(lock=True)`), refuse unless `payable` (409 `order_not_payable`, `reason`), `debit_purchase`, insert `Payment(purpose="order", provider="wallet", provider_ref=f"wallet:{number}", status="created")` and `move(payment, "succeeded")`, `mark_paid(provider="wallet")`, save the replay, commit — one transaction (R8).
    - a kassa: `resolve(lock=True)`, refuse unless `payable`, `ensure_attempt`, `get_gateway(provider).intent_url(payable=…, locale=…)`, save the replay, commit.
  - Dev only: `POST /api/v1/dev/orders/{number}/pay` (404 unless `dev_login_active`; owner only; keyless — the docstring says why): resolve(lock), `ensure_attempt("mock")`, `mark_pending`, `settle(event_id=f"mock:{attempt.id}")`, commit.

- [ ] **Step 1: Tests first**

```python
async def test_wallet_pay_twice_debits_once(api, db, buyer, pending_order) -> None:
    await credit(db, buyer, 500_000)
    key = _key()
    first = await api.post(f"/api/v1/orders/{pending_order.number}/pay", headers=key,
                           json={"provider": "wallet", "locale": "ru"})
    second = await api.post(f"/api/v1/orders/{pending_order.number}/pay", headers=key,
                            json={"provider": "wallet", "locale": "ru"})
    assert first.status_code == second.status_code == 200
    assert await purchase_count(db, pending_order.id) == 1
    assert await user_balance(db, buyer.id) == 500_000 - pending_order.price_uzs


async def test_concurrent_wallet_pay_one_payment(two_sessions, buyer, pending_order) -> None:
    # two sessions, two different keys, released together: one pays, the other gets 409
    results = await race(two_sessions, lambda db, k: pay_order(
        db, user_id=buyer.id, number=pending_order.number, provider="wallet",
        locale="ru", idempotency_key=k))
    assert sorted(r.kind for r in results) == ["conflict", "ok"]
    assert await payments_for(pending_order.id) == 1


async def test_pay_after_expiry_is_409(api, db, buyer, pending_order, clock) -> None:
    clock.advance(minutes=16)
    r = await api.post(f"/api/v1/orders/{pending_order.number}/pay", headers=_key(),
                       json={"provider": "wallet", "locale": "ru"})
    assert r.status_code == 409 and r.json()["code"] == "order_not_payable"
    assert r.json()["reason"] == "expired"
```

Also: a short balance is 409 `balance_too_low` and leaves no payment, no ledger row, the order `pending`; a kassa pay returns an `intent_url` ending `/orders/<number>` (mock) and reuses the live attempt on a second call; a paid order refuses another provider; the `NOTIFY` is sent once on wallet pay; another user's number → 404; the dev pay route pays through the mock kassa and is 404 in prod; ledger legs match R8/R9 (`test_wallet_purchase.py`, including the refund replay key and both refund leg shapes; extend the hypothesis ledger property with `purchase`/`refund` postings).

- [ ] **Step 2: Implement** as specified (routes parse and dispatch; `paying.py` holds the logic; `orders.api` does not export `paying`).
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_pay.py tests/integration/test_wallet_purchase.py tests/integration/test_wallet_ledger_props.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/orders): pay an order from the balance in one transaction or through a kassa

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Refund to the balance and the in-flight guard

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/refunds.py`
- Modify: `modules/orders/api.py` (exports), `modules/wallet/entries.py` (resolve `reference_type == "order"` numbers through a bare `_ORDERS` table stub, like `_TOPUPS`), `core/metrics.py` (`csmarket_order_refunds_total{reason}`), `docs/architecture/metrics.md`
- Test: `apps/api/tests/integration/test_orders_refunds.py`, `apps/api/tests/integration/test_wallet_entries.py` (extend)

**Interfaces:**

- Consumes: Task 6 `credit_order_refund`; Task 2 models/FSM.
- Produces:
  - `refunds.refund_to_balance(db, *, order: Order, to_status: Literal["failed","returned"], reason: str, actor: str) -> bool` — the caller holds the order row `FOR UPDATE`; an order already refunded (`refunded_at` set) → `False`, nothing written; else books `credit_order_refund`, `move(order, to_status)`, sets `refunded_at`, `refunded_to="balance"`, `failure_reason=reason`, increments the metric, logs `orders.refunded` (number, amount, reason) → `True`. Flushes, never commits.
  - `refunds.in_flight(order: Order, trade: SkinTrade | None) -> bool` — `paid`, `buying`, `trade_sent` → `True`; a `delivered` order with an unresolved `attention_reason` → `True`; else `False`.
  - `refunds.admin_refund(db, *, number: str, admin_id: str) -> Order` — locks the order; refused (409 `order_in_flight`) unless the order is `buying` **and** its trade has an `attention_reason` in (`buy_unconfirmed`, `ambiguous_trade`, `waxpeer_forbidden`) **and** `resolved_at` is set (an operator checked Waxpeer: nothing was bought); then `refund_to_balance(to_status="failed", reason="admin", actor=f"admin:{admin_id}")`; an already-refunded order → 409 `already_refunded`. (Spec §7.8 "admin manual refund only from failed/returned/attention": `failed`/`returned` are refunded automatically, so attention is the only case left.)
  - Customer entries show `reference_number` = the order number for `purchase` and `refund`.

- [ ] **Step 1: Tests first** — `test_refund_twice_credits_once` (two calls on one locked order → one ledger row, second returns `False`); kassa-paid vs wallet-paid legs; `test_refund_refused_while_in_flight` (admin refund on `buying` without resolve → 409 `order_in_flight`; on `trade_sent` → 409; on `delivered` with unresolved `rolled_back` → 409); admin refund after resolve → `failed`, balance credited, audit-free here (Task 12 audits); the refund entry carries the order number in `/wallet/entries`.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_refunds.py tests/integration/test_wallet_entries.py -q --cov=csmarket.modules.orders --cov-report=term-missing
cd ../.. && make lint typecheck
git add -A && git commit -m "feat(api/orders): refund to the balance once, never while a skin is in flight

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The worker buys at Waxpeer

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/buying.py`
- Modify: `modules/orders/api.py` (exports `drain_paid`, `attempt_buy`), `apps/worker/src/csmarket_worker/consumer.py` (`_queues` registers `orders`), `apps/worker/tests/test_consumer.py` (the two "no queues" tests become "registers the orders queue"), `core/metrics.py` (`csmarket_order_buys_total{outcome}`), `docs/architecture/metrics.md`
- Test: `apps/api/tests/integration/test_orders_buying.py`, `apps/api/tests/integration/fake_trade_client.py` (scriptable `TradeClient` for tests)

**Interfaces:**

- Consumes: Task 3 `TradeClient`, errors, `trade_client()`; Task 7 `refund_to_balance`; `users.tradelink.parse_tradelink`; `skins.listings.listings_for` (substitutes); Task 2 models/FSM.
- Produces:
  - `buying.drain_paid(db: AsyncSession, *, limit: int = 10) -> int` — the worker's `Drain`: claims up to `limit` `paid` orders oldest first (`FOR UPDATE SKIP LOCKED`), moves each to `buying`, stamps `claimed_at`/`claimed_by` (hostname:pid), creates its `SkinTrade` (`project_id = order.id`, `listing_id`, `paid_units = cost_units`, `buy_pending = True`), commits, then calls `attempt_buy` for each claimed id in its own transaction; returns the number claimed.
  - `buying.attempt_buy(db, client: TradeClient, *, order_id: str, settings: Settings) -> str` (the outcome, for logs/tests) — the single buy path, also called by the reconcile sweep for `buy_pending` trades:
    1. Read order + trade **unlocked**; nothing to do unless the order is `buying` and `trade.buy_pending`.
    2. `parse_tradelink(order.trade_link)` fails → lock, `refund_to_balance(failed, "invalid_trade_link")`.
    3. **Lookup first:** `check_project_ids([order.id])` — `WaxpeerRateLimitedError`/`WaxpeerUnavailableError` → `"lookup_later"` (stays `buy_pending`); `WaxpeerForbiddenError` → attention `waxpeer_forbidden` (keeps `buy_pending`); a trade found → lock, mirror it (Task 9's `mirror`), `buy_pending = False` → `"adopted"` (never rebuy).
    4. Buy (`_buy`) with the queue `[(listing_id, paid_units)]` and at most one substitute (R4, ceiling `paid_units × (1 + order_substitute_ceiling)`); classification (R6):

```python
async def _buy(db, client, *, snap: _BuySnapshot, link: TradeLink, settings) -> str:
    ceiling = int(snap.paid_units * (1 + settings.order_substitute_ceiling))
    queue: list[tuple[int, int]] = [(snap.listing_id, snap.paid_units)]
    tried: set[int] = set()
    while queue:
        listing_id, units = queue.pop(0)
        tried.add(listing_id)
        try:
            bought = await client.buy_one_p2p(item_id=listing_id, price_units=units,
                                              partner=link.partner, token=link.token,
                                              project_id=snap.order_id)
        except WaxpeerForbiddenError:
            return await _attention(db, snap.order_id, "waxpeer_forbidden")   # keeps buy_pending
        except WaxpeerRateLimitedError:
            return "rate_limited"                                             # next tick retries
        except WaxpeerUnavailableError:
            return await _unconfirmed(db, snap.order_id)                      # resolve by lookup
        except WaxpeerError as err:                                           # incl. BuyRefused
            if err.status >= 500:
                return await _unconfirmed(db, snap.order_id)                  # a 5xx may have bought
            if await _low_balance(client, err, units):
                return await _refund(db, snap.order_id, "waxpeer_low_balance")
            if len(tried) == 1:                                               # one substitute only
                nxt = await _substitute(db, client, snap=snap, ceiling=ceiling, tried=tried)
                if nxt is not None:
                    queue.append(nxt)
            continue
        return await _record_bought(db, snap.order_id, bought, listing_id)    # waxpeer_id, units, 0
    return await _refund(db, snap.order_id, "sold_out")
```

(`_BuySnapshot` is a frozen value object read unlocked: `order_id`, `listing_id`, `paid_units`, `slug`, `waxpeer_name`; `_substitute` reads `listings_for` for the item and returns the cheapest `(listing_id, price_units)` not in `tried` with `price_units <= ceiling`, or `None`; `_attention`, `_unconfirmed`, `_refund`, `_record_bought` each open their own `FOR UPDATE` re-read of order + trade, re-check `status == "buying"` and the trade's expected flags, write, commit, and return the outcome string.)

    `_low_balance(client, refused, units)` = the refusal text contains `not enough balance` / `insufficient balance` / `insufficient funds` (case-insensitive), **or** `await client.balance_units() < units` (a failing balance call counts as "not low"). Every write re-reads the order + trade `FOR UPDATE` and re-checks `status == "buying"` and the expected `buy_pending` before changing anything (a reconcile tick may have adopted the trade meanwhile).

- Worker: `Queue(name="orders", channel=ORDERS_CHANNEL, drain=_drain_orders, concurrency=2)` where `_drain_orders(db)` calls `drain_paid(db)` with `trade_client()`.
- Metric outcomes: `bought`, `adopted`, `sold_out`, `low_balance`, `forbidden`, `rate_limited`, `unconfirmed`, `invalid_link`.

- [ ] **Step 1: Tests first** — port the cases of `yupay:apps/api/tests/integration/test_waxpeer_skins_fulfiller.py` (21 tests) onto `attempt_buy` with `fake_trade_client.py`, plus:

```python
async def test_lost_answer_is_resolved_by_lookup_never_rebought(db, buying_order, fake) -> None:
    fake.buy_raises(WaxpeerUnavailableError("timeout"))
    assert await attempt_buy(db, fake, order_id=buying_order.id, settings=S) == "unconfirmed"
    fake.buy_raises(AssertionError("must not buy again"))
    assert await attempt_buy(db, fake, order_id=buying_order.id, settings=S) == "nothing_to_do"
    assert fake.buy_calls == 1                              # Task 9's sweep adopts it by lookup


async def test_redrain_of_a_buying_order_buys_nothing(db, paid_order, fake) -> None:
    fake.lookup_returns([])
    fake.buy_returns(WaxpeerBuy(id=5, price_units=10_000))
    assert await drain_paid(db) == 1
    assert await drain_paid(db) == 0                        # nothing paid left to claim
    assert fake.buy_calls == 1


async def test_forbidden_buy_keeps_order_buying_and_alerts(db, buying_order, fake) -> None:
    fake.lookup_returns([])
    fake.buy_raises(WaxpeerForbiddenError("whitelist", status=403))
    assert await attempt_buy(db, fake, order_id=buying_order.id, settings=S) == "forbidden"
    order, trade = await load(db, buying_order)
    assert order.status == "buying" and order.refunded_at is None
    assert trade.attention_reason == "waxpeer_forbidden" and trade.buy_pending
    assert metric("csmarket_order_buys_total", outcome="forbidden") == 1


async def test_rate_limited_buy_is_retried(db, buying_order, fake) -> None:
    fake.lookup_returns([])
    fake.buy_raises(WaxpeerRateLimitedError("slow", retry_after_seconds=1))
    assert await attempt_buy(db, fake, order_id=buying_order.id, settings=S) == "rate_limited"
    fake.buy_returns(WaxpeerBuy(id=6, price_units=10_000))
    assert await attempt_buy(db, fake, order_id=buying_order.id, settings=S) == "bought"
```

Also: low balance by message and by `balance_units` → `failed` + refund + metric; sold → one substitute ≤ ceiling bought (listing_id/paid cap updated) and a second refusal → `sold_out` refund; a substitute above the ceiling is never bought; a 5xx → unconfirmed, never a substitute; a broken trade link → refund `invalid_trade_link`; two workers draining concurrently claim disjoint orders; an exception inside one order's buy does not stop the drain (the next order is still bought; the poisoned one stays `buying` with `buy_pending`); no log line contains the trade-link token or a Waxpeer URL.

- [ ] **Step 2: Implement** `buying.py` (port the rules of `ym:fulfillment/suppliers/waxpeer_skins.py` 424 LOC onto orders — no `Fulfiller`, no task table, names without `supplier`/`fulfil`), the worker queue, metrics.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_buying.py -q --cov=csmarket.modules.orders.buying --cov-report=term-missing
cd ../worker && uv run pytest -q
cd ../.. && make lint typecheck
git add -A && git commit -m "feat(worker): buy paid orders at Waxpeer — lookup first, one substitute, classified failures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Trade sweeps — reconcile, expiry, protection watch, history audit

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/{trades,sweeps}.py`, `apps/scheduler/src/csmarket_scheduler/jobs/{orders_expiry,trades_reconcile,trades_protection,trades_audit}.py`
- Modify: `modules/orders/api.py`, `apps/scheduler/src/csmarket_scheduler/main.py` (register; import `orders` models), `apps/scheduler/tests/test_main.py` (job list), `core/metrics.py` (`csmarket_trade_attention_total{reason}`), `docs/architecture/metrics.md`
- Test: `apps/api/tests/integration/test_orders_trades.py`, `test_orders_sweeps.py`, `apps/scheduler/tests/test_orders_jobs.py`

**Interfaces:**

- Consumes: Tasks 3, 7, 8.
- Produces:
  - `trades.mirror(trade: SkinTrade, wt: WaxpeerTrade) -> None` — copies `waxpeer_id`, `status`, `trade_id`, `escrow_status`, `send_until`, `release_date` (stamps `accepted_at` the first time it appears), `is_released`, `reason`, `penalties`, `seller` (only non-empty values), `last_polled_at`; never blanks a known value with a null.
  - `trades.pick_trade(trades: list[WaxpeerTrade], waxpeer_id: int | None) -> WaxpeerTrade | None` — by Waxpeer id when known; else the only one; else the only non-6; all 6 → the last; several live → raises `AmbiguousTradeError`.
  - `trades.apply(db, *, order: Order, trade: SkinTrade, wt: WaxpeerTrade) -> str` (caller holds both rows `FOR UPDATE`): mirror, then — status 0/1/2/−1 → nothing; 4 without `release_date` → `buying → trade_sent`; 4 with `release_date` or 5 or `is_released` → `delivered` (from `buying` or `trade_sent`); 6 with `accepted_at` set or non-empty `penalties` → attention `rolled_back` (status unchanged, money spent, R3); 6 otherwise → `refund_to_balance(returned, "not_accepted")`.
  - `sweeps.reconcile(db_factory, client, *, settings) -> int` — every `trades_reconcile_seconds`: due orders (`buying`/`trade_sent`, `next_check_at <= now`, ≤ 100 oldest); `buy_pending` ones go to `attempt_buy`; the rest are looked up in one `check_project_ids` call; each order is applied in its own transaction (lock order → trade, re-check status), `next_check_at = now + 10 s`; an order with no trade and `buy_unconfirmed_at` older than `order_unconfirmed_minutes` → attention `buy_unconfirmed` once (no refund, R3); ambiguous → attention `ambiguous_trade`; a lookup error leaves every row due for the next tick; never raises.
  - `sweeps.expire_pending(db, *, batch: int = 500) -> int` — `pending` orders past `expires_at` with **no `pending` payment attempt** (a kassa holding a transaction is left to its own timeout, as M3 R8) → `cancelled`; their `created` attempts → `cancel_pending`; lock the order `FOR UPDATE SKIP LOCKED` first.
  - `sweeps.watch_protected(db, client) -> int` — `delivered` orders whose trade is status 4 with `release_date` and not released, in batches of 100: mirror; 6 → attention `rolled_back` + metric.
  - `sweeps.audit_recent(db, client, *, days: int = 14) -> int` — settled trades of the last `days` (status 5/6, released, or order `failed`/`returned`) looked up in batches of 100 (any Waxpeer error → return 0, no verdicts); divergences `unknown` (Waxpeer has no record of a trade we saw), `rolled_back` (Waxpeer 6, order delivered and not refunded), `delivered_refunded` (order refunded, Waxpeer 4/5), `ambiguous`; a new verdict sets `audit_verdict` and attention `audit_divergence` + metric **once** per verdict; agreement clears `audit_verdict`.
  - Jobs: `orders.expiry` every 60 s, `first_run_after(220)`; `trades.reconcile` every `trades_reconcile_seconds`, `first_run_after(240)`; `trades.protection` hourly, `first_run_after(280)`; `trades.audit` cron 23:30 UTC (04:30 Tashkent), coalesced. Reconcile/protection/audit are no-ops unless `waxpeer_api_key` or `waxpeer_fake`; every `run()` catches and logs, never raises.

- [ ] **Step 1: Tests first** — port `yupay:apps/api/tests/integration/test_skins_sweeps.py` (17 tests) and the status/lookup half of `test_waxpeer_skins_fulfiller.py` onto `trades`/`sweeps`, plus:

```python
async def test_unconfirmed_after_10_min_needs_attention_no_refund(db, fake, clock, buying_order) -> None:
    await set_trade(db, buying_order, buy_unconfirmed_at=clock.now(), buy_pending=False)
    fake.lookup_returns([])
    clock.advance(minutes=11)
    await reconcile_once(db, fake)
    order, trade = await load(db, buying_order)
    assert trade.attention_reason == "buy_unconfirmed"
    assert order.status == "buying" and order.refunded_at is None


async def test_rollback_after_accept_keeps_money_spent(db, fake, delivered_order) -> None:
    fake.lookup_returns([trade(project_id=delivered_order.id, status=6,
                               penalties={"rollback_fee": 200})])
    await watch_once(db, fake)
    order, trade = await load(db, delivered_order)
    assert order.status == "delivered" and order.refunded_at is None
    assert trade.attention_reason == "rolled_back"


async def test_declined_offer_returns_money_to_the_balance(db, fake, trade_sent_order) -> None:
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=6,
                               reason="Buyer failed to accept")])
    await reconcile_once(db, fake)
    order, _ = await load(db, trade_sent_order)
    assert order.status == "returned" and order.refunded_to == "balance"
```

Also: an unconfirmed buy that Waxpeer did make is adopted by the next lookup (`waxpeer_id` set, no second `buy_one_p2p` — the fake raises if called); 4 without release → `trade_sent`; 4 with release → `delivered` with `accepted_at`; 0→4-accepted in one tick → `delivered` from `buying`; a refused attempt under the same project id is not a rollback (pick by Waxpeer id); ambiguous → attention; expiry cancels an attempt-less or `created`-only order and keeps one a kassa holds; audit verdicts alert once, a changed verdict re-alerts, an unreachable Waxpeer writes nothing; scheduler `test_main.py` lists the four new job ids; each job's `run()` swallows an exception.

- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_trades.py tests/integration/test_orders_sweeps.py -q --cov=csmarket.modules.orders --cov-report=term-missing
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck
git add -A && git commit -m "feat(scheduler): reconcile trades every 10 s, expire unpaid orders, watch protection, audit history

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Ops signals — worker and scheduler metrics, health gauges, alerts

**Files:**

- Create: `apps/worker/src/csmarket_worker/metrics.py`, `apps/scheduler/src/csmarket_scheduler/metrics.py`, `apps/scheduler/src/csmarket_scheduler/jobs/orders_health.py`, `apps/api/src/csmarket/modules/orders/health.py`, `infra/prometheus/alerts/orders.yml`
- Modify: `core/config.py` (`worker_metrics_port: int = 9101`, `scheduler_metrics_port: int = 9102`, `waxpeer_balance_alert_usd: Decimal = Decimal("50")`), `core/metrics.py` (gauges), worker `consumer.run()` and scheduler `main` (start the metrics server), `infra/prometheus/prometheus.yml` (jobs `worker` → `worker:9101`, `scheduler` → `scheduler:9102`), `docker-compose.prod.yml` (no published ports; comment), `.env.example`, `infra/secrets-example/api.env`, `docs/architecture/metrics.md`
- Test: `apps/api/tests/integration/test_orders_health.py`, `apps/worker/tests/test_metrics_server.py`, `apps/scheduler/tests/test_orders_health_job.py`

**Interfaces:**

- Produces:
  - `orders.health.measure(db, client: TradeClient | None, *, settings) -> Health` (frozen: `paid_stuck`, `buying_stuck`, `trade_sent_unpolled`, `attention`, `waxpeer_balance_usd: Decimal | None`) — `paid` orders with `paid_at` older than 5 min; `buying` orders claimed > 30 min ago with no `attention_reason`; `trade_sent` orders whose trade `last_polled_at` is older than 30 min (or null); unresolved attention count; Waxpeer balance via `balance_units()` (any error → `None`, the gauge keeps its last value).
  - Gauges: `csmarket_orders_stuck{state="paid"|"buying"|"trade_sent_unpolled"}`, `csmarket_trades_attention`, `csmarket_waxpeer_balance_usd`, `csmarket_waxpeer_balance_threshold_usd` (= setting). Job `orders.health` every 60 s, `first_run_after(260)`; the balance call only every 5th run.
  - Each of worker and scheduler runs `prometheus_client.start_http_server(port)` once at start-up (never raises the process down when the port is taken — logs and goes on).
  - `infra/prometheus/alerts/orders.yml` (each with a `runbook:` link into `docs/runbooks/orders.md` / `waxpeer.md`, written in Task 17):
    - `OrdersPaidStuck`: `max(csmarket_orders_stuck{state="paid"}) > 0` for 2m, severity `page` (spec §12 "paid orders older than 5 min").
    - `OrdersBuyingStuck`: `max(csmarket_orders_stuck{state="buying"}) > 0` for 5m, `warn`.
    - `TradesUnpolled`: `max(csmarket_orders_stuck{state="trade_sent_unpolled"}) > 0` for 5m, `warn` (spec §12).
    - `TradesNeedAttention`: `max(csmarket_trades_attention) > 0` for 15m, `warn`.
    - `WaxpeerBalanceLow`: `min(csmarket_waxpeer_balance_usd) < min(csmarket_waxpeer_balance_threshold_usd)` for 10m, `page` (spec §12).
    - `WaxpeerForbidden`: `increase(csmarket_order_buys_total{outcome="forbidden"}[10m]) > 0`, `page`.
    - `WaxpeerLowBalanceRefund`: `increase(csmarket_order_refunds_total{reason="waxpeer_low_balance"}[15m]) > 0`, `page`.
    - `TradeAuditDivergence`: `increase(csmarket_trade_attention_total{reason="audit_divergence"}[1d]) > 0`, `warn` (spec §12 "audit divergences").

- [ ] **Step 1: Tests first** — `measure` over seeded orders in each state (and the boundaries: 4 min vs 6 min paid); the job sets every gauge and calls the balance only every 5th run; the metrics server serves `/metrics` text with `csmarket_orders_stuck`; `promtool check rules infra/prometheus/alerts/orders.yml` via `docker run --rm --entrypoint promtool prom/prometheus check rules …` passes.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_health.py -q && cd ../worker && uv run pytest -q && cd ../scheduler && uv run pytest -q
cd ../.. && docker run --rm -v "$PWD/infra/prometheus:/p" --entrypoint promtool prom/prometheus check rules /p/alerts/orders.yml
make lint typecheck
git add -A && git commit -m "feat(infra): order health gauges, worker and scheduler metrics, order and Waxpeer alerts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Dev Waxpeer fake

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/waxpeer_fake.py`, `apps/api/src/csmarket/modules/orders/dev_routes.py` (extend the Task 6 dev router)
- Modify: `skins/waxpeer_trades.py` (`trade_client()` fake branch), `users/routes.py` (`tradelink_checkers()` uses the fake's `check_tradelink`), `skins/routes.py` (listings client), `core/config.py` (validator: `waxpeer_fake` with `is_prod` → error at start-up), `docker-compose.yml` (`CSMARKET_WAXPEER_FAKE: "true"` in dev `x-app-env`), `.env.example`, `docs/architecture/cache-keys.md`
- Test: `apps/api/tests/integration/test_waxpeer_fake.py`, `apps/api/tests/unit/test_config.py` (prod refusal)

**Interfaces:**

- Produces:
  - `FakeTradeClient(redis)` implementing `TradeClient`: `buy_one_p2p` records `skins:waxpeer:fake:trade:{project_id}` (hash, 7-day TTL) with a random `id`, `status=0`, `price` = asked units, `created_at`; a second buy under the same `project_id` adds another trade (as Waxpeer would — so a double buy is visible in tests); `check_project_ids` returns the stored trades, advancing them on read: status 0 → 2 with a fake 10-digit `trade_id` after 3 s → 4 with `send_until = now + 30 min` after 6 s; `balance_units` → `int(redis.get("skins:waxpeer:fake:balance") or 10_000_000)`; `search_listings` raises `WaxpeerUnavailableError` (so `listings_for` serves the seeded snapshot); `check_tradelink` → `None` (works).
  - `trade_client()`, the listings client and the trade-link checker return the fake when `settings.waxpeer_fake`.
  - Dev only (`_dev_gate`, owner only, keyless with the reason in the docstring): `POST /api/v1/dev/orders/{number}/trade` body `{action: "accept"|"decline"|"rollback"}` — `accept` sets `release_date = now + 7 days` on a status-4 trade; `decline` sets status 6, `reason="Buyer failed to accept"`; `rollback` sets status 6 with `penalties={"rollback_fee": …}` after an accept. `POST /api/v1/dev/waxpeer/balance {units}` sets the fake balance.

- [ ] **Step 1: Tests first** — buy then lookup progression with a fake clock; dev route actions drive Task 9's sweep to `delivered` / `returned` / attention `rolled_back`; a second buy under one project id makes the lookup ambiguous (attention, Task 9); `Settings(environment="prod", waxpeer_fake=True)` raises; the dev routes are 404 in prod.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_waxpeer_fake.py tests/unit/test_config.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make lint typecheck
git add -A && git commit -m "feat(api/skins): dev Waxpeer fake and dev trade controls for local buys and e2e

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Admin API — orders, trades, resolve, refund, retry

**Files:**

- Create: `apps/api/src/csmarket/modules/admin/{orders_routes,orders_schemas,orders_service}.py`
- Modify: `modules/orders/buying.py` (`retry_buy`), `modules/admin/{users_service,users_schemas}.py` (card `orders`), `api/v1/router.py`, `tests/unit/test_import_order.py`, `modules/admin/README.md`, `docs/api/openapi.json` + client
- Test: `apps/api/tests/integration/test_admin_orders.py`, `apps/api/tests/integration/test_admin_users.py` (extend)

**Interfaces:**

- Consumes: Task 7 `admin_refund`, `in_flight`; `admin.audit.record`; `admin.filters.text_filter`; `core.cursor`; M3 admin patterns (`users_routes.py`: required `Idempotency-Key`, replay row storing `{request, response}`, change → `audit.record` → `save_replay` → commit).
- Produces (all `require_admin`):
  - `GET /admin/orders?q=&status=&user_id=&cursor=` → `{items: [AdminOrderRow{number, status, name, phase, price_uzs, paid_with, user: {id, display_name}, created_at, attention_reason}], next_cursor}`; `q` = number prefix (upper-cased, escaped, ≤ 8) or part of the item name; keyset `(created_at DESC, id DESC)`; one query (constant query-count test).
  - `GET /admin/orders/{number}` → `AdminOrderDetail{order: {…every `orders`column except`trade_link`—`trade_link_masked` instead…, cost_usd, price_usd, margin_usd (= price_usd − bought or cost), fx_rate}, trade: AdminTradeOut{project_id, waxpeer_id, listing_id, paid_units, bought_units, status, escrow_status, trade_id, offer_url, send_until, release_date, accepted_at, is_released, reason, penalties, seller, buy_pending, buy_unconfirmed_at, attention_reason, audit_verdict, last_polled_at, resolved_at, resolved_by, resolved_note} | null, payments: [{id, provider, status, amount_uzs, created_at}], can_refund: bool, can_retry: bool}`.
  - `GET /admin/trades?view=all|active|attention&q=&cursor=` → `{items: [AdminOrderRow + trade summary {status, state, attention_reason, send_until}], counts: {active, attention}, next_cursor}` — `attention` = unresolved `attention_reason`; `active` = order `buying`/`trade_sent`; counts ignore `q`.
  - `POST /admin/orders/{number}/resolve` body `{note: str (0..500) | null}` + key → detail; sets `resolved_at/by/note` once (idempotent); audit `orders.trade.resolve` `{reason}`.
  - `POST /admin/orders/{number}/refund` (no body) + key → detail; `admin_refund`; audit `orders.refund` `{amount_uzs}`; 409 `order_in_flight` / `already_refunded`.
  - `POST /admin/orders/{number}/retry` (no body) + key → detail; `orders.buying.retry_buy(db, number, admin_id)`: allowed only when the order is `buying`, not refunded, and its trade has a **resolved** `attention_reason` in (`buy_unconfirmed`, `ambiguous_trade`, `waxpeer_forbidden`); clears `attention_reason`, `buy_unconfirmed_at`, `resolved_*`, sets `buy_pending = True`, `next_check_at = now` (the next sweep looks the project id up first, so a buy Waxpeer did make is adopted, never repeated); audit `orders.buy.retry`; else 409 `not_retryable`.
  - `can_refund` / `can_retry` = exactly the conditions above (one function each, used by the detail and the actions; a test pins them equal).
  - Admin user card gains `orders: [AdminOrderRow]` (last 20).

- [ ] **Step 1: Tests first** — list search by number prefix and by name, status filter, paging + constant queries; detail fields (trade link masked, token absent from the response text); views and counts; `test_admin_refund_of_attention_order_needs_resolve` (refund before resolve → 409 `order_in_flight`; after resolve → `failed`, balance credited, one audit row; replayed key → one refund, one audit row); retry clears attention and the next reconcile adopts an existing Waxpeer trade without buying (fake raises on buy); retry of a refunded order → 409; customers → 403; unknown number → 404.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_admin_orders.py tests/integration/test_admin_users.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/admin): orders and trades — search, attention queue, resolve, refund, retry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Storefront — buy panel on the item page

**Files:**

- Create: `apps/web/src/lib/{orders,order-key,prefer-balance}.ts` (+ tests), `apps/web/src/components/skins/{SkinBuyPanel,PaymentPicker}.tsx` (+ tests)
- Modify: `apps/web/src/components/skins/{SkinOffers,SkinListings,SkinPriceBlock}.tsx` (a selected offer in the offers context; «Выбрать» on each listing; drop the "No buy button in M2" notes), `app/[locale]/item/[slug]/page.tsx` (render the panel when `detail.buy_enabled`), `components/balance/TopupForm.tsx` (use the shared `PaymentPicker` tiles), `packages/i18n/locales/{ru,uz,en}/web.json` (+ `web.buy`)
- Test: `lib/orders.test.ts`, `lib/order-key.test.ts`, `lib/prefer-balance.test.ts`, `components/skins/SkinBuyPanel.test.tsx`, `components/skins/PaymentPicker.test.tsx`

**Interfaces:**

- Consumes: Tasks 4, 6 routes; `useAuth()` (`user.trade_link`, `trade_link_verdict`, `trade_link_reason`), `POST /me/trade-link/check`, `lib/balance.ts` (`getBalance`, `getProviders`, `BALANCE_KEY`), `lib/kassa-redirect.ts`, `lib/trade-link.ts` (`verdictMessage`).
- Produces:
  - `lib/orders.ts`: types `OrderOut`, `SkinTradeOut`, `OrderStatus`, `OrdersPage`, `PayProvider = "wallet"|"click"|"payme"|"uzum"|"mock"`; `createOrder(body: {slug, listing_id, price_uzs}, key: string): Promise<OrderOut>`; `payOrder(number, body: {provider, locale}, key): Promise<{order: OrderOut, intent_url: string | null}>`; `getOrder(number)`, `listOrders(cursor?)`, `devPayOrder(number)`, `devTrade(number, action)`; typed errors `PriceChangedError(priceUzs)`, `OfferGoneError(nextOffer | null)`, `TradeLinkError(code, reason)`, `BalanceTooLowError`, `OrderNotPayableError(reason)`, `BuyingDisabledError` (mapped from the 409 `code`s; anything else → generic).
  - `lib/order-key.ts`: `orderKeyFor(current: OrderKey | null, listingId: number, tradeLink: string, mint: () => string): OrderKey` — one key per (offer, trade link) pair, kept across retries (port of YuPay's `orderKeyFor`).
  - `lib/prefer-balance.ts`: `preferBalance(current, {ready, picked, fallback}): string` and `usePreferBalance(...)` (port, 40 LOC + test): balance is pre-selected when it covers the price; a method the buyer picked by hand is never switched.
  - `SkinBuyPanel({slug, locale})` (client): selected offer + its price; signed out → «Войдите через Steam, чтобы купить» (sign-in link); no trade link → «Добавьте трейд-ссылку» + link to `/account`; unchecked verdict → runs the advisory check once on mount; `bad` → the verdict message and a disabled button; `PaymentPicker` (balance tile with «Не хватает {amount}» + «Пополнить» link when short; kassa tiles from `getProviders`; «Тестовая оплата» for `mock`); submit = `createOrder` with `orderKeyFor` → `payOrder` with a fresh key → wallet: `router.push(/orders/{number})`; kassa: `router.push(/orders/{number}?go=1)` (the order page opens the kassa once, Task 14). Errors: price changed → show the new price, keep the offer, ask to confirm; offer gone → select `next_offer` (or the cheapest left) with «Этот лот уже купили. Следующий — {price}»; none left → «Предложения закончились»; a replayed order that is no longer `pending` → one retry with a freshly minted key. One submit in flight at a time.
  - Copy `web.buy` (ru; uz/en in the same commit): `title` «Купить», `offer` «Лот», `choose` «Выбрать», `selected` «Выбран», `pay` «Купить за {price}», `signIn` «Войдите через Steam, чтобы купить», `needLink` «Добавьте трейд-ссылку, чтобы купить», `addLink` «Добавить ссылку», `checkingLink` «Проверяем трейд-ссылку…», `methodTitle` «Способ оплаты», `balance` «Баланс», `balanceShort` «Не хватает {amount}», `topUp` «Пополнить», `methodTest` «Тестовая оплата», `methodNone` «Оплата сейчас недоступна.», `priceChanged` «Цена изменилась: теперь {price}», `offerGone` «Этот лот уже купили. Следующий — {price}», `noneLeft` «Предложения закончились», `failed` «Не получилось оформить заказ. Попробуйте ещё раз.», `howItWorks` «После оплаты продавец отправит обмен в Steam. Примите его — скин ваш.»

- [ ] **Step 1: Tests first** — `orderKeyFor` stable per (offer, link), new when either changes; `preferBalance` 4 cases; panel: signed-out / no link / bad link states; balance pre-selected when it covers, not when short; submit calls `createOrder` with a ≥ 16-char key then `payOrder`, navigates per provider; a double click sends one `createOrder`; price-changed and offer-gone flows; a 409 replay of a non-pending order retries once with a new key; no raw API text is ever rendered.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/item): buy panel — offer, trade link check, balance or kassa

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Storefront — order page and «Мои заказы»

**Files:**

- Create: `apps/web/src/app/[locale]/orders/[number]/page.tsx`, `apps/web/src/app/[locale]/account/orders/page.tsx`, `apps/web/src/components/order/{OrderView,SkinTradeCard,OrderPay}.tsx` (+ tests), `apps/web/src/components/account/OrdersList.tsx` (+ test), `apps/web/src/lib/order-poll.ts` (+ test)
- Modify: `components/account/AccountView.tsx` (link «Мои заказы»), `lib/paths.ts` (`orderPath`), `packages/i18n/locales/{ru,uz,en}/web.json` (+ `web.orders`), `e2e/global-setup.ts` (warm the two routes)
- Test: as listed

**Interfaces:**

- Consumes: Task 13 `lib/orders.ts`; `lib/kassa-redirect.ts` (`shouldAutoOpen`, `markOpened`, `searchWithoutGo`); `PaymentPicker`.
- Produces:
  - `/orders/[number]` (Server Component shell, `robots: noindex`, `generateMetadata` with the route locale, **no `loading.tsx`**) → client `OrderView({number})`: `data-testid="order-status"` with `data-state={status}`; a header «Заказ #{number}», the item (image, name, phase), the price; per status:
    - `pending` + payable: `OrderPay` (method picker + «Оплатить {price}»; a kassa intent opens once with `?go=1` — reuse `kassa-redirect.ts`; mock → «Оплатить (тест)» calling `devPayOrder`); not payable → «Время на оплату вышло.»
    - `paid`/`buying`/`trade_sent`/`delivered`/`failed`/`returned`: `SkinTradeCard` (port of `yupay:apps/web/src/components/order/SkinTradeCard.tsx`, 140 LOC, with csmarket copy and `/account/balance` instead of the wallet page; a minute tick re-renders «Примите до HH:MM» while `offer_sent`).
    - `cancelled`: «Заказ отменён.»
    - 404 → «Заказ не найден.»; signed out → sign-in link.
  - `lib/order-poll.ts`: `orderPollInterval(status, failures): number | false` — 8 s base, ×2 per failure up to ×8, jitter ×(1..2), cap 60 s; `false` for terminal statuses (`delivered`, `cancelled`, `failed`, `returned`). (The WebSocket in M4b only adds a nudge; polling stays the reconciler — YuPay's 2026-08-31 zombie-socket lesson.)
  - `/account/orders` → `OrdersList` (cards: image, name, status, price, date; «Показать ещё» by cursor; empty «Заказов пока нет.» + «В каталог»).
  - Copy `web.orders` (ru; uz/en in the same commit): `title` «Мои заказы», `empty` «Заказов пока нет.», `toCatalog` «В каталог», `more` «Показать ещё», `number` «Заказ #{number}», `notFound` «Заказ не найден.», `cancelled` «Заказ отменён.», `expired` «Время на оплату вышло.», `payNow` «Оплатить {price}», `payTest` «Оплатить (тест)», `status.{pending «Ждёт оплаты», paid «Оплачен», buying «Покупаем», trade_sent «Обмен отправлен», delivered «Получен», cancelled «Отменён», failed «Не получилось», returned «Обмен не состоялся»}`, `trade.{title «Обмен в Steam», buying «Покупаем скин — обмен придёт в Steam через минуту.», offer_sent «Обмен отправлен — примите его в Steam.», acceptBy «Примите до {time}», openOffer «Открыть обмен в Steam», seller «Продавец», accepted «Получено», protectedUntil «Steam защищает обмен до {date}», refunded «Обмен не состоялся — деньги вернулись на баланс.», tryLater «Не получилось купить скин — деньги на балансе. Попробуйте через несколько минут.», support «Мы проверяем покупку. Статус обновится на этой странице.», toBalance «Открыть баланс»}`. Never promise a refund unless `trade.refunded_to` says so.

- [ ] **Step 1: Tests first** — `orderPollInterval` table; `SkinTradeCard` every state (port its 8 tests, drop the card-refund case; add the minute tick and the `support` no-promise case); `OrderView`: pending pays (kassa opens once with `?go=1`, mock calls `devPayOrder`), expired, each trade state, 404, signed out; polling stops on a terminal status (fake timers); `OrdersList` paging and empty state.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/orders): order page with the Steam trade card, my orders list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Admin SPA — Orders and Trades

**Files:**

- Create: `apps/admin/src/features/orders/{api.ts, OrdersPage.tsx, OrderDetail.tsx, TradeBlock.tsx, OrderActions.tsx, labels.ts}` (+ `OrdersPage.test.tsx`, `OrderDetail.test.tsx`), `apps/admin/src/features/trades/{api.ts, TradesPage.tsx}` (+ test)
- Modify: `apps/admin/src/app/router.tsx` (`/orders`, `/orders/:number`, `/trades`), `app/Layout.tsx` (nav «Заказы», «Обмены»), `features/users/UserCard.tsx` (orders block linking to `/orders/:number`), `features/payments/PaymentDetail.tsx` (order block link)

**Interfaces:**

- Consumes: Task 12 routes; M3 admin patterns (`useIdempotencyKey`, `errorText`/`CODE_MESSAGES`, `lib/format.ts`, `lib/url-guards.ts`, `useUrlParams`).
- Produces:
  - Orders page: search «Номер заказа или название», status filter, table (номер, скин, цена, оплата, статус chip, пользователь → `/users/:id`, создан, «внимание» badge), «Показать ещё».
  - Order detail: order fields (cost, price, margin, курс), payments list, `TradeBlock` (статус Waxpeer, trade id + Steam link, отправить до, принят, защита до, продавец, причина, штрафы, `project_id` and Waxpeer id with copy buttons), `OrderActions`: «Разобрано» (note ≤ 500), «Вернуть деньги на баланс» (shown when `can_refund`; confirm «Вернуть {amount} на баланс покупателя?»), «Повторить покупку» (shown when `can_retry`; confirm warns «Сначала проверьте project id в кабинете Waxpeer — повтор купит скин, если покупки там нет»). Each action sends one `Idempotency-Key` per confirmed submission; 409 codes in Russian (`order_in_flight` «Скин ещё в пути — вернуть деньги нельзя.», `already_refunded` «Деньги уже на балансе.», `not_retryable` «Повтор сейчас невозможен.»).
  - Trades page: tabs «Все» / «В пути» / «Требуют внимания» with counts; rows open the order detail; attention rows tinted.
  - Status chip words: pending «ждёт оплаты», paid «оплачен», buying «покупаем», trade_sent «обмен отправлен», delivered «получен», cancelled «отменён», failed «не получилось», returned «обмен не состоялся»; attention reasons: buy_unconfirmed «ответ Waxpeer потерян», ambiguous_trade «несколько обменов», rolled_back «откат после получения», waxpeer_forbidden «Waxpeer: IP не в белом списке», audit_divergence «расхождение со сверкой».

- [ ] **Step 1: Tests first** — search passes `q` from the URL; detail renders the trade block and never a trade-link token; refund shown only when `can_refund`, confirm then one request; retry warning text; resolve with note; 409 messages in Russian; tabs request the right view and show counts.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/orders): orders, trades attention queue, resolve, refund and retry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: e2e — buy from the balance, buy through the test kassa, a declined trade

**Files:**

- Create: `e2e/tests/buy.spec.ts`, `e2e/tests/admin-orders.spec.ts`
- Modify: `e2e/tests/helpers.ts` (`saveTradeLink(request, page, steamId)`, `topUp(page, amount)` through the dev mock kassa, `devTrade(request, number, action)`), `e2e/playwright.config.ts` (anchored `testMatch` for both specs), `e2e/README.md`

**Interfaces:**

- Consumes: dev stack with `make migrate && make seed-skins`, `CSMARKET_WAXPEER_FAKE=true`, `CSMARKET_SKINS_BUY_ENABLED=true` (dev compose defaults from Tasks 2, 11), Tasks 13–15 UI, `[data-testid="order-status"][data-state=…]`.

- [ ] **Step 1: Specs** (unique Steam IDs per test with a new prefix; never mutate shared seed state; at most 2 top-ups and 3 orders per run to stay under the `topup-create` / `order-create` buckets):
  1. **Buy from the balance → delivered:** sign in, save a fake trade link, top up 300 000 soʻm through the test kassa, open a seeded item, keep the cheapest offer, «Баланс» is pre-selected, buy → order page `buying` → `trade_sent` (the fake sends after ~6 s; the reconcile sweep runs every 10 s) → `devTrade(accept)` → `delivered` («Получено»); the balance shows a «Покупка» entry with the order number.
  2. **Buy through the test kassa:** with an empty balance, pick «Тестовая оплата», buy → order page `pending` → «Оплатить (тест)» → `buying`.
  3. **Declined trade → money back:** buy from the balance → `trade_sent` → `devTrade(decline)` → «Обмен не состоялся — деньги вернулись на баланс.»; the balance is back to its value before the purchase and shows «Возврат на баланс».
  4. **Admin:** an admin finds the order from spec 1 by its number on «Заказы», opens it, sees the trade block (Waxpeer status 4, Steam offer link), and «Обмены» lists it under «Все».
- [ ] **Step 2: Run against the dev stack** — `docker compose up -d --build`, `docker compose exec api alembic upgrade head`, `make seed-skins`, readiness waits, `make test-e2e` twice (all M1–M4a specs), `docker compose down` (no `-v`). Never touch other containers. A real app bug found here is reported, not papered over in the spec.
- [ ] **Step 3: Commit**

```bash
npx prettier --check . && pnpm --filter @csmarket/e2e lint && pnpm --filter @csmarket/e2e typecheck
git add -A && git commit -m "test(e2e): buy from the balance and through the test kassa, declined trade refunds, admin orders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: Docs, ADR-0007, runbooks; full verification

**Files:**

- Create: `docs/decisions/0007-orders-buying-trades.md`, `docs/runbooks/{orders,waxpeer}.md`, `docs/product/flows/buy.md`, `docs/architecture/sequence-diagrams/{checkout,buy,trade-reconcile}.mmd`
- Modify: `apps/api/src/csmarket/modules/{orders,payments,skins,wallet,admin}/README.md` (finish), `docs/architecture/{module-map,metrics,cache-keys}.md`, `docs/api/README.md`, `docs/security/pii-handling.md`, `AGENTS.md` (§0 M4 row → split M4a/M4b with this plan's path; status; §4 nothing new unless a pattern emerged; §11 carve-out landed in Task 4 — verify), `docs/architecture/overview.md`

- [ ] **Step 1: Write the docs**
  - **ADR-0007** (template `docs/decisions/0000-template.md`): context (spec §15 M4, owner decisions D1–D4); decision = rulings R1–R15, one short paragraph each, plus the refinements the execution ledger records; consequences (one purchase per order by lookup-first; unknown outcomes need a human; refunds only to the balance; kassas cannot reverse orders; the checkout carve-out); alternatives (YuPay's task table; refunding unknown outcomes automatically; a 2–3 min reconcile; an app-level Telegram alert bot); dependencies added (expect none — `prometheus_client` is already a dependency; state it).
  - **runbooks/orders.md:** the order lifecycle in plain words; each alert (`#orders-paid-stuck`, `#orders-buying-stuck`, `#trades-unpolled`, `#trades-attention`, `#waxpeer-low-balance-refund`, `#audit-divergence`) — what it means, what to check (admin «Обмены» → the order → its trade block → the Waxpeer dashboard by `project_id`), what to do; each attention reason and the safe action («Разобрано» first; refund only when Waxpeer shows nothing bought; retry only after checking `project_id`); never credit by hand — use admin adjust with a reason.
  - **runbooks/waxpeer.md:** the key and its IP whitelist (the VPS IP; the owner's local IP for local work — the key lives only in `.env` / `secrets/api.env`, never in chat or the repo), `#forbidden` (403 → orders stay `buying`; fix the whitelist; the sweep retries by itself), topping up the Waxpeer balance and `#balance-low`, **the fake (`CSMARKET_WAXPEER_FAKE`) vs the real key locally — with the real key and the fake off, a local buy is a real purchase with real money**, the M5 test buys (one declined, one accepted) and the `my-history` probe still owed (M4b).
  - **flows/buy.md** + `checkout.mmd`, `buy.mmd`, `trade-reconcile.mmd`: item page → `POST /orders` → `POST /orders/{number}/pay` (balance / kassa → callback → settle) → `NOTIFY` → worker claim → lookup → buy → sweep → `trade_sent` → accept → `delivered`; decline → `returned` + refund; unknown → attention.
  - **module-map, metrics** (every new counter and gauge), **cache-keys** (`skins:waxpeer:fake:*`, `order-create`/`order-pay` ip_guard buckets), **api/README** (orders endpoints, idempotency, limits, error codes), **pii-handling** (the order's `trade_link` snapshot — stored, never logged, masked in admin; seller data is public Steam profile data; `for_steamid64` is dropped at parse).
  - **AGENTS.md:** §0 milestone table: M4 → «M4a orders & buying: `docs/superpowers/plans/2026-10-01-m4a-orders-buying.md`; M4b WS, email, pricing editor, dashboard: not written yet»; status line "M0–M3 merged on local main; M4a on branch `m4a-orders-buying` until the owner says to merge; the first real sale waits for the deploy (Waxpeer key on the VPS IP)".
- [ ] **Step 2: Full gate**

```bash
git status --porcelain
make lint typecheck test
cd apps/api && uv run pytest --cov=csmarket.modules.orders --cov=csmarket.modules.payments --cov=csmarket.modules.wallet --cov=csmarket.modules.skins --cov-report=term -q -n auto && cd ../..
cd apps/api && uv run python -m csmarket.scripts.export_openapi /tmp/o.json && cd ../.. && diff -q /tmp/o.json docs/api/openapi.json
docker compose build && docker compose up -d && docker compose exec api alembic upgrade head && make seed-skins
make test-e2e && docker compose down
git status --porcelain
```

Expected: all green; `orders`, `payments`, `wallet`, `skins` ≥ 95 % each (report the numbers; below is a finding — add tests); no OpenAPI drift.

- [ ] **Step 3: Commit**

```bash
npx prettier --check .
git add -A && git commit -m "docs: ADR-0007 orders, buying and trades; orders and Waxpeer runbooks; buy flow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

**Spec coverage (§15 M4 split per owner D1; M4a = "first real sale end to end"):** `orders` tables/FSM (§5) → T2; order number (§6) → T2/T4 (`order_number`, existing); trade-hold refused (§7.2, D2) → T1; checkout re-price, ±2 %, substitution ≤ +3 %, floor, fx snapshot, 15 min, one skin (§7.4) → T4; payment from balance / kassa, NOTIFY, prefer-balance (§7.5) → T5, T6, T13; worker buy, drift guard, lookup-first, substitute once, low balance refund + alert (§7.6) → T8; reconcile, protection watch, history audit, expiry (§7.7) → T9; refund to balance + money guards (§7.8) → T7, T12; Waxpeer facts (§8: whitelist, envelope, status axis, acceptance = `release_date`, penalties) → T3, T8, T9; storefront buy panel, `/account/orders`, `/orders/[number]` with the trade card (§10) → T13, T14; admin Orders / Trades (§10) → T12, T15; alerts (§12: paid > 5 min, trade_sent unpolled > 30 min, Waxpeer balance, audit divergences) → T10; idempotency + rate limits (§13) → T4, T6, T12; tests incl. respx contracts, hypothesis ledger, e2e buy from balance / via mocked kassa / refund on `returned` (§14) → T3, T6, T16. **Moved to M4b by D1:** WS (`realtime`), email (`notifications`, Resend), admin pricing editor + preview + per-item override, dashboard (sales, margin, Waxpeer balance tile), `my-history` orphan probe, email verification. Pricing itself (§9) shipped in M2.

**Placeholder scan:** no TBD/TODO; port steps name every YuPay source and the tests to bring; the new rules (FSM, choose/substitute, buy classification, apply mapping) are written out.

**Type consistency:** `Order`/`SkinTrade` columns (T2) are the names T4–T12 use (`cost_units`, `paid_units`, `bought_units`, `attention_reason`, `buy_pending`, `buy_unconfirmed_at`, `resolved_*`, `next_check_at`); `TradeClient` methods (T3) = the calls in T8/T9/T10/T11; `refund_to_balance(order=…, to_status=…, reason=…, actor=…)` (T7) = T8/T9/T12 calls; `credit_order_refund(…, paid_with=…)` (T6) = T7; `mark_paid(db, order, provider=…)` (T5) = T6; `ReversalRefusedError` (T5) caught by Payme/Uzum; `ORDERS_CHANNEL` (T2) = the worker queue (T8) and `mark_paid` (T5); `OrderOut`/`SkinTradeOut` (T4) = `lib/orders.ts` (T13/T14); admin shapes (T12) = SPA (T15); scheduler first runs 220/240/260/280 + a cron (T9/T10) avoid 20/60/120/140/160/180/200/300.

**Review Focus → tests:** 1 → T6 `test_wallet_pay_twice_debits_once`, `test_concurrent_wallet_pay_one_payment`; T8 `test_lost_answer_is_resolved_by_lookup_never_rebought`, `test_redrain_of_a_buying_order_buys_nothing`; T7 `test_refund_twice_credits_once`. 2 → T9 `test_unconfirmed_after_10_min_needs_attention_no_refund`, `test_rollback_after_accept_keeps_money_spent`; T7 `test_refund_refused_while_in_flight`; T12 `test_admin_refund_of_attention_order_needs_resolve`. 3 → T8 `test_forbidden_buy_keeps_order_buying_and_alerts`, `test_rate_limited_buy_is_retried`. 4 → T4 `test_price_moved_beyond_tolerance_is_409`, `test_gone_offer_substituted_within_ceiling`, `test_trade_hold_link_is_refused`. 5 → T5 `test_payme_cancel_of_performed_order_is_31007`, `test_expired_order_is_not_payable`; T6 `test_pay_after_expiry_is_409`.
