# orders

One skin bought by one customer, from checkout to the Steam trade (spec §5, §7; M4a plan
rulings R1–R15; ADR-0007). Builds on `payments`, `wallet`, `skins`, `users` and `fx`; `payments`
reaches this module only through `orders.api`, and `wallet` imports neither.

**Owns:** tables `orders` and `skin_trades` (migration `0013_orders_skin_trades`, which also
adds `payments.order_id → orders.id` and `ck_payments_purpose_order`).

- `orders` — the purchase and the worker's queue: `number` (8 Crockford chars, unique),
  `user_id`, `status`, the item (`skin_item_id`, `market_hash_name`, `phase`, `slug`), the
  offer (`listing_id`, after any checkout substitution) and its cost (`cost_units` — Waxpeer
  units, 1000 = $1, the worker's price cap — `cost_usd`), the price billed (`price_usd`,
  `price_uzs` in whole soʻm, `fx_snapshot_id`), the `trade_link` snapshot (PII, never
  logged), `idempotency_key` (unique per user), `paid_with` (`wallet` | `click` | `payme` |
  `uzum` | `mock`), the times (`expires_at`, `paid_at`, `delivered_at`, `cancelled_at`,
  `failed_at`, `refunded_at`), `refunded_to` (`balance` only), `failure_reason`
  (`FAILURE_REASONS`), and the queue claim (`claimed_at`, `claimed_by`, `next_check_at`).
- `skin_trades` — one per order, keyed by `order_id` (`ON DELETE CASCADE`): `project_id`
  (= the order id; unique — a buy is looked up by it, never repeated), Waxpeer's
  `waxpeer_id`, `listing_id`, `paid_units` (the cap) and `bought_units`, Waxpeer's `status`
  (`NULL` = never reached Waxpeer), `escrow_status` as received, Steam's `trade_id`,
  `send_until`, `release_date`, `is_released`, `accepted_at`, `reason`, `penalties`,
  `seller` (public name, avatar, level, since), the buy flags (`buy_pending`,
  `buy_unconfirmed_at`), attention (`attention_reason` in `ATTENTION_REASONS`; an order needs
  an admin while it is set and `resolved_at` is not), `audit_verdict`, `last_polled_at`, and
  the admin's resolution (`resolved_at`, `resolved_by`, `resolved_note`).

**Interface (`api.py`):** `Order`, `SkinTrade`, `ORDER_STATUSES`, `IN_FLIGHT`, `TERMINAL`,
`ATTENTION_REASONS`, `FAILURE_REASONS`, `TRANSITIONS`, `InvalidOrderTransitionError`,
`move`, `ORDERS_CHANNEL` (`NOTIFY orders` wakes the worker), the response shapes `OrderOut`,
`OrderStatusOut`, `SkinTradeOut` and `order_out`, `skin_trade_out`, `effective_status`,
`is_expired`, `mark_paid`, `trade_state`, and the refunds (`refund_to_balance`, `in_flight`,
`ADMIN_REFUNDABLE`, `BLOCKS_REFUND`, `RefundStatus`), the admin actions (`admin_refund`,
`resolve_attention`, `retry_buy`, `can_refund`, `can_retry`, `buy_running`, `lock_order`,
`RETRYABLE`, `CONFLICTS`), the buy (`drain_paid`, `attempt_buy`), and the trade sweeps (`reconcile`, `expire_pending`,
`watch_protected`, `audit_recent`; the scheduler's jobs import `orders.sweeps` directly). `api.py` never imports `payments`
(`test_orders_api_never_imports_payments`: a cold `import csmarket.modules.orders.api`
leaves `csmarket.modules.payments` out of `sys.modules`).

**Paid (`paid.py`):** `mark_paid(db, order, *, provider)` — `move(order, "paid")`,
`paid_with = provider`, then `SELECT pg_notify('orders', <number>)` in the caller's
transaction (delivered on commit). The caller holds the order `FOR UPDATE`;
`payments.hooks.settle` calls it for a kassa (once per order: a non-`pending` order is
`AlreadyPaidError` there), the balance pay (R8) for `wallet`. A kassa can never reverse an
order (`payments.OrderReversalRefusedError`, R7); kassa attempts are found by
`payments.order_id` (`ix_payments_order`).

**Routes (`routes.py`):** `POST /orders` (checkout), `POST /orders/{number}/pay`,
`GET /orders/{number}`, `GET /me/orders` — contract in `docs/api/README.md`.
`dev_routes.py`: `POST /dev/orders/{number}/pay` and, with the dev Waxpeer fake on,
`POST /dev/orders/{number}/trade` (dev only, below).

## Checkout (`checkout.py`, rulings R4, R10–R12)

`create_order` in this order: a replayed `Idempotency-Key` returns the stored order whatever
the body; `skins_buy_enabled` off → 409 `buying_disabled`; the trade-link gate (no link →
`trade_link_missing`; a stored verdict `bad` — or the legacy `warn` of a trade hold — →
`trade_link_bad` with `reason`; unchecked or `unavailable` passes); the item (404 when
unknown or hidden), the pricing rules and a fresh soʻm rate (503 `rate_unavailable`).
Those scalars are copied out and the read transaction ends **before** the listings read
(`skins.listings.listings_for` with the shared `search_client` — cached 90 s, budgeted,
breaker-guarded; a degraded answer is accepted). Every live offer is priced with the item
page's `quote` + `to_uzs`; then:

- the chosen offer is listed → billed at the server price if within
  ±`order_price_tolerance` (2 %) of the shown price, else 409 `price_changed` (+ new
  `price_uzs`);
- it is gone → the cheapest offer priced ≤ shown × (1 + `order_substitute_ceiling`, 3 %)
  replaces it, billed at the lower of its price and the shown one (`price_usd` = shown /
  rate, 6 places, when the shown price is billed); none → 409 `offer_gone` with the next
  offer or `null`.

The order is inserted `pending`, expiring after `order_expiry_minutes` (15), with the offer
(`listing_id`, `cost_units`, `cost_usd`), the price, `fx_snapshot_id` and the trade-link
snapshot. Two first requests racing on one key: the unique `(user_id, idempotency_key)`
refuses the second, which returns the first's order. The route charges the `order-create`
ip_guard bucket (60/min per IP, 10/min per IP + account) before any work.

## Paying (`paying.py`, ruling R8)

`pay_order(db, *, user_id, number, provider, locale, idempotency_key) -> OrderPayOut` serves
`POST /orders/{number}/pay` and commits. It locks the order (`payments.resolve(lock=True)`;
another user's, a top-up's, unknown or malformed number → 404), then looks the key up in the
replay store (scope `orders.pay:{number}`, the row keeps `{request: {provider, locale},
response}`): the same body replays the stored answer, another body is 409
`idempotency_mismatch`. Looked up under the order lock, so a double-click's second request
waits for the first and replays it. Then an order that is not payable is 409
`order_not_payable` with `reason` `paid` or `expired` (also a cancelled order), and:

- **`wallet`** — one transaction: `wallet.debit_purchase` (locks the wallet; 409
  `balance_too_low` writes nothing), a `payments` row `purpose="order"`,
  `provider="wallet"`, `provider_ref="wallet:<number>"` moved `created → succeeded`,
  `mark_paid(provider="wallet")` (`NOTIFY orders`), the replay row, commit. No mixed payment.
- **a kassa** (`click`, `payme`, `uzum`, `mock`; 422 `order_provider` unless available
  here) — `payments.ensure_attempt` opens or reuses the order's live attempt in that kassa
  and the answer carries the kassa's `intent_url`; the order stays `pending` until the kassa
  settles it. The replay row, commit.

Lock order: order → (kassa row) → payment → user wallet. Log line `orders.paid` (number,
provider, amount; never the user). `paying.py` imports `payments`, so `orders.api` never
exports it (ruling A).

**Dev only:** `dev_pay(db, *, user_id, number)` behind `POST /dev/orders/{number}/pay` (404
unless dev login is active — `api.v1.deps.dev_gate`; not in the schema; keyless because a
repeat is a no-op): order lock → `ensure_attempt("mock")` → `mark_pending` →
`settle(event_id="mock:<attempt id>")` → commit; an expired order is 409
`order_not_payable`.

**Dev only, with the fake (`CSMARKET_WAXPEER_FAKE`):** `POST /dev/orders/{number}/trade
{action: accept|decline|rollback}` reads the owner's order (`get_owned`, 404 otherwise),
ends the transaction, and calls `skins.api.FakeTradeClient.act(order.id, action,
waxpeer_id=<the stored one>)`. Nothing in `orders` changes there: the reconcile tick reads the
trade like Waxpeer's — `accept` → `delivered`, `decline` → `returned` and refunded,
`rollback` after an accept → the protection watch flags `rolled_back`. `trade_client()`
returns the fake under the flag, so the worker's buys and every sweep run against it.

## Reads (`service.py`, `trade_view.py`)

`get_owned` (owner only; malformed or top-up-shaped numbers are "not found"),
`list_for_user` (20 a page, keyset on `created_at DESC, id DESC`, cancelled and expired
unpaid orders hidden; orders, item images and trades in **one** query) and `order_out`. A
`pending` order past `expires_at` reads `cancelled` (not payable) before the expiry sweep
writes it. `skin_trade_out(order, trade)` maps the trade to the buyer's five states
(`buying`, `offer_sent`, `accepted`, `released`, `failed`) and a `reason_code` (a refund
`invalid_trade_link` reads `trade_link`: the buyer fixes the link in their profile); any
unresolved attention (`ATTENTION_REASONS`, R3) reads `support` whatever the state (never a
bare failure, never a refund promise); `refunded_to` only when the order records a refund.

## Status machine (`fsm.py`, ruling R1)

`move(order, to)` is the only place an order's status changes; an illegal edge raises
`InvalidOrderTransitionError` (409) and leaves the row untouched. Every move stamps
`updated_at`.

| From                                           | To                                              | Also stamps                                        |
| ---------------------------------------------- | ----------------------------------------------- | -------------------------------------------------- |
| `pending`                                      | `paid`, `cancelled`                             | `paid_at` / `cancelled_at`                         |
| `paid`                                         | `buying`                                        | —                                                  |
| `buying`                                       | `trade_sent`, `delivered`, `failed`, `returned` | `delivered_at` / `failed_at` (also for `returned`) |
| `trade_sent`                                   | `delivered`, `returned`                         | `delivered_at` / `failed_at`                       |
| `delivered`, `cancelled`, `failed`, `returned` | none (terminal)                                 | —                                                  |

`IN_FLIGHT` = `paid`, `buying`, `trade_sent`: the money is ours and the skin is on its way,
so nothing refunds. `buying → delivered | returned` exists because one reconcile tick can see
Waxpeer jump past "sent". `failed` and `returned` come with the refund to the balance in the
same transaction; an unknown or spent outcome (R3) never reaches them automatically — it
sets `skin_trades.attention_reason` and waits for an admin.

## Refunds (`refunds.py`, spec §7.8, rulings R3, R9)

Refunds go to the balance only, once per order. `refunds.py` imports `wallet` and this
module's models and FSM — never `payments`.

- `refund_to_balance(db, *, order, to_status, reason, actor) -> bool` — the one refund path
  (the worker, the reconcile sweep, the admin). The caller holds the order `FOR UPDATE`.
  `refunded_at` already set → `False`, nothing written. Else `wallet.credit_order_refund`
  (key `refund:order:{order_id}`; balance-paid: D `user_wallet` / C
  `house_payments_received`; kassa-paid: D `user_wallet` / C `provider_clearing:<kassa>`),
  `move(order, to_status)` (`failed` | `returned`), `refunded_at`, `refunded_to="balance"`,
  `failure_reason = reason`, `csmarket_order_refunds_total{reason}` + 1, log
  `orders.refunded` (number, amount, reason, status — never the buyer) → `True`. Flushes,
  never commits. A `to_status` or `reason` outside its set is a `ValueError` (caller bug);
  an order with no `paid_with` is 409 `order_not_paid`; an order whose trade has an
  unresolved `buy_unconfirmed`, `ambiguous_trade`, `rolled_back` or `audit_divergence`
  (`BLOCKS_REFUND`, R3: unknown or spent outcome) is 409 `order_needs_attention`, nothing
  written — `waxpeer_forbidden` does not block (nothing was bought), and a resolved
  attention no longer blocks; the trade is read under the caller's order lock; an FSM edge that does not exist
  raises `InvalidOrderTransitionError` before anything is booked. The payment row stays
  `succeeded` (the money stays with us, now as balance).
- `in_flight(order, trade) -> bool` — `paid`, `buying`, `trade_sent`, and a `delivered`
  order whose trade has an unresolved `attention_reason` (e.g. `rolled_back`): the skin may
  be on its way or already with the buyer, so nothing refunds.
- The admin's refund (`admin_refund`) lives in `admin_actions.py` (below) and books
  through `refund_to_balance`.

## Admin actions (`admin_actions.py`, rulings R3, K, M)

What `/admin/orders/{number}/…` does (`admin.orders_routes` audits each and commits). Every
action locks the order, then its trade (`lock_order`, ruling K), re-checks under the locks
and flushes — never commits. Unknown, malformed or `T…` number → `NotFoundError`.

- `refund_refusal(order, trade, at)` / `retry_refusal(order, trade, at)` → the 409 code or
  `None`; `can_refund(order, trade, at=None)` / `can_retry(…)` are `… is None` — the admin
  page's flags and the actions run the same rule.
- `buy_running(order, trade, at)` — `buy_pending` and `next_check_at > at`: a buy attempt may
  hold the lease (`buy_lease.take_lease`), so a buy may be on the wire (or a 403/429 backoff
  of ≤ 60 s is running) → 409 `order_busy`. While Waxpeer keeps answering 403, refund/retry
  of a `waxpeer_forbidden` order answer `order_busy` during each 60 s backoff: fix the IP
  whitelist first — the sweep then buys by itself.
- `admin_refund(db, *, number, admin_id, client) -> Order` — only a `buying`, unrefunded
  order whose trade carries a **resolved** attention in `ADMIN_REFUNDABLE`
  (`buy_unconfirmed`, `ambiguous_trade`, `waxpeer_forbidden`: an operator checked Waxpeer,
  nothing was bought), no purchase on record that is not our own failed trade (`waxpeer_id`
  set and status ≠ 6 → `order_in_flight`, the same guard as the retry) and no running
  attempt. **Lookup first** (ADR-0007 Y): an unlocked read refuses early and ends the
  transaction; `client.check_project_ids([order.id])` is asked with nothing locked
  (`REFUND_LOOKUP_SECONDS` = 4 s; the route's client is `skins.request_trade_client`, the
  fake under `waxpeer_fake`); a trade under the `project_id` that is live (status ≠ 6) or
  was ever accepted (`release_date`, penalties, released) → `order_in_flight`; a lookup
  error or timeout → `waxpeer_unavailable`. Then it locks order → trade, re-checks, turns
  `buy_pending` off under the lock (a racing `take_lease` waits on the order row and then
  finds the order `failed`), and `refund_to_balance` books it (`failed`, reason `admin`,
  actor `admin:<id>`). 409, in this order: `already_refunded`; `order_in_flight`
  (`in_flight`, an unresolved or "something may be bought" attention, a purchase on record
  or at Waxpeer); `order_not_refundable` (unpaid, cancelled, delivered); `order_busy`;
  `waxpeer_unavailable`.
- `retry_buy(db, *, number, admin_id) -> str` — a `buying`, unrefunded order whose trade
  carries a **resolved** attention in `RETRYABLE` (the same three), no purchase on record
  (`waxpeer_id` unset — `sweeps` also flags a bought trade that stopped being reported
  `ambiguous_trade`, and a retry would buy it twice) and no running attempt:
  clears `attention_reason`, `buy_unconfirmed_at` and `resolved_*`, sets `buy_pending`,
  `next_check_at = now`. The reconcile sweep's next `attempt_buy` looks the `project_id` up
  first, so a purchase Waxpeer did make is adopted, never repeated. Returns the cleared
  reason (audited). 409 `not_retryable`, `order_busy`.
- `resolve_attention(db, *, number, admin_id, note) -> str | None` — stamps `resolved_at`,
  `resolved_by` (admin id), `resolved_note` once; returns the reason, or `None` when it was
  already resolved (nothing written). 409 `nothing_to_resolve` without a trade or an
  attention. A sweep that flags the trade again clears `resolved_*` (`trades.flag`).
- `CONFLICTS` — every 409 code above → its `detail`.

## Buying (`buying.py`, `buy_lease.py`, `buy_writes.py`, `buy_rules.py`, `trades.py`, rulings R3, R4, R6, K)

The worker's `orders` queue (`apps/worker`, two drainers) buys each paid order at Waxpeer,
at most once: `skin_trades.project_id` = the order id, every buy is preceded by a
`check-many-project-id` lookup, and a lost answer is resolved by lookup, never by buying
again. Flow: `docs/architecture/sequence-diagrams/buy.mmd`.

- `drain_paid(db, *, client=None, settings=None, limit=10) -> int` — the queue's drain:
  claims up to `limit` `paid` orders by `paid_at` (`FOR UPDATE SKIP LOCKED`), moves them to
  `buying`, stamps `claimed_at`, `claimed_by` (`hostname:pid`) and `next_check_at = now`,
  opens their trade (`listing_id`, `paid_units = cost_units`, `buy_pending`), commits, then
  runs `attempt_buy` per order. An exception in one order is rolled back and logged
  (`orders.buy.crashed`, the type only); the order stays `buying` with `buy_pending` and the
  reconcile sweep retries it once its lease lapses. Builds the purchase client
  (`skins.api.trade_client`) only when it claimed something. Returns the number claimed.
- `attempt_buy(db, client, *, order_id, settings) -> str` — the one buy path (the worker and
  the reconcile sweep for a `buy_pending` trade). It takes the order's **lease first**: one
  `UPDATE … SET next_check_at = now + 5 min WHERE status = 'buying' AND <its trade is
buy_pending> AND next_check_at <= now RETURNING next_check_at` — and only then reads the
  snapshot (`nothing_to_do`, lease released, unless still `buying` with a buy pending). A
  second attempt (the sweep racing the worker) finds the lease held, or the buy no longer
  pending, so it can never act on a `buy_pending` it read before the first attempt settled
  the buy. The release (`next_check_at = now`; `now + 60 s` after `forbidden`, `now + 20 s`
  after `rate_limited` and `lookup_later`, or a 429's own `retry_after` when longer, capped
  at `MAX_RETRY_AFTER` = the lease — `RELEASE_BACKOFF` bounds the lookups a 403/429 storm or
  an outage causes) is
  owner-checked (`WHERE next_check_at =
<this attempt's lease>`); an attempt is bounded by `ATTEMPT_BUDGET` (lease − 30 s), so it
  never outlives its lease — a timeout after the buy was sent is `unconfirmed` (or
  `unrecorded` when even that mark cannot be written: the lease lapses), before it
  `lookup_later`. A lease left by a dead process lapses by itself. Outcomes:

  | Case                                                        | Outcome         | Writes                                                                  |
  | ----------------------------------------------------------- | --------------- | ----------------------------------------------------------------------- |
  | trade link does not parse                                   | `invalid_link`  | `failed` + refund `invalid_trade_link`                                  |
  | lookup: 429, unavailable, a refusal                         | `lookup_later`  | nothing (`buy_pending` kept; no buy without a lookup); due in 20 s      |
  | lookup or buy: HTTP 403                                     | `forbidden`     | attention `waxpeer_forbidden` (once), `buy_pending` kept                |
  | lookup finds our trade (`orders.trades.pick_trade`)         | `adopted`       | `mirror`, `bought_units`, `buy_pending = false` — never rebought        |
  | lookup finds only failed (6) trades, none accepted          | (buys)          | never adopted: refused attempts, nothing live was bought — buy as usual |
  | a lost answer on record (`buy_unconfirmed_at`), any lookup  | `nothing_to_do` | `buy_pending = false`; reconcile's unconfirmed rule decides (R3); belt  |
  | … one of them accepted, released or with penalties          | `ambiguous`     | attention `ambiguous_trade`, `buy_pending = false`; nothing bought      |
  | lookup finds several live trades                            | `ambiguous`     | attention `ambiguous_trade`, `buy_pending = false` (no refund)          |
  | buy accepted                                                | `bought`        | `listing_id`, `paid_units`, `waxpeer_id`, `bought_units`, `status = 0`  |
  | buy: 429                                                    | `rate_limited`  | nothing (`buy_pending` kept, next tick)                                 |
  | buy: unavailable / unreadable / 5xx                         | `unconfirmed`   | `buy_unconfirmed_at`, `buy_pending = false` (R3 after 10 min)           |
  | buy refused, the message names the trade link               | `invalid_link`  | `failed` + refund `invalid_trade_link` (no substitute)                  |
  | buy refused, low balance (words, or `GET /v1/user` < units) | `low_balance`   | `failed` + refund `waxpeer_low_balance`                                 |
  | buy refused (sold, price moved, a 4xx), no substitute       | `sold_out`      | `failed` + refund `sold_out`                                            |
  | a buy accepted or lost, but the rows moved during the call  | `stale_bought`  | attention `ambiguous_trade` (the purchase on record: `adopted`)         |

  A refusal that names neither the trade link nor low balance is retried **once** with the cheapest other `auto`
  listing of the item at most `paid_units × (1 + order_substitute_ceiling)` units, read
  through `skins.listings_for` (cached, budgeted; Waxpeer's spelling, phase included);
  Waxpeer's `new_price` is never accepted. A failing balance call reads as "not low". A buy
  or adoption ends a `waxpeer_forbidden` attention (cleared with its resolution: the access
  question is moot, and an admin refund must not see a "nothing bought" order that bought).
  Once a buy request has been **sent** in an attempt, no exit that failed to record its
  outcome frees the order: a timeout, a shutdown's `CancelledError` or any unexpected error —
  in the buy call or in the write after it (a lock wait, a slow database) — rolls the
  attempt's session back and records the buy as unconfirmed in a **fresh session**
  (`buy_lease.secure` → `buy_writes.secure_sent`; on an order that left `buying` it also
  flags `ambiguous_trade`); when even that write fails the lease is **kept**, so it lapses
  after 5 min as a dead attempt's and no one buys again within it. The attempt's budget is
  counted from before the lease is taken. `bought_units` falls back to the units offered when Waxpeer
  answers `price: 0`. A 403 on an order whose `waxpeer_forbidden` attention was resolved
  re-opens it (resolution cleared): an admin refund must not see a still-forbidden order as
  settled.
  `csmarket_order_buys_total{outcome}` counts every outcome but `lookup_later` and
  `nothing_to_do`; the log line `orders.buy` carries the order number and the outcome only.

- **Writes** (`buy_writes.py`): each locks the order, then the trade (ruling K), re-checks
  `status == "buying"` and `buy_pending`, writes and commits; when a sweep moved the rows
  during the Waxpeer call it writes nothing (`orders.buy.stale`, outcome `nothing_to_do`) —
  except after a buy that may have gone through: then the trade gets `ambiguous_trade`
  (which blocks any automatic refund), an error `orders.buy.stale_purchase` (number only) is
  logged and the outcome is `stale_bought`. An attention is set once per open attention; a
  new or re-opened one always clears an earlier resolution. `buy_rules.py` holds the low
  balance test and the substitute pick.
  No lock or transaction is held across a Waxpeer call.
- `trades.mirror(trade, wt)` copies a lookup onto the row without ever blanking a known
  value (`accepted_at` stamped the first time a `release_date` appears; `is_released` never
  goes back); `trades.pick_trade(trades, waxpeer_id)` picks ours by Waxpeer's id, else the
  only one, else the only live one, else (all failed) the last — several live ones raise
  `AmbiguousTradeError`. `trades.flag` and `trades.apply` are below.

## Trade sweeps (`sweeps.py`, `expiry.py`, `trade_audit.py`, `sweep_base.py`, `trades.py`, rulings R3, R5, K, M)

Timed by the scheduler (`apps/scheduler/src/csmarket_scheduler/jobs/`, which import
`orders.sweeps`: it re-exports `expire_pending` from `expiry.py` and `audit_recent` from
`trade_audit.py`); the logic is here, `sweep_base.py` holds the shared locked re-read and
chunked lookup.
Flow: `docs/architecture/sequence-diagrams/trade-reconcile.mmd`. Every write locks the order,
then its trade, re-checks, writes and commits in its own transaction; no lock or
transaction is held across a Waxpeer call, and lookups ask at most 100 ids
(`skins.api.LOOKUP_MAX_IDS`).

| Job (id)            | When                                           | Function                                     |
| ------------------- | ---------------------------------------------- | -------------------------------------------- |
| `orders.expiry`     | every 60 s, first run 220 s after start        | `expire_pending(db, *, batch=500)`           |
| `trades.reconcile`  | every `trades_reconcile_seconds` (10 s), 240 s | `reconcile(db_factory, client, *, settings)` |
| `trades.protection` | hourly, first run 280 s after start            | `watch_protected(db, client)`                |
| `trades.audit`      | cron 23:30 UTC (04:30 Tashkent), coalesced     | `audit_recent(db, client, *, days=14)`       |
| `orders.health`     | every 60 s, first run 260 s after start        | `health.measure(db, client, *, settings)`    |

The three trade jobs do nothing without `waxpeer_api_key` (or `waxpeer_fake`); every job's
`run()` logs and swallows any failure.

- `reconcile` — the ≤ 100 oldest due orders (`buying` / `trade_sent`, `next_check_at` null
  or `<= now`). Those whose buy is no longer pending are looked up in one call; each is then
  locked (order → trade), re-checked (still followed, not `buy_pending`, still due), moved
  by `trades.apply` and given `next_check_at = now + trades_reconcile_seconds`. Ours is
  picked by `trades.ours`: **a 6 is conclusive only when it is our trade** (its id is the
  stored `waxpeer_id`); a 6 picked without a known id may be a refused attempt under the
  same `project_id` while our lost buy went through, so it counts as unseen — never mirrored,
  its id never pinned. Unseen: a buy whose answer was lost (`buy_unconfirmed_at`) waits
  `order_unconfirmed_minutes` (10), then gets the attention `buy_unconfirmed` — never a
  refund (R3); a trade whose Waxpeer id we know but Waxpeer stops reporting (not seen for
  10 min since `last_polled_at`) gets `ambiguous_trade` once. Our trade found (live, or by
  its known id) answers an open `buy_unconfirmed` (cleared, ruling Q); `ambiguous_trade`
  stays for a human. Several live trades and no Waxpeer id: attention `ambiguous_trade`. A
  trade
  still `buy_pending` goes to `attempt_buy` (after the poll), whose lease is the only writer
  of its `next_check_at` (ruling M). A failed lookup writes nothing: every row stays due.
  One order's failure is rolled back and logged (type only); the sweep never raises.
- `trades.apply(db, *, order, trade, wt)` — `mirror`, then:

  | Waxpeer reports                                                                            | Order                                                                                           |
  | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
  | 0, 1, 2, −1 (−1 never overwrites a known status)                                           | unchanged                                                                                       |
  | 4 without `release_date` (the offer is out)                                                | `buying → trade_sent`                                                                           |
  | 4 with `release_date` (accepted), 5, or `is_released`                                      | `buying` / `trade_sent → delivered`                                                             |
  | 6 on a `delivered` order, or after acceptance (`accepted_at`), released, or with penalties | `buying` / `trade_sent → delivered` (ruling P), then attention `rolled_back` — money spent (R3) |
  | 6 otherwise (our trade, declined or expired)                                               | `returned` + refund `not_accepted`                                                              |

  A refund an open attention blocks (`refund_to_balance` → `order_needs_attention`) leaves the
  order as it is (`held`, warned once — when the 6 is first seen): an admin resolves
  first, and the next tick refunds.

- `trades.flag(trade, reason, *, reopen=False) -> bool` — opens an attention unless one is
  open (an open `waxpeer_forbidden` gives way); a new attention clears any earlier
  resolution and counts `csmarket_trade_attention_total{reason}` once. A resolved attention
  with the same reason stays resolved (the sweeps see the same state every tick) unless
  `reopen` — the buy re-opens `waxpeer_forbidden` on a new 403.
- `expire_pending` — `pending` orders past `expires_at` with no `pending` (or `succeeded`)
  payment attempt, locked `FOR UPDATE SKIP LOCKED`, attempts re-read under the lock: their
  `created` attempts → `payments.cancel_pending` (imported inside the function: `payments`
  imports `orders.api`), the order → `cancelled`. A kassa-held attempt keeps its order
  (M3 R8); its kassa's timeout sweep releases it and a later tick expires the order. Flushes;
  the job commits.
- `watch_protected` — `delivered` orders whose trade is 4 with `release_date`, not released,
  in batches of 100: `apply` (5 → released; 6 → attention `rolled_back`, the order stays
  `delivered`, nothing refunded). Several live trades: logged, nothing mirrored. A lookup
  failure ends the run.
- `audit_recent` — trades of the last `days` that we consider settled (status 5 or 6,
  released, or the order `failed` / `returned`), all looked up first (any Waxpeer error →
  0, nothing written). Verdicts: `unknown` (Waxpeer has no record of a trade we saw —
  `status` not null), `rolled_back` (Waxpeer 6, the order `delivered`, not refunded, our row
  not already 6), `delivered_refunded` (refunded, Waxpeer 4/5), `ambiguous`. A changed
  verdict is stored in `audit_verdict`; a new one opens (or re-opens) `audit_divergence`
  when no graver attention is open and counts the metric **once per verdict**; agreement
  clears `audit_verdict` (the attention waits for an admin). The audit changes no other
  trade or order state.

## Health (`health.py`, ruling R14)

`measure(db, client, *, settings) -> Health` is read-only: `paid` orders with `paid_at` older
than 5 min, `buying` orders claimed over 30 min ago with no **open** attention (a resolved one
does not hide an order), `trade_sent` orders whose trade was last polled over 30 min ago (or
never), the count of unresolved attentions, and Waxpeer's balance in USD (`balance_units() /
1000`; `None` without a client or on any error). The scheduler's `orders.health` job sets the
`csmarket_orders_stuck{state}`, `csmarket_trades_attention` and `csmarket_waxpeer_balance_*`
gauges from it and reads the balance on every 5th tick (the first included). The alerts are in
`infra/prometheus/alerts/orders.yml`; the gauges in `docs/architecture/metrics.md`.

## Nudges and letters (`letters.py`, M4b rulings R4, R5)

Every buyer-visible status change calls `realtime.api.nudge` in its own transaction (paid,
claimed, trade sent / delivered / rolled back, refunded, expired) — delivered on commit. Three
events also enqueue a letter through `notifications.api.enqueue` in the same transaction:
`mark_paid` → `receipt`, `trades.apply` → `trade_sent` (with the offer's `send_until`; none
when an order jumps straight to `delivered`), `refund_to_balance` → `refunded` (with the
amount; none when held or replayed). The payload snapshots the number and the skin; one
letter per order and kind.

## Dashboard (`dashboard.py`, M4b rulings R9, R10)

`summary(db, redis, days=1|7|30, at=…)` for `GET /admin/dashboard`: sales (paid in the
window, not refunded; cost = `COALESCE(bought_units / 1000, cost_usd)`; margin and its
percent of revenue), refunds by `refunded_at`, orders in flight and open attentions now, one
row per Tashkent day (zeros included; days cut in Postgres with `AT TIME ZONE
'Asia/Tashkent'`, the window start in Python at the fixed UTC+5), and the Waxpeer balance the
`orders.health` job cached (`health.cache_balance`, Redis `orders:waxpeer:balance`, 1 h).
Four queries whatever the window; `ix_orders_paid_at` / `ix_orders_refunded_at` (0016).

## Lock order

Order row → kassa transaction row → payment → user wallet (the M3 top-up order with the
order in the top-up's place). No lock is held across a Waxpeer call: read unlocked → call
Waxpeer → `FOR UPDATE` re-read → re-check → write.

## Operations

Runbooks: `docs/runbooks/orders.md` (lifecycle, every alert, attention reasons and the safe
admin action) and `docs/runbooks/waxpeer.md` (key and IP whitelist, balance, the fake versus
the real key). Flow: `docs/product/flows/buy.md`; diagrams
`docs/architecture/sequence-diagrams/{checkout,buy,trade-reconcile}.mmd`.

## Milestones

- **M4a** (built) — tables and FSM, checkout, payment (kassa or balance), the worker's buy at
  Waxpeer, trade sweeps, refunds to the balance, health gauges and alerts, the dev fake, the
  order page (polling), «Мои заказы» and the admin orders and trades pages.
- **M4b** — WebSocket order pushes, email (Resend), the pricing editor and the dashboard,
  the `my-history` orphan-buy probe.
