# orders

One skin bought by one customer, from checkout to the Steam trade (spec §5, §7; M4a plan
rulings R1–R15). Builds on `payments`, `wallet`, `skins`, `users` and `fx`; `payments`
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
`is_expired`. `api.py` never imports `payments`.

**Routes (`routes.py`):** `POST /orders` (checkout), `GET /orders/{number}`,
`GET /me/orders` — contract in `docs/api/README.md`.

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

## Reads (`service.py`, `trade_view.py`)

`get_owned` (owner only; malformed or top-up-shaped numbers are "not found"),
`list_for_user` (20 a page, keyset on `created_at DESC, id DESC`, cancelled and expired
unpaid orders hidden; orders, item images and trades in **one** query) and `order_out`. A
`pending` order past `expires_at` reads `cancelled` (not payable) before the expiry sweep
writes it. `skin_trade_out(order, trade)` maps the trade to the buyer's five states
(`buying`, `offer_sent`, `accepted`, `released`, `failed`) and a `reason_code`; any
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

## Lock order

Order row → kassa transaction row → payment → user wallet (the M3 top-up order with the
order in the top-up's place). No lock is held across a Waxpeer call: read unlocked → call
Waxpeer → `FOR UPDATE` re-read → re-check → write.

## Milestones

- **M4a** — this module: tables and FSM (now), then checkout, payment (kassa or balance),
  the worker's buy at Waxpeer, trade reconcile, refunds, the order page (polling) and the
  admin trades view.
- **M4b** — WebSocket order pushes, email (Resend), the pricing editor and the dashboard.
