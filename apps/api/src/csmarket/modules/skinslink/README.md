# `skinslink` — the second buy source

Owns everything csmarket knows about Skinslink (spec
`docs/superpowers/specs/2026-10-06-skinslink-buy-source-design.md`): the HTTP client, a mirror
of its CS2 stock, the purchase records, the status webhook and the balance read. It does not
price anything (`skins`) and does not own orders (`orders`); both reach it through `api.py`.

## Settings

| Setting                                      | Default                            | Meaning                                          |
| -------------------------------------------- | ---------------------------------- | ------------------------------------------------ |
| `CSMARKET_SKINSLINK_ENABLED`                 | `false`                            | The switch; with both keys → `skinslink_active`  |
| `CSMARKET_SKINSLINK_API_KEY`                 | empty                              | `X-Api-Key`                                      |
| `CSMARKET_SKINSLINK_SECRET`                  | empty                              | Verifies webhook signatures                      |
| `CSMARKET_SKINSLINK_BASE_URL`                | `https://api.skinslink.com/api/v1` |                                                  |
| `CSMARKET_SKINSLINK_MIRROR_STALE_MINUTES`    | `10`                               | An older mirror offers and prices nothing        |
| `CSMARKET_SKINSLINK_REQUEST_TIMEOUT_SECONDS` | `10`                               | Catalogue, status, balance                       |
| `CSMARKET_SKINSLINK_BUY_TIMEOUT_SECONDS`     | `35`                               | `POST /merchant/purchase` (≤ 30 s on their side) |
| `CSMARKET_SKINSLINK_BALANCE_ALERT_USD`       | `100`                              | `SkinslinkBalanceLow` fires below it             |

`skinslink_active` = the switch **and** both keys. Off: the mirror, reconcile and balance jobs
skip, the item page and the price sync see no Skinslink stock, the webhook answers 404 and the
check drain drops its rows. Both keys are on the log redaction list.

## Tables (migration `0018_skinslink`)

| Table                 | Holds                                                                                                                                                                                                                                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skinslink_items`     | The mirror: one row per item on Skinslink's CS2 sale list. `id` = the Steam asset id Create Purchase takes; `market_hash_name`, `phase` (`''` for none), `price_units` (1000 = $1), `float_value`, `paint_seed`, `inspect_url`, `image_url`, `skin_item_id` (our catalogue item, `NULL` = not ours: never offered or priced), `updated_at`  |
| `skinslink_state`     | Row 1: the events `cursor` (kept verbatim, nanoseconds), `mirror_synced_at`, `full_loaded_at`                                                                                                                                                                                                                                               |
| `skinslink_purchases` | One per Skinslink order, keyed by `order_id`: `merchant_tx_id` (unique; the order id, `<order id>:2` for a substitute), `asset_id`, `paid_units` (the cap), Skinslink's `purchase_id` and `status`, Steam's `offer_id`, `fail_reason`, `amount_units` (charged), `hold_end_date`, the buy flags, attention and resolution, `last_polled_at` |
| `skinslink_checks`    | One-shot queue "ask Skinslink about purchase N", written by the webhook with `NOTIFY skinslink`                                                                                                                                                                                                                                             |

`skin_items` gains `skinslink_min_units` and `skinslink_count` (owned by `skins`, written by
this module's roll-up). `orders` gains `source` and `offer_id` (owned by `orders`).

## Interface (`api.py`)

The client (`SkinslinkClient`, `SkinslinkPurchaseClient`, `client_for`, the errors
`SkinslinkError`, `SkinslinkForbiddenError`, `SkinslinkRateLimitedError`,
`SkinslinkUnavailableError`, the answer types, `LINK_ERROR_CODES`, `PURCHASE_FAIL_REASONS`),
the mirror (`sync_mirror`, `mirror_fresh`, `to_units`, `MirrorResult`), `offers_for`,
`rollup`, the checks (`enqueue_check`, `claim_checks`, `SKINSLINK_CHANNEL`), the balance
(`refresh_balance`, `skinslink_cached_balance`) and the models. `skins`, `orders`, `admin`, the
worker and the scheduler import only this.

## Parts

- **`client.py`** — `X-Api-Key` on every call; the `{success, message, data}` envelope; USD as
  `Decimal` from the JSON text. `available` (full, extended), `events(since)`, `purchase`
  (`asset_id`, `partner`, `token`, `merchant_tx_id`, `max_price`), `purchase_status`
  (by `merchant_tx_id`; `None` = no such purchase), `balance`. 403 →
  `SkinslinkForbiddenError`; 429 → `SkinslinkRateLimitedError`; 408 / 5xx / network / an
  unreadable body / no key → `SkinslinkUnavailableError`; any other refusal → `SkinslinkError`
  with `status` and `code`. Error bodies are never logged. Each call counts in
  `csmarket_skinslink_calls_total{endpoint, outcome}`.
- **`mirror.py`** — `sync_mirror`: no cursor or `reset` → the full list, replacing the table in
  one transaction; otherwise the events from the cursor (`upsert` by id, `remove`), following
  `more` for up to 20 pages a tick. Names map to our catalogue by `(market_hash_name, phase)`
  through `skins.canonical_name` (a phase in the name moves out, as for Waxpeer).
  `mirror_fresh`: synced within `skinslink_mirror_stale_minutes`.
- **`rollup.py`** — `rollup`, run inside `skins.prices.sync_prices` (one tick prices both
  sources): per item the cheapest Skinslink price and the count; an item with Skinslink stock
  is active even with no Waxpeer listing. Off or stale → cleared, and items only Skinslink
  kept on sale go inactive.
- **`offers.py`** — `offers_for(db, skin_item_id, …)`: the item's Skinslink offers from the
  mirror as source-neutral `skins.Offer` (`sl:<asset id>`, no stickers); none when off or
  stale. No external call.
- **`webhook.py`, `routes.py`** — `POST /api/v1/skinslink/webhook` (not in the OpenAPI schema;
  on `bootstrap._exempt_self_authenticating_routes`; no `Idempotency-Key`). Body ≤ 4 KiB;
  `sign == base64(sha256(str(id) + secret))` checked in constant time (403 `bad_signature`
  otherwise). The signature covers only the id, so the body is not trusted: a purchase
  webhook queues a check, a deposit webhook (`trade_id`) is answered and ignored. 404 while
  off.
- **`checks.py`** — `enqueue_check` (row + `NOTIFY skinslink` in the caller's transaction) and
  `claim_checks` (`FOR UPDATE SKIP LOCKED`, deletes what it takes, one id once). The drain
  itself is `orders.skinslink_status.drain_checks` (it applies statuses to orders).
- **`balance.py`** — `refresh_balance` (the `skinslink.balance` job, every 5 min): exports the
  balance gauges and caches `skinslink:balance` (1 h) for the admin dashboard; a failed read
  keeps the last good copy.

The buy, the status flow and the reconcile live in `orders` (`orders/README.md`, «Buying at
Skinslink»): they move orders and refund, which only `orders` may do.

## Processes

| Where     | Name                  | Every   | Does                                                       |
| --------- | --------------------- | ------- | ---------------------------------------------------------- |
| scheduler | `skinslink.mirror`    | 15 s    | `sync_mirror`; stamps `csmarket_skinslink_mirror_synced_…` |
| scheduler | `skinslink.reconcile` | 30 s    | `orders.reconcile_skinslink` (polls, retries pending buys) |
| scheduler | `skinslink.balance`   | 5 min   | `refresh_balance`; sets `csmarket_skinslink_enabled`       |
| worker    | queue `skinslink`     | on wake | `orders.drain_checks` (one drainer)                        |

Alerts (`infra/prometheus/alerts/orders.yml`): `SkinslinkMirrorStale`, `SkinslinkBalanceLow`,
`SkinslinkBuyFailures` — runbook `docs/runbooks/skinslink.md`. Decision: ADR-0010. Flow:
`docs/architecture/sequence-diagrams/skinslink-buy.mmd`.

## Tests

Contract: `tests/contract/test_skinslink_client.py` (respx; every endpoint, every error
class). Integration: `test_skinslink_models.py`, `test_skinslink_mirror.py`,
`test_skinslink_rollup.py`, `test_skinslink_offers.py`, `test_skinslink_webhook.py`,
`test_skinslink_status.py`, `test_skinslink_balance.py`, `test_orders_skinslink_buying.py`
(helpers `skinslink_factory.py`, `fake_skinslink_client.py`). Unit:
`test_skinslink_settings.py`. Scheduler: `apps/scheduler/tests/test_skinslink_{mirror,reconcile,balance}.py`.
Coverage gate ≥ 95 % (`scripts/check-module-coverage.py`).
