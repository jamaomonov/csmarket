# public_api

The public purchase API (spec `docs/superpowers/specs/2026-10-09-public-api-design.md`).

Owns:

- `api_keys` — one live key per user (`uq_api_keys_live_user`), `sha256` of the `csm_…` token
  only, the pricing profile (`retail` / `cost`, set by an admin) and an optional IP allowlist.
- `api_webhooks` — one https URL per user (it follows key reissues); `api_webhook_deliveries` —
  the outbox, unique per `(order, event)` (migration 0029).

Keys are revoked, never deleted (`orders.api_key_id` is RESTRICT): deleting a user with API
orders fails on the key.

Orders placed through a key carry `orders.channel = 'api'`, `api_key_id`, `client_order_id`
(unique per owner across all their keys — a reissue neither hides old orders nor frees an old
id; `uq_orders_user_client_order_id`, 0028) and `pricing_profile`; they are paid from the USD wallet
(`wallet.purchases.debit_purchase_usd`) and refunded to it.

## Routes (`/api/v1/public`, `routes.py`) and the site's key routes (`site_routes.py`)

`GET /me`, `POST /tradelink/check`, `GET /catalog`, `GET /catalog/{item_id}/offers`, `POST /orders`,
`GET /orders/{order_id}`, `GET /orders`, `PUT/GET/DELETE /webhook`; and, for a signed-in user, `GET/POST/DELETE
/me/api-key`, `PUT /me/api-key/ip-allowlist`. The contract is `docs/api/public-v1.md`. No public request calls a market: the feed
and offers read our tables and Redis, and the order is bought by the worker.

## Files

- `keys.py` — issue (revokes the live key, tariff carries over), revoke, lookup; `csm_` + token.
- `auth.py` — the `api_caller` dependency: hash, load, suspended-user and IP allow-list checks,
  `last_used_at` at most once a minute; failed attempts throttled per address.
- `limits.py` — per-key buckets `read` 60 / `order` 10 / `feed` 1 / `check` 30 a minute by
  default; a key's `read_per_min` / `orders_per_min` / `feed_per_min` / `check_per_min` columns
  override them (`NULL` = default, admin-edited, carried over on reissue).
- `tradelink_route.py` — `POST /tradelink/check`: the site's advisory check for a key (bucket
  `check`; `ok` / `bad` / `unavailable`; an unparsable link is `bad` / `invalid_link` with no
  upstream call). The checker factory lives in `users/tradelink_checkers.py`.
- The IP allow-list is set by the user (`site_routes.py`, ≤ 20 entries, 422
  `ip_allowlist_invalid` with the `index`); a reissue carries it and the limits over.
- Metrics: gauge `csmarket_public_api_orders_buying_oldest_seconds` (age of the oldest API order
  in `buying`), alert `PublicApiOrderBuyingLong`.
- `feed.py` — `build_snapshot` (scheduler `public_api.feed`, every 60 s, first run 400 s after
  a restart), the cursor `{snap}.{n}`; `offers.py` — offers priced by tariff, the sealed
  `offer_id` bound to its item.

- `webhook_url.py` — `check_url` (https only, no userinfo / fragment / control chars, ≤ 500,
  lowercase IDNA host) and `public_addresses` (DNS in 3 s; every address must be public: no
  private, loopback, link-local, multicast, reserved, unspecified, CGNAT, 198.18/15, NAT64 /
  6to4 / Teredo embeddings; IPv4-mapped unwrapped). Run at save and before every send.
- `webhooks.py` — read / replace / delete the URL (`Idempotency-Key` on the writes).
- `webhook_sender.py` — the worker's `api_webhooks` drain: the claim and the next-attempt booking
  in one short transaction, the POST with no lock; connection pinned to the checked IP with TLS
  checked against the hostname, no redirects, no env proxies; HMAC-SHA256 signing with the key
  hash. Retries 1 m, 5 m, 30 m, 2 h, then 2 h; 10 attempts; 5 s. Events are enqueued by
  `orders.webhook_events` in the order's own transaction. Logs carry the host, never the URL.
- `metering.py` — `MeteredRoute`: `csmarket_public_api_requests_total{route,status}` for every
  public request, with the real status.

Webhook contract: `docs/api/public-v1.md`; stuck deliveries: `docs/runbooks/public-api.md`.

## Redis keys

| Key                                     | TTL         | Notes                                                |
| --------------------------------------- | ----------- | ---------------------------------------------------- |
| `public_api:feed:current`               | 1500 s      | `{snap, pages, at}`; absent = 503 `feed_unavailable` |
| `public_api:feed:{snap}:{n}`            | 1800 s      | one JSON text page of 1000 items                     |
| `public_api:offers:{profile}:{item_id}` | 60 s        | priced offers per tariff                             |
| `public_api:rl:{bucket}:{key_id}`       | 60 s window | per-key counters (`read`, `order`, `feed`, `check`)  |
| `public_api:authfail:{hash_short(ip)}`  | 60 s window | failed authentications, 30 a minute                  |

Catalogued in `docs/architecture/cache-keys.md`.

## Tariff

`api_keys.pricing_profile` is `retail` or `cost`; an admin switches it on the API keys page
(`/admin/api-keys`, audited `api_keys.tariff`), not in SQL.
