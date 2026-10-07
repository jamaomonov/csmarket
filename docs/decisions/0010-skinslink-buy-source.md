# 0010. Skinslink as a second buy source

- **Status**: Accepted
- **Date**: 2026-10-06
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | data | security | observability

## Context and problem statement

The approved spec (`2026-10-01-csmarket-design.md` §2, §17) named Waxpeer the only source of
skins and Skinslink the **sell** side, after the MVP. On 2026-10-06 the owner asked for
Skinslink as a **buy** source too: its CS2 offers shown next to Waxpeer's, the catalogue
priced from the cheaper of the two, and a paid order bought from whichever the buyer picked.
The buyer never sees where a skin comes from. Selling through Skinslink's deposit API stays a
later, separate spec.

Design: `docs/superpowers/specs/2026-10-06-skinslink-buy-source-design.md`. Plan:
`docs/superpowers/plans/2026-10-06-skinslink-buy-source.md`; the rulings taken while building
are in this ADR.

## Decision drivers

- **Waxpeer untouched.** ADR-0007's buy, sweeps and refunds keep working as they are; with
  `CSMARKET_SKINSLINK_ENABLED=false` the shop behaves exactly as before.
- **One order, one purchase.** Never a double buy, never a buy above our cost ceiling; every
  failure ends in a refund to the balance or an admin's attention.
- **No new synchronous external call on the request path** (AGENTS §11).
- **Never log PII.** Skinslink payloads carry the buyer's `steam_id`; trade links travel as
  `partner` + `token` in request bodies.
- The word `supplier` is banned in `apps/*/src` (AGENTS §6): the code says **source**
  (`waxpeer` | `skinslink`).

## Considered options

1. **A — Skinslink beside Waxpeer** — a `source` on the order, a mirror of Skinslink's stock
   instead of live reads, a purchase record of its own, a webhook that only enqueues.
2. **B — one neutral trade model** — fold `skin_trades` and the Skinslink purchase into one
   source-agnostic table and buy path.
3. **C — Skinslink as a fallback only** — buy at Skinslink when Waxpeer has nothing.

## Decision outcome

**Chosen option:** A, because it adds a source without rewriting the Waxpeer path that ADR-0007
hardened, and every Skinslink offer competes on price from day one.

- **Module `skinslink`** (`apps/api/src/csmarket/modules/skinslink/`): the client, the
  mirror, the roll-up, the offers read, the purchase records, the webhook and the balance
  read. Migration `0018_skinslink`: `skinslink_items`, `skinslink_state`,
  `skinslink_purchases`, `skinslink_checks`; `skin_items` gains `skinslink_min_units` and
  `skinslink_count`; `orders` gains `source` and `offer_id`.
- **A mirror, not live reads.** The scheduler's `skinslink.mirror` (every 15 s) does a full
  download once (and after `reset`), then follows Catalogue Events from a cursor kept
  verbatim. Items map to our catalogue by `(market_hash_name, phase)`. A mirror older than
  10 minutes offers and prices nothing.
- **Prices and offers.** The scheduler's `skinslink.prices` (every 2 min,
  `skins.prices.sync_skinslink_prices`) rolls the mirror up onto `skin_items` and reprices,
  so Skinslink prices do not wait for, or depend on, the Waxpeer price sync; the 5-minute
  Waxpeer sync rolls up too, so its tick prices both sources consistently. The cost is the cheaper source's;
  the count is the sum, used everywhere (card, item page, checkout, popular sort). The item
  page merges both sources' offers by price, Waxpeer first on a tie.
- **Offer ids.** `listing_id` is a string `wx:<id>` / `sl:<id>`; a bare integer is read as
  `wx:` for one release (an open tab from before the change).
- **Orders.** `source` routes the worker's buy (`drain_paid`). `attempt_skinslink_buy` takes
  the same lease (`take_lease(source=...)`), sends `POST /merchant/purchase` keyed by
  `merchant_tx_id` (the order id; `<order id>:2` for a substitute) with `max_price` = the
  ceiling. Skinslink is idempotent on that id, so a lost answer is resolved by asking under
  the same id, never by buying again.
- **One substitute of either source** within `paid_units × (1 + order_substitute_ceiling)`. A
  Waxpeer substitute turns the order into a Waxpeer order for the Waxpeer path.
- **Status flow.** The webhook verifies `sign` and only enqueues a `skinslink_checks` row
  (`NOTIFY skinslink`); the worker's `skinslink` queue asks Skinslink and applies the answer.
  The scheduler's `skinslink.reconcile` (every 30 s) polls open purchases and retries pending
  buys — the fallback for a lost webhook.
- **Renames.** `waxpeer_low_balance` → `source_low_balance`, `waxpeer_forbidden` →
  `source_forbidden`; the migration maps old rows.

### Rulings taken while building

- `skinslink_purchases.merchant_tx_id` (unique) holds the id actually sent. A Skinslink
  substitute is retargeted (`<id>:2`, asset, `paid_units`) and committed **before** the
  request, so a lost answer is looked up under the right id. Its `max_price` is that offer's
  own price.
- A Waxpeer substitute writes `skin_trades.paid_units` = its price; the Waxpeer path may then
  try one substitute of its own, within the **order's** ceiling (`cost_units × 1.03`, never
  counted from a substitute's price). A rerun after a Skinslink substitute (`<id>:2`) never
  looks for another.
- Any other `failed` reason (incl. `provider_unavailable`) and any 4xx that is neither a
  trade-link code nor 409 is a refused offer: substitute once, then refund `sold_out`. A 409
  or `duplicate_purchase` adopts the stored purchase; a stored failed one counts as refused.
- `hold` with an offer on a `buying` order moves it to `trade_sent` (a missed `active`). The
  buyer reads `hold` as `accepted`, with `release_date = hold_end_date` (Steam protects the
  skin until then); the order stays `trade_sent` until `completed`.
  `reverted` before delivery = `returned` + refund `not_accepted`; after delivery = attention
  `rolled_back`. A purchase failed before any offer is refunded by its reason.
- Skinslink answering "no such purchase" for our `merchant_tx_id` past
  `order_unconfirmed_minutes` **re-arms the buy** (`buy_pending`, due now; outcome `repeat`):
  the buy path sends `POST /merchant/purchase` again under the same id, which Skinslink
  answers with the stored purchase if one exists (spec §5). A silence is never refunded. A
  webhook for an unknown purchase id is logged (`orders.skinslink.unknown_purchase`) and
  dropped.
- The check drain deletes the rows it claims before asking (one-shot); the reconcile is the
  retry. With Skinslink off the rows are dropped unasked.
- The admin margin uses what Skinslink charged (`amount_units`) when known.
- «Разобрано» (`resolve_attention`) works on a Skinslink purchase's attention; resolving it
  frees a refund the attention held. The admin attention **queue** (trades list view and
  counts, the dashboard tile) and the refund / retry actions stay **Waxpeer-only** for now
  (`docs/tech-debt.md`). A Skinslink attention shows on the order page's «Покупка Skinslink»
  block, in `csmarket_trade_attention_total` and in the `csmarket_trades_attention` gauge.
- `orders.health` is source-aware: the stuck and unpolled counts read a Skinslink order's
  purchase (`last_polled_at`, attention), and the attention gauge counts both tables.
- The mirror folds one events page per id in order (the last event wins) before writing;
  a full load keeps the last copy of a duplicated id.

### Positive consequences

- The catalogue gets the cheaper of two markets; the buyer sees one list.
- The item page and checkout make no new external call: Skinslink offers come from our table.
- The sell side can reuse the client, the webhook and the models later.

### Negative consequences

- Two balances to fund and watch, two keys and two IP whitelists.
- Two buy paths and two status flows to keep in step (`orders/buying.py` and
  `orders/skinslink_*.py`).
- A stale mirror hides Skinslink entirely until it syncs; items only Skinslink had go
  inactive meanwhile.
- The integer `listing_id` compatibility must be removed after the next deploy.

## Validation

Contract tests for every Skinslink endpoint used; integration tests for the mirror, the
roll-up, checkout across sources, every failure row of the buy, the webhook (good, bad and
missing sign, forged body ignored, duplicates, disabled → 404) and the reconcile; module
coverage ≥ 95 % for `skinslink`, `orders` and `skins`. In production: the first Skinslink buy
delivered and a declined one refunded once (`docs/runbooks/skinslink.md`).

## Alternatives considered (detail)

### Option B — one neutral trade model

Cleaner in the long run, but it rewrites the Waxpeer buy, sweeps and admin actions that
ADR-0007 hardened, before the first real sale. Deferred: revisit when the sell side lands.

### Option C — Skinslink as a fallback only

Rejected: Skinslink's cheaper offers would never show while Waxpeer has the item, which is
the point of adding it.

## References

- [ADR-0007](./0007-orders-buying-trades.md) — orders, buying at Waxpeer, trades.
- Spec `docs/superpowers/specs/2026-10-06-skinslink-buy-source-design.md`.
- Runbook [`skinslink.md`](../runbooks/skinslink.md); flow
  [`skinslink-buy.mmd`](../architecture/sequence-diagrams/skinslink-buy.mmd).
- Skinslink API reference: <https://docs.skinslink.com/llm> (read 2026-10-06).

## Update 2026-10-07: Waxpeer off as a buy source

A comparison by Steam asset id found 437 643 of Skinslink's 439 072 listings (99.7 %) are
Waxpeer's own auto listings, at the same price (49 %) or cheaper (51 %, mostly −2.9 % to
−4.8 %), almost never dearer. Skinslink gets Waxpeer's stock cheaper than we do and passes
the price on. `CSMARKET_WAXPEER_BUY_ENABLED=false` (prod, `docker-compose.prod.yml`): the
Waxpeer price sync keeps the Steam price but writes no stock, `skinslink.prices` clears what
an earlier Waxpeer tick wrote, the item page and checkout offer Skinslink only, and a
Skinslink buy never substitutes from Waxpeer. It also ends the double count of one asset
listed by both. Trade-link checks and orders already bought at Waxpeer are untouched.
