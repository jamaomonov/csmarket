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
  cache miss (15 s timeout, a 120 s breaker after 3 failures in a row, its own `ip_guard` bucket, no DB connection held);
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

## Amendment 2026-10-12 — review fixes (SB-1 … SB-13, admin M7)

- **A closed sale is reopened, not flagged.** A `closed` or `reverted` sale has paid nothing,
  so when Skinslink reports its deposit alive (`new` … `completed`) the status machine reopens
  it and follows the report: a late deposit is paid like any other (the credit keyed by the
  sale, a canceled card request reopened). `late_deposit` now means only a closed sale reported
  `reverted`. The `not_created` grace is 10 minutes (was 2), and the poll keeps asking about a
  `not_created` sale every 5 minutes for 24 h; the webhook stays open while both Skinslink
  credentials are set, whatever the switches.
- **A revert after a card sale became payable never cancels its request.** The admin may be
  paying it: the sale is flagged `rolled_back`, the request stays `to_pay`; «Выплачено» still
  records a transfer, «Отменить (откат)» closes it unpaid.
- **Attentions are visible and resolvable.** `csmarket_sale_attention_open{reason}` and the
  `SaleAttentionOpen` alert; `resolved_at / resolved_by / resolved_note` on `sales` and an
  audited «Проверено»; a list filter and a dashboard count. `SaleHoldOverdue` (hold 6 h past its
  end) and `SaleUnknownStatus` (statuses compared lower-cased; an unknown one counted) join it.
- **Limits.** Optional USD ceilings per sale, per seller per 24 h and for everyone per 24 h in
  the settings document (missing = off, so an old row reads unchanged); a per-user sell block
  (`sale_blocks`); an item already in an open sale refused (`items_in_sale`). The checks take
  transaction-scoped advisory locks held until the sale is committed, with nothing external
  inside. Settings that lose money on an expensive balance sale (top bracket − bonus − 1 % ≤ 0)
  carry a `warnings` entry; the save is never refused.
- **Only `already_exists` adopts a deposit**; any other 409 from `create-deposit` is a refusal.

SB-4 (P&L and reconciliation of Skinslink credits) done 2026-10-13: spec
`2026-10-13-sales-pnl-design.md`. Not done: SB-14
(in-site notifications while email is off — the seller UI's work).

## Amendment 2026-10-12 — paying out from a phone (admin review H1–H3, M1–M10)

- **A claim before the money moves.** The money leaves through a bank app, outside our
  system, so the double-booking guard does not stop a double _payment_. «Беру в работу» is a
  15-minute lease on the request (`payout_requests.claimed_by / claimed_at`); a reveal claims
  a free request; another admin's live claim refuses reveal and every decision (409
  `payout_claimed`) until an explicit, audited takeover. A lease, not a status: an abandoned
  claim frees itself, and the status machine (`waiting_hold` → `to_pay` → …) is unchanged.
  The queue refreshes every 15 s.
- **The card path is no weaker than the balance path.** «Выплачено» to a banned account or a
  frozen wallet needs an audited override reason; «Отклонить» to a frozen wallet says so
  (`wallet_frozen`).
- **The same card on other accounts** is found by a keyed fingerprint
  (`payout_cards.number_fp`, HMAC under an HKDF key of the app key) — not a plain hash, which
  could be brute-forced over the card space from a dump. Existing cards are filled by a
  one-off script after the deploy: the key never reaches SQL.
- **Undo for 10 minutes.** A wrong «Выплачено» goes back to the queue (nothing was on our
  ledger). A wrong «Отклонить» is undone only by taking its credit back: a new transaction kind
  `payout_return_reversal` debits the seller's wallet under its lock and refuses when the
  balance no longer covers the credit (`balance_spent`) — our code never drives a balance
  below zero, and money already spent stays a matter for the owner. Keys carry the request's
  `undo_count`, so a rejection made again credits once more and never replays the first.
  The seller's letter about the undone decision is dropped while still waiting in the outbox;
  one already sent stays sent.
- **Settings saves are optimistic** (`If-Match` = the `updated_at` the edit started from; 409
  `settings_stale`), so a stale tab cannot switch selling back on.
- **The queue** is oldest first with search (sale number, last four, name, Steam ID) and the
  day's totals in Tashkent time; the admin UI shows it as cards on a phone.

Not done: a required bank reference on «Выплачено» (the comment says «номер чека банка» but is
optional), a CSV export and a ledger entry for card payouts (M10's accounting half), the bank
name / holder name of a card (L8), the per-request action trail on the page (L3).

## Validation

Integration tests pin the double credit, a reversal before and after the credit, the forged
webhook, price drift and the card number's PII (the plan's Review Focus). In production: the
owner's test sale, then `csmarket_sale_outcomes_total` and the `SalePayoutsOverdue` alert.

## References

- [ADR-0010](./0010-skinslink-buy-source.md) — Skinslink as a buy source (the client, the
  webhook).
- [ADR-0007](./0007-orders-buying-trades.md) — the buy paths' locking and ledger patterns.
- Skinslink docs: Get Inventory, Create Deposit, Deposit Status, Webhooks, Errors (2026-10-08).
