# LIS-SKINS as a buy source — design

- **Status:** draft for the owner's review (2026-10-07). Approved in conversation: LIS-SKINS
  beside Skinslink, **auto-delivery lots only**, a periodic snapshot instead of a live mirror,
  statuses polled (no webhook), behind a switch.
- **Why:** on 2026-10-07 LIS-SKINS' auto lots were cheaper than our Skinslink cost on 59 % of the
  16 978 names we both sell (median −1.7 %, p10 −4.3 %), and it sells ~8 500 names we do not.
  Slow delivery (`delivery_type=2`, up to 12 h) is dearer (median +4.7 %) and is left out;
  trade-locked lots (`unlock_at`) were absent from the whole market that day and are left out.
- **API:** `https://api.lis-skins.com/v1`, `Authorization: Bearer <key>`; public price export
  `https://lis-skins.com/market_export_json/api_csgo_full.json` (no key, ~855 MB, ~2.4 M lots,
  minutes behind). OpenAPI exported from <https://lis-skins.stoplight.io/docs/lis-skins>
  (2026-10-07). The key (`CSMARKET_LISSKINS_API_KEY`) is on the server; it answers from the VPS
  IP (balance read, 2026-10-07). Rate limits: 200 req/min, `market/buy` 500 req/min; 429 with
  `retry-after`.

## 1. Goal and success

1. A card's cost is the cheapest of Skinslink and LIS-SKINS (Waxpeer stays off, ADR-0010
   update); its count adds both.
2. The item page lists LIS-SKINS lots (`ls:<id>`) with Skinslink's in one price-sorted list,
   with float, seed, stickers (LIS-SKINS names them itself) and inspect link.
3. Paying for a LIS-SKINS lot buys it there and delivers by a Steam trade offer; every failure
   ends in a refund to the balance or an admin's attention — never a double buy, never above
   our ceiling.
4. `CSMARKET_LISSKINS_ENABLED=false` (the default) leaves the shop exactly as today.

Non-goals: slow delivery, locked lots (withdraw/return), the WebSocket feeds, Dota 2 / Rust,
selling to LIS-SKINS.

## 2. Constraints carried in

- AGENTS §6: no `supplier` in `apps/*/src` — **source** `lisskins`.
- AGENTS §10: purchase answers carry the buyer's `steam_id` (redacted by key); `partner` /
  `token` only in request bodies, never logged; the key joins the redaction list.
- AGENTS §11: one new advisory call on the request path — `check-availability` at checkout
  (§5) — needs ADR-0012 and a line in §11 and the latency alert regexes.
- AGENTS §9: success, retryable failure and idempotent re-call tested on every money path.
- The buyer never sees the source.

## 3. The snapshot of LIS-SKINS' auto lots

Every 5 minutes the scheduler job `lisskins.snapshot` streams the public export (the existing
`skinslink.stream.ItemsScanner` pattern: never in memory whole; LIS-SKINS' envelope is
`{"status": "success", "last_update": <unix>, "items": [...]}`) and keeps, **per catalogue item**
(`market_hash_name` + phase via `skins.canonical_name`, as the Skinslink mirror maps):

- `skin_items.lisskins_min_units`, `lisskins_count` (auto lots only, `unlock_at` null);
- the **10 cheapest** auto lots in a new table `lisskins_offers` (`id` = LIS-SKINS skin id,
  bigint PK; `skin_item_id` FK; `price_units`; `float_value`; `paint_seed`; `asset_id`;
  `inspect_url`; `stickers` JSONB as LIS-SKINS names them `{name, image, slot, wear}`; `updated_at`).
  ~200 k rows; a tick upserts what changed and deletes what left, in one transaction.
- `lisskins_state` (row 1): `snapshot_at` (the export's `last_update`), `synced_at`.

Unmapped names are skipped (counted in the tick's log). A snapshot older than
`CSMARKET_LISSKINS_STALE_MINUTES` (20) offers and prices nothing. A tick whose export has
< 50 % of the previous tick's auto lots is refused (as the Waxpeer sync refuses a collapsed
snapshot). Prices are USD with two decimals → units (1000 = $1).

Images: sticker images from LIS-SKINS go through `skins.images.steam_image_only` (Steam CDN
only; anything else is dropped, the name stays).

## 4. Prices and offers

- `skins.repricing.cost_units` takes the minimum over the sources present (Waxpeer when its
  switch is on, Skinslink, LIS-SKINS); counts add up. The `skinslink.prices` tick becomes the
  sources' tick: it rolls up Skinslink, clears LIS-SKINS columns when off or stale, reprices.
- Offers: `skins.offers.Source` gains `lisskins`, prefix `ls`, id `[0-9]{1,20}`.
  `lisskins.offers_for(db, skin_item_id, *, settings, now)` reads `lisskins_offers`.
  `merge_offers` keeps price order; on a tie the order is Waxpeer, Skinslink, LIS-SKINS.
- The same Steam asset listed by two sources (`asset_id` equal) is shown once, at the cheaper
  price.

## 5. Orders and buying

- `orders.source` gains `lisskins`; `orders.offer_id` `ls:<id>`.
- Checkout: the chosen `ls:` offer's live price comes from
  `GET /market/check-availability?ids[]=<id>` (one call, 4 s timeout, a process-wide budget, a
  breaker). Unavailable → the offer is gone (the usual substitute rule); a failed call → the
  snapshot price is accepted (the worker's `max_price` is the money guard). ADR-0012.
- Table `lisskins_purchases` (order_id PK; `custom_id` unique — our order id, `<order id>:2` for
  a substitute; `skin_id`; `paid_units`; `purchase_id`; `status`; `return_reason`; `error`;
  `steam_trade_offer_id`; `offer_expiry_at`; `amount_units`; `buy_pending`;
  `buy_unconfirmed_at`; attention columns as `skinslink_purchases`; `last_polled_at`).
- Worker (`orders/lisskins_buying.py`, the Skinslink path's shape: lease, snapshot read, no lock
  across the call, writes re-check `buying` + `buy_pending`):
  `POST /market/buy {ids:[id], partner, token, max_price, custom_id}`.

| Answer                                                                                                                 | Outcome                                                 |
| ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| 200, skin `processing` / `wait_accept`                                                                                 | `bought`; the status applied                            |
| 400 `custom_id_already_exists`                                                                                         | look up `market/info?custom_ids[]=` and adopt           |
| 400 `skins_unavailable`, `skins_price_higher_than_max_price`                                                           | one substitute (either source, ≤ +3 %), else `sold_out` |
| 400 `insufficient_funds`                                                                                               | refund `source_low_balance`                             |
| 400 `invalid_trade_url`, `user_trade_ban`, `user_cant_trade`, `private_inventory`, `too_many_failed_attempts_for_user` | refund `invalid_trade_link`                             |
| 401 / 403                                                                                                              | attention `source_forbidden`, the buy kept pending      |
| 429                                                                                                                    | retried after `retry-after`                             |
| timeout, 5xx, transport                                                                                                | `buy_unconfirmed_at`; resolved by `market/info` (§6)    |

- The shared substitute search moves to `orders/substitutes.py`: every source's offers for the
  item, cheapest first, within the order's ceiling; both buy paths use it.

## 6. Status flow (polled)

The scheduler job `lisskins.reconcile` (every 30 s) asks `GET /market/info?custom_ids[]=…` for
up to 200 open purchases in **one** call, applies each, and handles unconfirmed buys: found →
adopt; not found after `order_unconfirmed_minutes` → the same `custom_id` is bought again (a
second buy is impossible: LIS-SKINS refuses a known `custom_id`).

| LIS-SKINS skin status                                                                    | Order                                                |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `processing`                                                                             | `buying`                                             |
| `wait_accept` with `steam_trade_offer_id`                                                | `trade_sent`, offer URL, `send_until = offer_expiry` |
| `accepted`                                                                               | `delivered`                                          |
| `return`, reason `trade_timeout` / `trade_canceled` / `manual_cancel`, before acceptance | `returned` + refund `not_accepted`                   |
| `return`, reason `trade_create_error` (with `error` a trade-link code)                   | `failed` + refund `invalid_trade_link`               |
| `return`, reason `rollback_user` / `rollback_supplier` after `accepted`                  | attention `rolled_back` (the money may be spent)     |
| `wait_unlock` / `wait_withdraw` (never bought on purpose)                                | attention `ambiguous_trade`                          |

The buyer's trade card reads like the others (`buying`, `offer_sent`, `accepted`, `failed`).

## 7. Settings, money, monitoring

`CSMARKET_LISSKINS_ENABLED` (false), `_API_KEY`, `_BASE_URL`, `_EXPORT_URL`,
`_STALE_MINUTES` (20), `_REQUEST_TIMEOUT_SECONDS` (10), `_BUY_TIMEOUT_SECONDS` (35),
`_CHECK_TIMEOUT_SECONDS` (4), `_BALANCE_ALERT_USD` (100). `lisskins_active` = switch and key.
Balance job (5 min, `GET /user/balance`) → gauges + the admin dashboard. Metrics:
`csmarket_lisskins_calls_total{endpoint,outcome}`, snapshot timestamp, balance gauges, enabled.
Alerts: `LisskinsSnapshotStale` (> 20 min), `LisskinsBalanceLow`, `LisskinsBuyFailures`.
Admin: «Источник: LIS-SKINS · ls:…», a «Покупка LIS-SKINS» block; «Разобрано» works on its
attention.

## 8. Testing

Contract (respx): every endpoint, every error code in §5, 429 with `retry-after`, the export
stream (chunking, truncation, a collapsed export). Integration: the snapshot (mapping, top-10,
deletes, staleness, refusal), offers and dedupe by asset, checkout with `check-availability`
(available, gone, call failed), the buy table of §5 row by row, the status table of §6, the
reconcile batch and the unconfirmed rule, admin and dashboard. Coverage gate: `lisskins` ≥ 95 %.

## 9. Documents

ADR-0012 (LIS-SKINS as a buy source; the checkout carve-out), `modules/lisskins/README.md`,
runbook `docs/runbooks/lisskins.md` (key, balance, stale snapshot, buy failures, switching on/off),
module map, metrics, PII, `docs/api/README.md` (`ls:` ids), AGENTS §0/§11.

## 10. Rollout

Ship with the switch off; on the owner's word: switch on, buy one cheap item to a test trade
link, watch the snapshot, the reconcile and the balance; then leave it on.
