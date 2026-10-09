# `lisskins` — the third buy source

Owns everything csmarket knows about LIS-SKINS (spec
`docs/superpowers/specs/2026-10-07-lisskins-buy-source-design.md`): the HTTP client, the
reader of the public price export, the snapshot of instant lots and its roll-up onto the
catalogue, the checkout's availability check, the purchase records and the balance read. It
does not own pricing rules (`skins`) or orders (`orders` buys and applies statuses).

## Settings

| Setting                                     | Default                                                       | Meaning                                        |
| ------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------- |
| `CSMARKET_LISSKINS_ENABLED`                 | `false`                                                       | The switch; with the key → `lisskins_active`   |
| `CSMARKET_LISSKINS_API_KEY`                 | empty                                                         | `Authorization: Bearer`                        |
| `CSMARKET_LISSKINS_BASE_URL`                | `https://api.lis-skins.com/v1`                                |                                                |
| `CSMARKET_LISSKINS_EXPORT_URL`              | `https://lis-skins.com/market_export_json/api_csgo_full.json` | The public price export (streamed)             |
| `CSMARKET_LISSKINS_STALE_MINUTES`           | `20`                                                          | An older snapshot offers and prices nothing    |
| `CSMARKET_LISSKINS_REQUEST_TIMEOUT_SECONDS` | `10`                                                          | Export, info, balance                          |
| `CSMARKET_LISSKINS_BUY_TIMEOUT_SECONDS`     | `35`                                                          | `POST /market/buy`                             |
| `CSMARKET_LISSKINS_CHECK_TIMEOUT_SECONDS`   | `4`                                                           | The checkout's `check-availability` (ADR-0012) |
| `CSMARKET_LISSKINS_BALANCE_ALERT_USD`       | `100`                                                         | `LisskinsBalanceLow` fires below it            |

`lisskins_active` = the switch **and** the key. Off: the snapshot and balance jobs skip,
`offers_for` and the roll-up see nothing (the `sources.prices` tick clears what an earlier
snapshot left), checkout makes no availability call. The reconcile follows the **key**, not
the switch: orders already in flight settle after switching off. `max_price` goes out in cents
rounded down — never above the agreed cost. The key is on the log redaction list.

## Tables (migration `0022_lisskins`)

| Table                | Holds                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lisskins_offers`    | The 10 cheapest instant lots of each catalogue item (~200 k rows). `id` = LIS-SKINS' skin id (what `market/buy` takes), `skin_item_id`, `price_units` (1000 = $1), `float_value`, `paint_seed`, `asset_id` (the Steam asset), `inspect_url`, `stickers` (JSONB `{name, image, slot, wear}` as LIS-SKINS names them), `updated_at`                                                                    |
| `lisskins_state`     | Row 1: `snapshot_at` (the export's own `last_update`), `synced_at` (when we applied it), `lots` (sellable lots in it — the refusal baseline)                                                                                                                                                                                                                                                         |
| `lisskins_purchases` | One per LIS-SKINS order, keyed by `order_id`: `custom_id` (unique; the order id; a row from before ADR-0013 may carry `<order id>:2`), `skin_id`, `paid_units` (the cap), LIS-SKINS' `purchase_id`, `status`, `return_reason`, `error`, Steam's `steam_trade_offer_id`, `offer_expiry_at`, `amount_units` (charged), `buy_pending`, `buy_unconfirmed_at`, attention and resolution, `last_polled_at` |

`skin_items` gains `lisskins_min_units` and `lisskins_count` (owned by `skins`, written by this
module's snapshot and roll-up). `orders.source` accepts `lisskins` (owned by `orders`).

## Interface (`api.py`)

The client (`LisskinsClient`, `client_for`, `availability_client`, `request_info_client` — the admin refund's 4 s `market/info`, read through `info_answer` (`InfoAnswer`: the purchases and the answer's entry count, unreadable ones included), ADR-0018 —, the protocols
`LisskinsBuyClient`, `AvailabilityClient`, `BalanceClient`, the errors `LisskinsError`,
`LisskinsForbiddenError`, `LisskinsRateLimitedError`, `LisskinsUnavailableError`, the answer
types, `BUY_LINK_ERRORS`, `TRADE_LINK_ERRORS`, `INFO_MAX_IDS`), the export (`read_export`,
`lot_of`, `Lot`, `Sticker`, `INSTANT`, `to_units`), the snapshot (`load_index`, `Collector`,
`apply_snapshot`, `snapshot_fresh`, `SnapshotResult`, `KEEP`, `MIN_SHARE`), `rollup`,
`offers_for`, the checkout check (`recheck_chosen`, `live_price`, `BUDGET_PER_MINUTE`,
`BREAKER_KEY`, `BREAKER_TTL`), the balance (`refresh_balance`, `cached_balance`,
`BALANCE_KEY`) and the models. `skins`, `orders`, `admin` and the scheduler import only this.

## Parts

- **`client.py`** — `Authorization: Bearer <key>` on every call; answers `{"data": …}`,
  refusals `{"error": "<code>"}`. `buy` (`POST /market/buy`: `ids`, `partner`, `token`,
  `max_price`, `custom_id`), `info` (`GET /market/info` by up to 200 `custom_ids[]`),
  `check_availability` (`GET /market/check-availability`), `balance` (`GET /user/balance`).
  401 / 403 → `LisskinsForbiddenError`; 429 → `LisskinsRateLimitedError` (`retry_after`); 408 /
  5xx / network / an unreadable body / no key → `LisskinsUnavailableError`; any other 4xx →
  `LisskinsError` with `status` and `code`. A purchase's `steam_id` is never read. Error bodies
  are never logged. Each call counts in `csmarket_lisskins_calls_total{endpoint, outcome}`.
- **`export.py`** — `read_export` streams the public export (~855 MB, ~2.4 M lots) through
  `core.json_stream.ItemsScanner` (the scanner moved there from `skinslink`; it takes the
  success and cursor patterns): each lot goes to a callback as soon as it is complete, never
  the whole body in memory. Kept: `delivery_type = 1` (instant) and no `unlock_at`, with an id,
  a name and a price. A body that is cut short, not the export or not `"status": "success"` is
  `LisskinsUnavailableError` — never an empty market. Returns `last_update`. The request uses a
  browser-like `User-Agent`: the export's CDN refused httpx's on 2026-10-07.
- **`snapshot.py`** — `load_index` maps a lot's name to our catalogue as Skinslink's mirror
  does (`skins.canonical_name`); a Doppler-family name without a phase is placed by
  `item_paint_index` against `skin_items.paint_index` (each phase is its own paint).
  `Collector` counts each item's lots and keeps the 10 cheapest in a heap; unmapped names are
  counted and dropped. `apply_snapshot` (caller's transaction) upserts the kept lots that are
  new or moved, deletes the ones that left, writes `lisskins_min_units` / `lisskins_count`
  (clearing items with none and re-deriving `active` from the other sources) and
  `lisskins_state`. A tick with under half (`MIN_SHARE`) of the last applied tick's lots is
  refused: nothing is written (`lisskins.snapshot.refused`). `snapshot_fresh`: the export's
  own `last_update` is within `lisskins_stale_minutes`.
- **`rollup.py`** — `rollup`, run by every price tick (`sources.prices` and the Waxpeer sync):
  on and fresh → items with LIS-SKINS lots are on sale; off or stale → every LIS-SKINS
  roll-up is cleared and `active` re-derived from the other sources.
- **`offers.py`** — `offers_for(db, skin_item_id, *, settings, now)`: the item's lots from
  `lisskins_offers` as source-neutral `skins.Offer` (`ls:<id>`, float, seed, stickers, inspect
  link, `asset_id`); none when off or stale. No external call. Sticker images are filtered to
  Steam's CDN on the way out (`skins.images.steam_image_only`); the name stays.
- **`availability.py`** — checkout's live look at the chosen `ls:` lot (ADR-0012, AGENTS §11):
  `recheck_chosen` asks `check-availability` once (4 s, `lisskins_check_timeout_seconds`),
  within `BUDGET_PER_MINUTE` (100) calls a minute for the whole API (Redis
  `lisskins:check:budget:<minute>`), skipped while the breaker is open (`lisskins:check:breaker`,
  120 s after a 401/403/429/outage). Sold → the offer is dropped (checkout answers `offer_gone`);
  a new price → the offer repriced; anything else → unchanged (the snapshot price; the worker's
  `max_price` guards). A Redis outage does not stop checkout.
- **`balance.py`** — `refresh_balance` (the `lisskins.balance` job): exports the balance gauges
  and caches `lisskins:balance` (1 h) for the admin dashboard; a failed read keeps the last good
  copy.

The buy, the status flow and the reconcile live in `orders` (`orders/README.md`, «Buying at
LIS-SKINS»): they move orders and refund, which only `orders` may do.

## Processes

| Where     | Name                 | Every   | Does                                                                      |
| --------- | -------------------- | ------- | ------------------------------------------------------------------------- |
| scheduler | `lisskins.snapshot`  | 5 min   | `skins.source_prices.sync_lisskins` (export → snapshot → roll-up → price) |
| scheduler | `sources.prices`     | 2 min   | `skins.source_prices.sync_source_prices` (Skinslink + LIS-SKINS roll-up)  |
| scheduler | `lisskins.reconcile` | 30 s    | `orders.reconcile_lisskins` (pending buys, one `market/info` poll)        |
| scheduler | `lisskins.balance`   | 5 min   | `refresh_balance`; sets `csmarket_lisskins_enabled`                       |
| worker    | queue `orders`       | on wake | `orders.drain_paid` → `attempt_lisskins_buy` for a `lisskins` order       |

First runs after a scheduler start: `sources.prices` 105 s, `lisskins.snapshot` 320 s,
`lisskins.reconcile` 90 s, `lisskins.balance` 360 s. Alerts
(`infra/prometheus/alerts/orders.yml`): `LisskinsSnapshotStale`, `LisskinsBalanceLow`,
`LisskinsBuyFailures` — runbook `docs/runbooks/lisskins.md`. Decision: ADR-0012. Flow:
`docs/architecture/sequence-diagrams/lisskins-buy.mmd`.

## Tests

Contract: `tests/contract/test_lisskins_client.py`, `test_lisskins_export.py` (respx; every
endpoint and error code, 429 with `Retry-After`, the stream cut and chunked). Integration:
`test_lisskins_models.py`, `test_lisskins_snapshot.py`, `test_lisskins_rollup.py`,
`test_lisskins_offers.py`, `test_lisskins_listings_route.py`, `test_lisskins_availability.py`,
`test_orders_checkout_lisskins.py`, `test_orders_lisskins_buying.py`, `test_lisskins_status.py`,
`test_lisskins_reconcile.py`, `test_lisskins_balance.py` (helpers `lisskins_factory.py`,
`fake_lisskins_client.py`). Unit: `test_lisskins_settings.py`, `test_json_stream.py`.
Scheduler: `apps/scheduler/tests/test_lisskins_{snapshot,reconcile,balance}.py`,
`test_source_prices.py`. Coverage gate ≥ 95 % (`scripts/check-module-coverage.py`).
