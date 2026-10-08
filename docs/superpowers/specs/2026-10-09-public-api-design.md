# Public purchase API and the USD wallet — design

- **Status:** draft for the owner's review (2026-10-09). The owner's brief (2026-10-09) fixed
  §2's decisions; the rest was agreed in conversation the same day. ADR-0017 records it.
- **Why:** any csmarket user takes an API key in the profile and buys skins through the API
  from a balance of their own: bots, resellers, Telegram shops. The first client is YuPay: it
  stops buying from its own sources and buys through csmarket (one adapter on its side). So a
  key carries a **tariff**: a regular user pays the storefront price, YuPay pays cost.
- **Supply in the API:** Skinslink and LIS-SKINS only (both deliver by bot, so every offer is
  `delivery: "instant"`). Waxpeer is off on the storefront and stays out of the API; if it
  comes back, its P2P offers would appear as `delivery: "manual"` without breaking clients.
- **Not in v1:** selling skins through the API; free-text search (the feed + `slug` cover it);
  topping the USD wallet up through the API or a kassa; USD → soʻm conversion; a second key,
  scopes, OAuth; a synchronous trade-link check.

## 1. Success

1. A user is given a USD wallet by an admin, converts soʻm into it on the site, issues a key,
   buys a skin over the API onto any trade link, sees `trade_sent` / `delivered` in
   `GET /orders/{id}` and in a webhook; a supplier refusal comes back to the USD wallet with a
   reason.
2. A `cost` key's prices are the supplier's `cost_units`, with `retail_price_usd` beside them.
3. Repeating `POST /orders` with the same `client_order_id` never makes a second order.
4. A full feed pass every 5 minutes by one client (~7.5k requests a day) does not show on the
   graphs; no public request reaches a supplier.

## 2. Decisions (owner)

1. **One key.** A bearer token `csm_` + 32 random bytes (url-safe base64), shown once; only its
   SHA-256 is stored. `Authorization: Bearer csm_…`. One active key per user; reissuing revokes
   the old one (the tariff carries over).
2. **The API lives in dollars, on a separate USD wallet.** Prices are USD strings with three
   decimals; inside they are integer milli-USD units (1000 = $1, as `cost_units`). No rate
   appears in the API. An admin switches a user's USD wallet on (`usd_wallet_enabled`); the
   balance page then shows a second card. API purchases debit only the USD wallet; refunds go
   back to it. Topping up: «Перевести с баланса» at the site rate (CBU × 1.01, ADR-0011) and
   an admin's manual credit (for YuPay). No USD → soʻm.
3. **Tariff per key** (`pricing_profile`, only an admin sets it; default `retail`):
   `retail` = the storefront's pricing rules, in USD; `cost` = the offer's `cost_units` as is,
   plus `retail_price_usd`. The seller's margin is the client's business; csmarket earns
   nothing on `cost` (owner, 2026-10-09).
4. **The supplier is never named.** No Skinslink / LIS-SKINS words or ids; `offer_id` is
   opaque.
5. **The trade link is the client's buyer's**, sent with every purchase and passed on as is.
6. **Webhooks are signed with `sha256(token)`** (the client derives it from the token; we keep
   only that hash) — one key stays one key.
7. **The trade link is checked for form only** at `POST /orders` (422 `trade_link_invalid`); a
   supplier's refusal for the link, a Steam hold or a private inventory is a refund with a
   reason. No public request calls out.
8. **API orders show on the site's «Обмены»** with an «API» tag; no letters are sent for them.

## 3. Money: the USD wallet

- `wallet_accounts` gains `currency` (`UZS` | `USD`, existing rows `UZS`). Amounts stay
  `Numeric(14,0)`: whole soʻm for UZS, milli-USD for USD.
- New account kinds: `user_wallet_usd`, `house_payments_received_usd`,
  `house_adjustments_usd`, `house_fx` (both currencies: the conversion's counter-account).
- `service.post` checks every leg's account currency and that D = C **per currency**; a
  transaction may span two currencies only as two balanced pairs (the conversion).
- New transaction kinds: `fx_convert`, `admin_adjust_usd`; `purchase` and `refund` work on
  either currency (the account decides).
- **Conversion** `POST /wallet/convert {amount_uzs}` (Idempotency-Key): rate = the current
  CBU rate × (1 + `fx_uplift_pct`); `usd_units = floor(amount_uzs × 1000 / rate)`; one
  transaction: D user_wallet / C house_fx (UZS) and D house_fx / C user_wallet_usd (USD); rate,
  snapshot id and both amounts in its metadata. Refused without a fresh rate (503
  `rate_unavailable`), without the USD wallet (403 `usd_wallet_disabled`), on a short soʻm
  balance (402 `insufficient_balance`), or when the result is under 1 milli-USD.
- **Admin credit / debit** of the USD wallet with a required comment, audited.
- `GET /wallet` gains `usd: {enabled, balance_usd} | null`; history entries carry a currency.

## 4. API keys

- Table `api_keys`: `id` (uuid, the `key_id` in logs), `user_id`, `token_hash` (unique),
  `pricing_profile` (`retail` | `cost`), `ip_allowlist` (CIDR list, empty = any), `created_at`,
  `last_used_at` (written at most once a minute), `revoked_at`. A partial unique index allows
  one live key per user.
- Issuing needs a Steam sign-in and at least one successful top-up; 409 otherwise.
- Profile: «API-ключ» block — issue, reissue (old one revoked at once), revoke; the token shown
  once with a copy button; `last_used_at`; a link to the docs.
- Auth: a FastAPI dependency hashes the bearer token, loads the live key and its user
  (suspended user → 403), checks the allow-list against `core.client_ip`; 401 otherwise. Every
  key-authenticated route is out of the per-IP coarse limiter (one audited list, as the kassa
  webhooks) and under its own per-key limits (§7).
- The logging redactor masks any value starting `csm_` and the `authorization` header (already
  a key); only `key_id` is logged.

## 5. Contract v1 (`/api/v1/public/*`)

JSON; errors RFC 7807 with `code`. Money `*_usd`, strings with three decimals. Time ISO 8601
UTC.

| Method       | Path                                          | Does                                                                                                                                         |
| ------------ | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| GET          | `/me`                                         | `balance_usd`, `usd_wallet_enabled`, key `{id, pricing_profile, created_at}`, limits                                                         |
| GET          | `/catalog?cursor=&limit=≤1000&updated_since=` | the feed: `item_id`, `slug`, `market_hash_name`, `exterior`, `price_usd` (+ `retail_price_usd` on `cost`), `stock`, `updated_at`; ETag / 304 |
| GET          | `/catalog/{item_id}/offers`                   | `offer_id`, `float`, `paint_seed`, `stickers[]`, `price_usd` (+ `retail_price_usd`), `delivery`                                              |
| POST         | `/orders`                                     | buy: `item_id`, `offer_id?`, `max_price_usd`, `trade_link`, `client_order_id`                                                                |
| GET          | `/orders/{order_id}`                          | the order: `status`, `item`, `price_usd`, `trade{offer_sent_at, accepted_at, release_at}`, `refund{amount_usd, reason}`, `client_order_id`   |
| GET          | `/orders?cursor=&status=`                     | the key's orders, newest first                                                                                                               |
| PUT / DELETE | `/webhook`                                    | set / clear the webhook URL; `GET /webhook` shows it and the last delivery                                                                   |

- **`item_id`** is our `skin_items.id`; **`offer_id`** is the internal offer id encrypted with
  AES-GCM under a key of its own (`core/crypto`, purpose `public_offer`), url-safe. A forged or
  stale one is 409 `offer_gone`.
- **Buying.** Inside one transaction: resolve the offer (the given one, else the cheapest of
  the item's offers not above `max_price_usd`) from our own tables; price it by the key's
  tariff; 409 `price_above_max` if above `max_price_usd`; debit the USD wallet (402
  `insufficient_balance`); insert the order **already `paid`** (`channel = api`, `api_key_id`,
  `client_order_id`, `charged_units`, `pricing_profile`, the trade link); NOTIFY the worker. A
  repeated `client_order_id` returns 409 `duplicate_client_order_id` with the existing order in
  the body. No pending stage: the client already holds the money with us.
- **Errors:** 401 `unauthorized`; 403 `usd_wallet_disabled`, `ip_not_allowed`,
  `account_suspended`; 402 `insufficient_balance`; 404 unknown item / order (another key's
  order is 404); 409 `offer_gone`, `price_above_max`, `duplicate_client_order_id`,
  `buying_disabled`; 422 `trade_link_invalid` and body errors; 429 with `Retry-After`.
- **Status mapping** (no new FSM states, ADR-0007):

  | Internal                                                            | API                       |
  | ------------------------------------------------------------------- | ------------------------- |
  | `paid`, `buying`                                                    | `buying`                  |
  | `trade_sent` (offer out)                                            | `trade_sent`              |
  | `delivered`, or `trade_sent` with the trade accepted (Steam's hold) | `delivered`               |
  | `failed` / `returned` with a refund                                 | `refunded`                |
  | `failed` / `returned` held for support                              | `buying` (until resolved) |

- **Refund reasons** (closed list) from internal `failure_reason`: `sold_out` → `sold_out`;
  `invalid_trade_link` → `invalid_trade_link`; new internal `trade_hold` (Skinslink `hold` /
  `hold_and_permissions`, LIS-SKINS' hold refusal) → `trade_hold`; new internal `price_moved`
  (the supplier's price rose above `cost_units`) → `price_moved`; `source_low_balance`,
  `not_accepted` → `supplier_refused`; `admin` → `cancelled_by_support`.
- A delivered skin is never refunded automatically (ADR-0007).

## 6. Orders and the worker

- `orders` gains `channel` (`site` | `api`, default `site`), `api_key_id` (nullable FK),
  `client_order_id` (nullable; unique with `api_key_id`), `charged_units` (nullable int),
  `pricing_profile` (nullable). `price_uzs`, `fx_snapshot_id`, `fx_uplift_pct` become nullable
  under a CHECK: a `site` order has them, an `api` order has `charged_units` instead.
- `paid_with` = `usd_wallet` for API orders; `credit_order_refund` books the refund on the
  wallet the order was paid from (`REFUND_SOURCES` gains `usd_wallet`).
- The worker buys an API order exactly as a site order (same claim, lease, lookup-before-buy,
  `cost_units` cap, no substitute offer — ADR-0013). Only `order.trade_link` is read, so the
  per-order link needs no change there. Letters are skipped for `channel = api`.
- «Обмены» lists API orders with an «API» tag and the amount in USD.

## 7. Feed, offers, limits

- **Snapshot job** (scheduler, every 60 s, staggered): one query over `skin_items` with
  Skinslink / LIS-SKINS stock and minimum cost; for each item `cost_units` and the retail
  `price_usd` (`pricing.quote`, the stored rules); pages of 1000 serialised, gzipped and kept
  in Redis with an ETag (hash of the page) and the snapshot time; the previous snapshot stays
  until the new one is complete. `updated_since` filters by the item's `prices_updated_at`.
- **Offers** per item from `skinslink_items` / `lisskins_offers`, priced by tariff, cached 60 s
  per item and tariff.
- **Limits** (Redis counters per `key_id`): 60/min reads, 10/min `POST /orders`, the feed's
  first page once a minute (later pages of the same snapshot free); 429 with `Retry-After`.
- New Redis keys go to `docs/architecture/cache-keys.md`.

## 8. Webhooks

- `api_webhooks` (one per user: `url`, `created_at`); `api_webhook_deliveries` (`order_id`,
  `event`, `payload` JSONB, `status` pending | sent | failed, `attempts`, `next_at`,
  `last_error`, `last_status_code`). A row and `NOTIFY api_webhooks` are written in the same
  transaction as the order's move (outbox, as the email queue); events `order.paid`,
  `order.trade_sent`, `order.delivered`, `order.refunded`.
- The worker posts with a 5 s timeout: headers `X-Csm-Timestamp`, `X-Csm-Signature =
hex(HMAC-SHA256(sha256(token), timestamp + "." + body))`, `X-Csm-Event`. 2xx = sent; else
  retry at 1 m, 5 m, 30 m, 2 h, then every 2 h up to 10 attempts, then `failed`.
- URL: https only, no credentials in it; resolved addresses must be public (no private,
  loopback, link-local) — checked at save and at every send; redirects not followed.
- Reissuing the key changes the signing key at once (documented).

## 9. Admin

- «API-ключи»: list (user, tariff, created, last used, revoked), change the tariff, revoke;
  per key: its orders and revenue (sum of `charged_units`, and for `cost` the forgone retail).
- User card: switch the USD wallet on/off; credit / debit USD with a comment (audited).
- Orders: filter `channel = api`; the detail shows the key and `client_order_id`.

## 10. Observability and docs

- Metrics `csmarket_public_api_requests_total{route,status}` and
  `csmarket_public_api_orders_total{profile,outcome}`, webhook deliveries by outcome; added to
  `docs/architecture/metrics.md`.
- `docs/api/public-v1.md` with curl examples (auth, feed with ETag, offers, buy, poll, webhook
  verification in Python and Node); OpenAPI regenerated; ADR-0017; runbook `public-api.md`
  (revoke a key, a stuck webhook, a refund dispute, switching the USD wallet).
- PII: the per-order trade link follows the existing 30-day erase; `docs/security/pii-handling.md`
  gains the API key hash and webhook URLs.

## 11. Testing

- Ledger: hypothesis on per-currency balance; the conversion; a mixed-currency transaction
  that does not balance per currency is refused.
- Purchase: tariff pricing, `max_price_usd`, insufficient balance, duplicate `client_order_id`
  under concurrency, offer resolution without `offer_id`, refund to the USD wallet with each
  reason, the status mapping.
- Keys: hash-only storage, revoke, reissue, allow-list, suspended user, limits.
- Webhooks: signature, retry schedule, private-address refusal.
- `public_api`, `wallet` and `orders` ≥ 95 % (gate in `scripts/check-module-coverage.py`).

## 12. Delivery in three plans (each deployed alone)

- **A — USD wallet:** ledger currency, conversion, admin credit / debit, the switch, the
  balance card.
- **B — keys and buying:** `api_keys`, auth, feed snapshot, offers, `POST /orders`, status
  mapping, profile block, «API» on «Обмены».
- **C — webhooks and operations:** outbox + delivery, admin keys page, metrics, public docs,
  runbook.
