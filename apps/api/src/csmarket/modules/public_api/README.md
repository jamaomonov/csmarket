# public_api

The public purchase API (spec `docs/superpowers/specs/2026-10-09-public-api-design.md`).

Owns:

- `api_keys` — one live key per user (`uq_api_keys_live_user`), `sha256` of the `csm_…` token
  only, the pricing profile (`retail` / `cost`, set by an admin) and an optional IP allowlist.

Keys are revoked, never deleted (`orders.api_key_id` is RESTRICT): deleting a user with API
orders fails on the key.

Orders placed through a key carry `orders.channel = 'api'`, `api_key_id`, `client_order_id`
(unique per owner across all their keys — a reissue neither hides old orders nor frees an old
id; `uq_orders_user_client_order_id`, 0028) and `pricing_profile`; they are paid from the USD wallet
(`wallet.purchases.debit_purchase_usd`) and refunded to it.

## Routes (`/api/v1/public`, `routes.py`) and the site's key routes (`site_routes.py`)

`GET /me`, `GET /catalog`, `GET /catalog/{item_id}/offers`, `POST /orders`,
`GET /orders/{order_id}`, `GET /orders`; and, for a signed-in user, `GET/POST/DELETE
/me/api-key`. The contract is `docs/api/public-v1.md`. No public request calls a market: the feed
and offers read our tables and Redis, and the order is bought by the worker.

## Files

- `keys.py` — issue (revokes the live key, tariff carries over), revoke, lookup; `csm_` + token.
- `auth.py` — the `api_caller` dependency: hash, load, suspended-user and IP allow-list checks,
  `last_used_at` at most once a minute; failed attempts throttled per address.
- `limits.py` — per-key buckets `read` 60 / `order` 10 / `feed` 1 a minute.
- `feed.py` — `build_snapshot` (scheduler `public_api.feed`, every 60 s, first run 400 s after
  a restart), the cursor `{snap}.{n}`; `offers.py` — offers priced by tariff, the sealed
  `offer_id` bound to its item.

## Redis keys

| Key                                     | TTL         | Notes                                                |
| --------------------------------------- | ----------- | ---------------------------------------------------- |
| `public_api:feed:current`               | 1500 s      | `{snap, pages, at}`; absent = 503 `feed_unavailable` |
| `public_api:feed:{snap}:{n}`            | 1800 s      | one JSON text page of 1000 items                     |
| `public_api:offers:{profile}:{item_id}` | 60 s        | priced offers per tariff                             |
| `public_api:rl:{bucket}:{key_id}`       | 60 s window | per-key counters                                     |
| `public_api:authfail:{ip}`              | 60 s window | failed authentications, 30 a minute                  |

Catalogued in `docs/architecture/cache-keys.md`.

## Tariff

`api_keys.pricing_profile` is `retail` or `cost`; until plan C's admin page it is set by SQL
(`docs/runbooks/public-api.md`).
