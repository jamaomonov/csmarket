# 0007. Orders, buying at Waxpeer and Steam trades (M4a)

- **Status**: Accepted
- **Date**: 2026-10-02
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | data | security | observability | frontend

## Context and problem statement

M4 (spec §15) is the first real sale: a buyer picks an offer, pays in soʻm from the balance or
through Click / Payme / Uzum, the worker buys the listing at Waxpeer, Waxpeer's seller sends
the skin to the buyer's trade link, and a failed or declined trade is refunded to the
balance. It builds on M2's catalogue and live listings and on M3's ledger, payments and
kassas.

The owner took four decisions while planning (2026-10-01):

- **D1.** M4 is split. **M4a** is the sale end to end with a polling order page; **M4b**
  brings the WebSocket, email (Resend), the pricing editor and the dashboard.
- **D2.** A trade link with a Steam trade hold is **refused** (verdict `bad`), as in YuPay.
- **D3.** The email provider is Resend (M4b).
- **D4.** The owner may give a Waxpeer key whitelisted for their local IP. It goes into the
  owner's local `.env` by the owner — never into chat, the repo or a file an agent writes.

Planning settled fifteen rulings (R1–R15); execution refined them in lettered rulings (A–X).
This ADR records both so M4b and M5 build on them.

## Decision drivers

- **One order, one purchase, one refund**, whatever double clicks, replays, kassa retries,
  worker re-drains, lost Waxpeer answers or sweep races arrive.
- **A skin that may have been delivered is never refunded automatically**, and nothing is
  refunded while a skin is in flight.
- **A Waxpeer misconfiguration (403, 429) does not refund the shop as "sold out".**
- **The buyer pays the price they saw**, within published tolerances.
- No lock and no DB session held across a Waxpeer call; logs never tie a person to money or
  carry a trade link or the key.
- Port YuPay's proven skin purchase (ADR-0002) by allow-list, keeping what its production
  incidents taught and dropping its task table and Telegram alerting.

## Considered options

1. **YuPay's model**: a generic fulfilment task table drives the buy; alerts go to Telegram
   from the app.
2. **The order is the queue** (`orders` rows claimed with `FOR UPDATE SKIP LOCKED`), one
   `skin_trades` row per order mirroring Waxpeer, lookup-first buying, sweeps in the
   scheduler, ops signals through Prometheus (chosen).

## Decision outcome

**Chosen option:** 2, as the rulings below.

### Rulings taken while planning

- **R1 — Order FSM** (`orders.fsm.move`, the only writer of `orders.status`): `pending →
paid | cancelled`; `paid → buying`; `buying → trade_sent | delivered | failed | returned`;
  `trade_sent → delivered | returned`; `delivered`, `cancelled`, `failed`, `returned` are
  terminal. `buying → delivered | returned` exists because one reconcile tick can see Waxpeer
  jump past "sent". `failed` and `returned` always come with the refund in the same
  transaction.
- **R2 — `skin_trades` carries YuPay's load-bearing columns** (`listing_id`, `waxpeer_id`,
  `paid_units`, `bought_units`, `accepted_at`, `seller` jsonb, `buy_pending`,
  `buy_unconfirmed_at`, `attention_reason`, `audit_verdict`, `resolved_*`) beyond spec §5.
  `escrow_status` is stored as received. "Needs attention" is derived:
  `attention_reason IS NOT NULL AND resolved_at IS NULL`.
- **R3 — Unknown and spent outcomes never auto-refund.** A lost buy answer still unseen after
  10 min (`buy_unconfirmed`), an ambiguous lookup (`ambiguous_trade`), a status 6 after
  acceptance or with penalties (`rolled_back`) set an attention; the order keeps its status;
  an alert fires; an admin decides. The buyer reads «Мы проверяем покупку», never a refund
  promise.
- **R4 — Substitution.** At checkout a gone offer is replaced by the cheapest `auto` offer of
  the item priced ≤ shown × 1.03, billed at the lower of its price and the shown one; none →
  409 `offer_gone` with the next offer. In the worker a buy refused on price or because the
  listing sold is retried **once** with the cheapest other `auto` listing ≤ `paid_units` ×
  1.03; Waxpeer's `new_price` is never accepted blindly.
- **R5 — Reconcile every 10 s** (spec: 2–3 min): the buyer has ~30 min to accept and the
  order page rides this sweep; one lookup covers ≤ 100 orders, so ≤ 6 calls a minute.
  Protection watch hourly (spec: daily); history audit daily at 04:30 Tashkent over 14 days
  by `check-many-project-id` (spec: `my-history`, whose shape was never captured — the
  orphan-buy probe moves to M4b).
- **R6 — Buy errors are classified.** A 200 refusal (sold, `new_price`) → substitute once,
  then `failed` + refund `sold_out`; a refusal naming low balance, or any refusal while
  `GET /v1/user` shows less than the price → `failed` + refund `waxpeer_low_balance` + alert;
  HTTP 403 → no substitute, no refund, the order stays `buying`, attention
  `waxpeer_forbidden` + alert; 429 → retried; network / 5xx / unreadable → unconfirmed,
  resolved by lookup.
- **R7 — A kassa can never reverse an order payment.** The skin is bought at payment and
  refunds go to the balance: Payme Cancel of a performed order → −31007, Uzum `/reverse` →
  10017, Click has no reversal. `ReversalRefusedError` is the base class; M3's
  `TopupSpentError` and the new `OrderReversalRefusedError` subclass it.
- **R8 — Pay from the balance** (`provider="wallet"`): one transaction locks the order, then
  the wallet, books `purchase` (C `user_wallet` / D `house_payments_received`, key
  `purchase:order:{id}`), writes a `succeeded` payments row, moves the order to `paid` and
  sends `NOTIFY orders`. A short balance is 409 `balance_too_low` and writes nothing. No
  mixed payment.
- **R9 — Refund legs.** Balance-paid: D `user_wallet` / C `house_payments_received`;
  kassa-paid: D `user_wallet` / C `provider_clearing:<kassa>` (the kassa's money becomes
  balance, as a top-up). Key `refund:order:{id}`; the payment row stays `succeeded`.
- **R10 — Trade-link gate at checkout:** no link → 409 `trade_link_missing`; a stored `bad`
  verdict → 409 `trade_link_bad` with `reason` (`invalid | private | trade_ban | hold`); an
  unchecked or `unavailable` verdict passes (the check is advisory; the panel runs it first).
- **R11 — Checkout re-prices from the cached listings read** (90 s fresh / 1 h stale,
  budgeted, 4 s timeout, breaker): a third synchronous-Waxpeer carve-out on the money path
  (AGENTS §11, `ApiHighLatency` / `ApiWaxpeerLatency` regexes). A degraded (snapshot) answer
  is accepted: the worker's price cap is the money guard. No DB session is held across it.
- **R12 — `skins_buy_enabled`** (default off; dev compose on; prod at launch) gates the buy
  panel and `POST /orders` (409 `buying_disabled`).
- **R13 — Dev Waxpeer fake** (`CSMARKET_WAXPEER_FAKE`, refused at startup in prod): trades in
  Redis, the offer "sent" 6 s after the buy, dev routes to accept / decline / roll back and
  to set the balance. With a real key and the fake off a local buy is a real purchase.
- **R14 — Ops signals through Prometheus**, not an app Telegram bot: the worker and the
  scheduler expose `/metrics` (9101 / 9102, not published); a scheduler job sets order-health
  gauges every minute; Alertmanager sends to Telegram.
- **R15 — Not in M4a (M4b):** WebSocket pushes, email, pricing editor and preview, per-item
  overrides, dashboard, `my-history` orphan detection, email verification.

### Rulings refined during execution

- **Import direction (A, E).** `orders.api` never re-exports a module that imports
  `payments`; `orders.paying` is not exported and the expiry sweep imports
  `payments.cancel_pending` inside the function. `payments.models` imports `orders.models`
  once to register the FK target. A cold-import test pins it.
- **The key stays with the owner (B, D4).** Agents never ask for it, write it or need it;
  tests use respx recordings and the fake.
- **Legacy `warn` = `bad` (C).** A stored pre-change hold verdict (`warn`) is refused at
  checkout like `bad`/`hold`.
- **Schema details (D, migration 0014).** `orders.slug` is 255 chars like `skin_items.slug`;
  `payments.order_id` is indexed (`ix_payments_order`).
- **An unreadable answer is never "absent" (F).** A lookup entry without an id or
  `project_id`, a lookup without a `trades` list, a buy success without an id → unavailable
  (resolved by lookup), never "nothing bought". More than 100 ids raises instead of
  truncating. A cancelled call is re-raised uncounted.
- **The buyer sees `support` for any open attention (G),** whatever the trade state; the
  order page still shows an open offer with its link and deadline (X).
- **A kassa-paid order books no ledger entry at settle (H);** its refund credits
  `provider_clearing` like a top-up. Sale revenue is not in the ledger in M4a.
- **Refund codes (I, L).** `refund_to_balance` is the one refund path; it refuses (409
  `order_needs_attention`) while the trade has an open `buy_unconfirmed`, `ambiguous_trade`,
  `rolled_back` or `audit_divergence` — R3 is a property of the path, not of each caller.
  `waxpeer_forbidden` does not block (nothing was bought). Admin refund codes:
  `already_refunded`, `order_in_flight`, `order_not_refundable`, `order_busy`.
- **A rollback after delivery is never refunded by the app (J, P).** A spent 6 on a
  `buying` / `trade_sent` order first moves it to `delivered`, then flags `rolled_back`;
  goodwill goes through an audited admin adjustment.
- **Lock order order → trade (K)** for every writer of `skin_trades`; with M3's order:
  order → kassa row → payment → user wallet. Kassa timeout sweeps lock the owner
  `SKIP LOCKED` per row.
- **The buy lease (M).** `attempt_buy` takes the lease first — one committed `UPDATE …
next_check_at = now + 5 min WHERE buying AND buy_pending AND due` — then reads. The worker
  and the reconcile sweep both buy only through it. Its release is owner-checked, with a
  backoff (60 s after a 403, 20 s after a 429); an attempt is bounded by lease − 30 s; once
  the buy is **sent**, no exit releases the order without a durable outcome (recorded as
  unconfirmed in a fresh session, or the lease is kept to lapse). A buy that lands on rows
  another writer moved is `stale_bought` → `ambiguous_trade`.
- **Ambiguity (N, Q, R).** Several live trades before a buy → `ambiguous_trade`, nothing
  bought. A status 6 is conclusive only when it is **our** trade (its id is the stored
  `waxpeer_id`); a 6-only answer is never adopted and never resolves a lost buy. Finding our
  trade clears an open `buy_unconfirmed`; `ambiguous_trade` stays for a human. A new
  attention clears an earlier resolution; a settled buy clears `waxpeer_forbidden`.
- **Admin actions.** «Разобрано» (resolve) is audited and idempotent; refund and retry need a
  resolved `buy_unconfirmed` / `ambiguous_trade` / `waxpeer_forbidden` on a `buying` order
  and no running attempt (`order_busy`, which also covers the 403/429 backoff). Refund turns
  `buy_pending` off under the lock before booking. Retry is refused once a purchase is on
  record (`waxpeer_id`) — it would buy twice; refund is refused then too (`order_in_flight`)
  unless our own trade is a conclusive 6 — the skin may still arrive.
- **The admin refund asks Waxpeer first (Y; closes the accepted risk U).** Before it books,
  `admin_refund` reads the order unlocked, ends the transaction, and looks its `project_id`
  up (`check-many-project-id`, 4 s); any trade under it that is live (status ≠ 6) or was ever
  accepted (`release_date`, penalties, released) refuses the refund (`order_in_flight`); a
  lookup that fails or times out refuses it too (`waxpeer_unavailable`, nothing booked). Then
  it locks the order and its trade and re-checks, as every buy write does. This is a fourth
  synchronous-Waxpeer carve-out, the first on an admin route (AGENTS §11, the
  `ApiHighLatency` / `ApiWaxpeerLatency` regexes): a refund is the one place the system
  could hand out both the skin and the money, and a human reading a runbook row was its
  only guard. U — a refund of a resolved `waxpeer_forbidden` order after a dead attempt
  (sent, unrecorded, lease lapsed) — is now caught by the same lookup. The nightly audit's
  `delivered_refunded` fires for any refunded order whose trade is not a 6 (not only 4/5).
- **Scheduler (O).** First runs 220 s (expiry), 240 s (reconcile), 260 s (health), 280 s
  (protection); the history audit is a pure cron (23:30 UTC), so a deploy never re-runs it.
- **Signals (S).** `WorkerDown` / `SchedulerDown` (`up == 0`), `WaxpeerBalanceUnknown` (never
  read / stale read), `OrdersHealthStale`; every gauge alert pins `job="scheduler"`; counters
  are pre-created at 0 so the first event after a restart is an `increase()`.
- **The price sync is not faked (T):** with a key set it keeps the real read-only client.
- **Storefront (V, W).** Replay of a create key returns the stored order (200; a new order is
  201). A replayed order that is no longer pending is retried with a fresh key only when it
  expired; a paid one goes to its order page (a fresh key would buy twice). A `cancelled`
  order never paid reads «Время на оплату вышло.». The kassa opens once from
  `/orders/{n}?go=1&via=<kassa>`, only while payable and within 8 s; the page never trusts a
  pay answer's snapshot and re-reads `GET /orders/{n}`.

**Dependencies added in M4a:** none. `prometheus_client` was already a dependency of
`csmarket`; the worker and scheduler get it through it.

### Positive consequences

- **One purchase per order by lookup-first:** `project_id` = the order id, every buy is
  preceded by a lookup, a lost answer is resolved by lookup, and the lease keeps the worker
  and the sweep from buying in parallel. One ledger debit (`purchase:order:{id}`), one
  refund (`refund:order:{id}`).
- A Waxpeer 403 or 429 keeps orders in flight and pages, instead of refunding everyone.
- Refunds are a single path with the R3 guard inside it; buyers are never promised money
  that is not theirs yet.
- Ops see stuck, unpolled and attention orders and the Waxpeer balance in Prometheus, with a
  runbook anchor per alert.

### Negative consequences

- **Unknown outcomes need a human** (attention queue), and a resolved ambiguous order can
  sit in `buying` until Waxpeer settles its trades.
- **Refunds only to the balance;** a buyer who wants a card refund is handled by the owner in
  the kassa's cabinet plus a clawback adjustment.
- **Kassas cannot reverse orders** (−31007 / 10017); a disputed card payment is settled by
  hand.
- **The checkout carve-out:** a synchronous (cached, budgeted) Waxpeer read on `POST /orders`.
- **The admin refund carve-out:** one synchronous lookup (4 s) per refund; while Waxpeer is
  down or rate-limits us an operator cannot refund (409 `waxpeer_unavailable`) — the money
  waits, the skin is never given twice.
- The buyer polls (8 s) until M4b's WebSocket; e2e must start ≥ 4 min after the stack (the
  reconcile's first run).
- Orphan buys (a Waxpeer purchase with no order) are not detected until the M4b probe.

## Validation

- Locally: `make lint typecheck test`; `orders`, `payments`, `wallet`, `skins` ≥ 95 %
  coverage; no OpenAPI drift; promtool rule tests (`infra/prometheus/tests/orders_test.yml`);
  hypothesis keeps `SUM(D) = SUM(C)` over top-ups, purchases and refunds; e2e on the dev stack
  with the fake (balance buy → delivered, test kassa, decline → refund, admin orders).
- The Review Focus tests: `test_wallet_pay_twice_debits_once`,
  `test_concurrent_wallet_pay_one_payment`, `test_lost_answer_is_resolved_by_lookup_never_rebought`,
  `test_redrain_of_a_buying_order_buys_nothing`, `test_refund_twice_credits_once`,
  `test_unconfirmed_after_10_min_needs_attention_no_refund`,
  `test_rollback_after_accept_keeps_money_spent`, `test_refund_refused_while_in_flight`,
  `test_admin_refund_of_attention_order_needs_resolve`,
  `test_admin_refund_refused_while_a_purchase_is_on_record`,
  `test_admin_refund_asks_waxpeer_first`,
  `test_forbidden_buy_keeps_order_buying_and_alerts`, `test_rate_limited_buy_is_retried`,
  `test_price_moved_beyond_tolerance_is_409`, `test_gone_offer_substituted_within_ceiling`,
  `test_trade_hold_link_is_refused`, `test_payme_cancel_of_performed_order_is_31007`,
  `test_expired_order_is_not_payable`, `test_pay_after_expiry_is_409`.
- After the deploy (M5): two test buys with the real key (one declined → refunded, one
  accepted → delivered), `docs/runbooks/waxpeer.md`.

## Alternatives considered (detail)

### YuPay's fulfilment task table

A generic task row per order line, with its own statuses, retried by a fulfilment worker.
csmarket sells one thing, so a second state machine beside the order's only duplicates it;
the order row is the queue (`FOR UPDATE SKIP LOCKED` + `NOTIFY orders`) and `skin_trades`
carries the trade. Rejected.

### Refunding unknown outcomes automatically

Simpler for the buyer: a lost answer or an ambiguous lookup refunds after a timeout. But the
skin may already be on its way — Waxpeer cannot recall a paid offer — so a refund then hands
over both the skin and the money. Rejected (R3); the attention queue costs an operator a few
minutes per case.

### A 2–3 minute reconcile (spec §7.7)

Fewer Waxpeer calls, but the buyer has about 30 minutes to accept and the order page shows
«Обмен отправлен» only after a tick; 10 s with ≤ 100 orders a call stays far under Waxpeer's
limits. Rejected (R5).

### An app-level Telegram alert bot

YuPay sent alerts from the app. That needs a bot token, dedupe and rate-limiting in app
code, and goes silent when the process dies. Prometheus already scrapes us and Alertmanager
already routes to Telegram, with `up == 0` covering a dead process. Rejected (R14).

## References

- Spec §5, §7.2–§7.8, §8, §10, §12–§15; plan
  `docs/superpowers/plans/2026-10-01-m4a-orders-buying.md`
- [ADR-0002](./0002-port-from-yupay-by-allowlist.md), [ADR-0005](./0005-skins-catalogue-fx-and-indexing.md),
  [ADR-0006](./0006-wallet-payments-topups.md)
- Runbooks: [`orders.md`](../runbooks/orders.md), [`waxpeer.md`](../runbooks/waxpeer.md),
  [`wallet.md`](../runbooks/wallet.md); flow: [`buy.md`](../product/flows/buy.md); diagrams:
  `docs/architecture/sequence-diagrams/{checkout,buy,trade-reconcile}.mmd`
- Module READMEs: `apps/api/src/csmarket/modules/{orders,payments,wallet,skins,admin}/README.md`
- Alerts: `infra/prometheus/alerts/orders.yml`; metrics: `docs/architecture/metrics.md`
