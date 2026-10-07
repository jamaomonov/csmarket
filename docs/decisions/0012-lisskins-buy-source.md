# 0012. LIS-SKINS as a third buy source

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | data | security | observability

## Context and problem statement

Since ADR-0010 (and its 2026-10-07 update) the shop buys from Skinslink only; Waxpeer buying is
off in prod. On 2026-10-07 LIS-SKINS' instant lots were cheaper than our Skinslink cost on
59 % of the 16 978 names both sell (median −1.7 %, p10 −4.3 %). LIS-SKINS also sells
~8 500 names we do not list today. The owner asked for LIS-SKINS beside Skinslink: its lots
on the item page, the catalogue priced from the cheapest source, and a paid order bought
where the buyer picked. The buyer never sees the source.

LIS-SKINS has an API (`https://api.lis-skins.com/v1`, Bearer key, 200 requests/min,
`market/buy` 500/min) and a public price export (~855 MB of JSON, ~2.4 M lots, a few minutes
behind). It has no purchase webhook we can use; statuses come from `GET /market/info` or a
WebSocket feed.

Design: `docs/superpowers/specs/2026-10-07-lisskins-buy-source-design.md`. Plan:
`docs/superpowers/plans/2026-10-07-lisskins-buy-source.md`; the rulings taken while building
are in this ADR.

## Decision drivers

- **Nothing changes while off.** With `CSMARKET_LISSKINS_ENABLED=false` (the default) the shop
  behaves exactly as before.
- **One order, one purchase.** Never a double buy, never above our ceiling; every failure
  ends in a refund to the balance or an admin's attention.
- **Bounded request path.** At most one new external call on checkout, with a timeout, a
  budget and a breaker (AGENTS §11).
- **Never log PII.** Purchase answers carry the buyer's `steam_id`; the trade link travels as
  `partner` + `token` in the request body only.
- The word `supplier` is banned in `apps/*/src` (AGENTS §6): the code says **source**
  (`lisskins`).

## Considered options

1. **A — LIS-SKINS beside Skinslink** — a third `source`; instant, unlocked lots only; a
   5-minute snapshot of the public export; statuses polled every 30 s.
2. **B — the WebSocket feeds** — a live mirror of lots and purchase statuses.
3. **C — every lot type** — add slow delivery (`delivery_type=2`) and trade-locked lots.

## Decision outcome

**Chosen option:** A, because it brings the cheaper prices and the extra names with the
smallest new moving part: a periodic download and a periodic poll, both in the scheduler.

- **Module `lisskins`** (`apps/api/src/csmarket/modules/lisskins/`): the client, the export
  reader, the snapshot and its roll-up, the checkout's availability check, the purchase
  records and the balance read. Migration `0022_lisskins`: `lisskins_offers`,
  `lisskins_state`, `lisskins_purchases`; `skin_items` gains `lisskins_min_units` and
  `lisskins_count`; `orders.source` accepts `lisskins`.
- **Instant, unlocked lots only.** A lot is kept when `delivery_type = 1` and `unlock_at` is
  null. LIS-SKINS' own bot sends it at once.
- **A snapshot, not a live mirror.** The scheduler's `lisskins.snapshot` (every 5 min)
  streams the export (`core.json_stream.ItemsScanner`, never in memory whole) and keeps, per
  catalogue item, the count and the **10 cheapest** lots (`lisskins_offers`, ~200 k rows).
  Changed rows are upserted, gone rows deleted, the roll-up written, all in one transaction
  under the pricing lock. A snapshot older than `CSMARKET_LISSKINS_STALE_MINUTES` (20) offers
  and prices nothing. A tick whose export has under half of the last applied one's lots is
  refused (`lisskins_state.lots`).
- **Prices.** The cost is the cheapest present source (`skins.repricing.cost_units(*units)`);
  the count is the sum of every source (`SkinItem.stock_count`). The 2-minute Skinslink tick
  became the sources' tick, `sources.prices`: it rolls Skinslink and LIS-SKINS up and
  reprices.
- **Offers.** Offer ids `ls:<LIS-SKINS skin id>`. The item page merges all sources by price;
  ties go Waxpeer, Skinslink, LIS-SKINS (`skins.offers.TIE_ORDER`). The same Steam asset
  listed by two sources is shown once, at the cheaper price.
- **The checkout carve-out (AGENTS §11).** `POST /orders` for a chosen `ls:` lot asks
  `GET /market/check-availability` once: 4 s timeout, 100 calls/min for the whole API (a
  Redis counter per minute), a 120 s breaker after an outage. Gone → the usual substitute
  rule (or `offer_gone`; Superseded by ADR-0013: no substitutes.). A dearer live price → the usual `price_changed` check. A failed
  call → the snapshot price stands; the worker's `max_price` is the money guard. No DB
  connection is held across the call.
- **Buying.** `drain_paid` routes a `lisskins` order to `attempt_lisskins_buy`
  (`orders/lisskins_buying.py`), the Skinslink path's shape: the lease, an unlocked snapshot,
  `POST /market/buy` with `custom_id` = the order id, `max_price` = the agreed cost in cents
  rounded down. LIS-SKINS refuses a `custom_id` it knows, so a repeat never buys twice.
- **One substitute rule for every source** (`orders/substitutes.py`): the cheapest other
  offer of the item, any source, within `cost_units × (1 + order_substitute_ceiling)`, once.
  A LIS-SKINS substitute is retargeted to `<order id>:2` before the request; another source's
  hands the order to that path. Superseded by ADR-0013: no substitutes.
- **Statuses polled.** The scheduler's `lisskins.reconcile` (every 30 s) buys the pending
  buys, then asks `GET /market/info?custom_ids[]=…` once for up to 200 purchases.

### Rulings taken while building

- The JSON scanner moved from `skinslink/stream.py` to `core/json_stream.py`, with the success
  and cursor patterns as arguments.
- Names map to the catalogue as Skinslink's do (`skins.canonical_name`). A Doppler-family name
  without a phase is placed by the lot's `item_paint_index` against `skin_items.paint_index`.
- Freshness is the export's own `last_update`, not the time we applied it.
- `lisskins_state.lots` was added to hold the last applied lot count for the refusal rule.
- `skinslink.prices` was renamed `sources.prices` (`skins.source_prices.sync_source_prices`).
- The export is fetched with a browser-like `User-Agent`: its CDN refused httpx's own on
  2026-10-07.
- Checkout checks only the chosen `ls:` offer. A lot in neither of LIS-SKINS' lists reads
  "unknown" (the snapshot price stands). The budget is a constant, 100/min.
- A returned skin with `trade_create_error` before any offer refunds `invalid_trade_link`
  when its `error` names the buyer's side (`TRADE_LINK_ERRORS`), else `sold_out`.
- Any `return` with a `rollback_…` reason, and any `return` on a delivered order, is
  attention `rolled_back`: the skin may have been used, so an admin decides.
- Delivered orders stay polled every 10 minutes for 8 days (Steam's 7-day trade protection
  and a margin), because an accepted trade can still be rolled back.
- A lost buy answer is never refunded. If `market/info` shows nothing under the `custom_id`
  after `order_unconfirmed_minutes`, the buy is re-armed and sent again under the **same**
  `custom_id` (log `orders.lisskins.repeat_unseen`). Which check LIS-SKINS runs first — the
  `custom_id` or the lot — is not documented, so a repeat refused for the lot is never
  substituted or refunded: `market/info` decides, else the `buy_unconfirmed` attention.
- The dashboard's attention count and the admin «Разобрано» now read every source.

### Positive consequences

- The catalogue gets the cheapest of two markets, and ~8 500 more names can go on sale.
- The item page makes no new external call: LIS-SKINS lots come from our table.
- Only one bounded call is added to checkout, and only for a chosen `ls:` lot.

### Negative consequences

- A third balance to fund and watch, and a third key tied to the VPS IP.
- The export is ~855 MB every 5 minutes: CPU and bandwidth on the VPS.
- A stale snapshot hides LIS-SKINS entirely until a fresh one lands; items only it had go
  inactive meanwhile.
- Statuses are up to 30 s late (no webhook).
- Rollbacks are watched for 8 days after delivery: one more poll per delivered order every
  10 minutes.

## Validation

Contract tests for every endpoint used and the export stream (chunks, truncation, a non-success
body). Integration tests for the snapshot (mapping, top 10, deletes, staleness, refusal),
offers and the asset dedupe, checkout with `check-availability` (available, gone, failed),
every row of the buy table, the status table, the reconcile batch and the unconfirmed rule,
admin and dashboard. Coverage ≥ 95 % for `lisskins`, `orders` and `skins`. In production: one
cheap test buy delivered (`docs/runbooks/lisskins.md`, "Enabling").

## Alternatives considered (detail)

### Option B — the WebSocket feeds

Rejected: a long-lived connection to keep alive and a second state machine, for a gain of
about 30 s on status changes. The snapshot is minutes old anyway, and checkout re-checks the
chosen lot live.

### Option C — every lot type

Slow delivery (up to 12 h) was dearer than instant (median +4.7 %) and makes the buyer wait.
Trade-locked lots need a withdraw/return flow of their own, and none were on the market on
2026-10-07. Both stay out.

## References

- [ADR-0010](./0010-skinslink-buy-source.md) — Skinslink, the second buy source.
- [ADR-0007](./0007-orders-buying-trades.md) — orders, buying, trades.
- Spec `docs/superpowers/specs/2026-10-07-lisskins-buy-source-design.md`.
- Runbook [`lisskins.md`](../runbooks/lisskins.md); flow
  [`lisskins-buy.mmd`](../architecture/sequence-diagrams/lisskins-buy.mmd).
- LIS-SKINS API reference: <https://lis-skins.stoplight.io/docs/lis-skins> (read 2026-10-07).
