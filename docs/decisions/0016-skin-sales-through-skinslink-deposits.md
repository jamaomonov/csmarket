# 0016. Selling skins to us through Skinslink deposits

- **Status**: Accepted
- **Date**: 2026-10-08
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security | data

## Context and problem statement

The buy side runs on three sources. The sell side («выкуп») is the next revenue line: a user
sells skins, Skinslink takes them through its deposit API and credits **our** merchant
balance in USD, and we pay the user in soʻm minus our margin — to the csmarket balance, or to
a card by hand. Spec: `docs/superpowers/specs/2026-10-08-skin-sales-design.md`.

## Decision drivers

- No path pays twice, pays for a reverted trade, or pays before a verified `completed`.
- No external call holds a database lock or an open transaction (AGENTS §11).
- A card number is PII and a payment credential.
- The seller is paid what the cart showed.

## Considered options

1. **Skinslink's API flow** (`inventory` → `create-deposit` → `deposit/status` + webhook).
2. **Skinslink's hosted intent** (a redirect or an iframe) — their UI, not ours; no control
   over the copy, the payout choice or the card.
3. **Our own bots** — a Steam bot fleet, trade holds and inventory risk of our own.

## Decision outcome

**Chosen option:** 1, because it keeps the page ours and the risk (bots, Steam holds,
reversals) Skinslink's, and its `min_prices` lets us fix the payout when the sale is created.

- **Pricing.** `price_uzs = floor100((usd − bracket_margin(usd)) × rate)`, the rate being the
  raw CBU rate less `rate_cut_pct` (never the buy side's uplift); the balance gets a bonus, a
  card pays its type's fee; every figure rounds down to 100. All of it lives in one admin
  document (`sale_settings`, row 1), like the pricing rules.
- **Fixed payout.** `POST /sell` re-prices from the inventory snapshot we kept (Redis, 5 min,
  the life of Skinslink's own snapshot), refuses a cart whose payout differs from what it
  showed, and floors each item at 99 % of its quoted price (`min_prices`): Skinslink then
  credits us at least that or refuses the deposit (`item_specified_price_not_found` →
  `prices_changed`).
- **Two new AGENTS §11 carve-outs.** `GET /sell/inventory` calls Skinslink `inventory` on a
  cache miss (6 s timeout, 120 s breaker, its own `ip_guard` bucket, no DB connection held);
  `POST /sell` stores and commits the sale, then calls `create-deposit` once (10 s; a timeout
  leaves the sale `creating` for the poll, which asks `deposit/status`).
- **One status machine.** `sales.status.apply_deposit` moves a sale under its row lock; the
  webhook (signed over `trade_id` only) never moves anything — it queues a check, and the
  worker asks `deposit/status`. A 60-s poll covers `creating` / `offered` (no webhooks before
  `hold`), a 30-min one `hold`.
- **The ledger.** A new credit-normal house account `house_skin_buys`; a balance sale books
  D `user_wallet` / C `house_skin_buys` under `sale:{sale_id}` at `completed` — once, whatever
  the races. A card payout books nothing (the money leaves our bank by hand); a rejected one
  credits the amount before the fee (`items_uzs`) under `payout_return:{request_id}`.
- **Reversals.** `reverted` before the money left cancels the payout; after it, the sale gets
  `attention_reason = rolled_back` and an admin decides — no automatic debit.
- **Cards.** Encrypted with `core.crypto` (purpose `csmarket:payout-card:v1`); `last4` only in
  logs, lists, letters and replays; the full number only through an audited reveal that is
  never stored as a replay. At most three live cards per user.
- **Validation errors.** An app-wide `RequestValidationError` handler answers 422 without
  `input` and `ctx`, so no request body (a card number, a trade link) is ever echoed.
- **Switches.** `CSMARKET_SALES_ENABLED` and the admin's «Выкуп включён», both off by default.

### Positive consequences

- A seller sees soʻm prices for the items Skinslink accepts now, and is paid once.
- The buy side's patterns (row locks, keyed ledger posts, checks queued by a webhook, polling
  fallbacks) carry over unchanged.

### Negative consequences

- Card payouts are manual: an admin must pay within 48 h (`SalePayoutsOverdue`).
- We carry the gap between Skinslink's quote and its credit (at most 1 % per item).
- The 7-day Steam protection delays every payout; no instant credit until KYC (later).

## Validation

Integration tests pin the double credit, a reversal before and after the credit, the forged
webhook, price drift and the card number's PII (the plan's Review Focus). In production: the
owner's test sale, then `csmarket_sale_outcomes_total` and the `SalePayoutsOverdue` alert.

## References

- [ADR-0010](./0010-skinslink-buy-source.md) — Skinslink as a buy source (the client, the
  webhook).
- [ADR-0007](./0007-orders-buying-trades.md) — the buy paths' locking and ledger patterns.
- Skinslink docs: Get Inventory, Create Deposit, Deposit Status, Webhooks, Errors (2026-10-08).
