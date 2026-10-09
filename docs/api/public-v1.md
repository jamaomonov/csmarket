# Public API v1 — keys and buying

Base: `https://api.csmarket.uz/api/v1/public`. JSON; money is a USD string with three decimals
(`"12.345"`); time is ISO 8601 UTC. Design: `docs/superpowers/specs/2026-10-09-public-api-design.md`,
ADR-0017. Operations: `docs/runbooks/public-api.md`. Webhooks («скоро») arrive with plan C: poll
`GET /orders/{order_id}` until then.

Every example uses fake values: a token `csm_EXAMPLE…` and a trade link with `partner=1&token=FAKEFAKE`.

## Getting a key

A signed-in user issues the key on the site (profile → «API-ключ»). The token (`csm_` + 43
characters) is shown **once**; only its SHA-256 is kept, so a lost token is replaced by
reissuing. One live key per account: reissuing revokes the old one at once, the tariff carries
over. Issuing needs a successful top-up or the USD wallet switched on by an admin.

Site routes (a signed-in user, not a key; `Idempotency-Key` ≥ 16 chars on the writes):

| Method   | Path          | Does                                                                                                                                                      |
| -------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/me/api-key` | the live key `{id, pricing_profile, created_at, last_used_at}` or `null`; never the token                                                                 |
| `POST`   | `/me/api-key` | issue (201 `{id, token, …}`); 409 `api_key_not_allowed` without a top-up or the USD wallet; a replayed `Idempotency-Key` is 409 `key_already_issued` (R3) |
| `DELETE` | `/me/api-key` | revoke (204); 404 `api_key_missing` when none                                                                                                             |

Send the token on every call: `Authorization: Bearer csm_EXAMPLEtokenNotReal`. The key may carry
an IP allow-list (CIDR list, set by an admin; empty = any address): a call from outside is 403
`ip_not_allowed`. A suspended account is 403 `account_suspended`.

## Tariffs

A key has a `pricing_profile`, set by an admin (the customer does not see it on the site):

- `retail` (default) — the storefront price in USD.
- `cost` — the offer's cost as is; every price object also carries `retail_price_usd`.

## Orders belong to the account

Orders and `client_order_id` are scoped to the key's **owner**: a reissued key reads the older
orders, an id used earlier is still taken, and another account's order is 404.

## Calls

### `GET /me`

```bash
curl -s https://api.csmarket.uz/api/v1/public/me \
  -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal'
```

```json
{
  "balance_usd": "250.000",
  "usd_wallet_enabled": true,
  "key": { "id": "…", "pricing_profile": "retail", "created_at": "2026-10-09T08:00:00Z" },
  "limits": { "read_per_min": 60, "orders_per_min": 10, "feed_per_min": 1 }
}
```

### `GET /catalog` — the feed

Items with Skinslink or LIS-SKINS stock, priced by the key's tariff. Pages are fixed at 1000
items (no `limit`); follow `next_cursor` until it is `null`.

```bash
curl -s --compressed -D - 'https://api.csmarket.uz/api/v1/public/catalog' \
  -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal'
```

```json
{
  "items": [
    {
      "item_id": "4f1c…",
      "slug": "ak-47-redline-field-tested",
      "market_hash_name": "AK-47 | Redline (Field-Tested)",
      "exterior": "Field-Tested",
      "price_usd": "14.250",
      "stock": 7,
      "updated_at": "2026-10-09T08:14:00+00:00"
    }
  ],
  "next_cursor": "20261009081500.1"
}
```

On a `cost` key each item also has `retail_price_usd`. `item_id` is our item id; `stock` is the
count of offers; `updated_at` is `null` when the item has no price time.

- **Snapshot.** The scheduler rebuilds the feed every 60 s. A scheduler restart delays the first
  build by ~400 s: until then the first page answers **503 `feed_unavailable`** with
  `Retry-After: 60` (never an empty catalogue). Retry.
- **Cursor** `"{snapshot}.{page}"`. A page lives 1800 s, the current pointer 1500 s. A cursor of
  a snapshot that has lapsed is **409 `cursor_expired`**: restart from the first page.
- **ETag.** Every page carries a strong `ETag` and `Cache-Control: private, no-cache`. Send it
  back as `If-None-Match`; an unchanged page is **304** with no body. Only strong tags match
  (`*` and `W/"…"` do not). Page 0 is limited to once a minute **including** a revalidation, so
  poll no faster than that.
- **`updated_since=<ISO time>`** keeps, within the page, the items whose `updated_at` is at or
  after it. A page may therefore come back with an empty `items` and a non-null `next_cursor`:
  keep paging.
- JSON text is gzip-compressed by Caddy; send `Accept-Encoding: gzip`.

### `GET /catalog/{item_id}/offers`

```bash
curl -s https://api.csmarket.uz/api/v1/public/catalog/4f1c…/offers \
  -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal'
```

```json
[
  {
    "offer_id": "Zm9v…",
    "float": 0.2134,
    "paint_seed": 661,
    "stickers": [],
    "price_usd": "14.250",
    "delivery": "instant"
  }
]
```

Cheapest first (`retail_price_usd` is added on `cost`). `offer_id` is opaque and bound to its
item; it expires with the offer. Cached for 60 s per tariff and item. The supplier is never
named. `delivery` is `instant` for every offer today; treat other values (a future `manual`) as
slower. 404 `item_not_found`.

### `POST /orders` — buy

```bash
curl -s https://api.csmarket.uz/api/v1/public/orders \
  -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal' \
  -H 'Content-Type: application/json' \
  -d '{
    "item_id": "4f1c…",
    "offer_id": "Zm9v…",
    "max_price_usd": "14.500",
    "trade_link": "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE",
    "client_order_id": "shop-1042"
  }'
```

- `offer_id` is optional: without it the cheapest offer not above `max_price_usd` is bought.
- `max_price_usd` — up to three decimals; the price is checked against it.
- `trade_link` is your buyer's, sent with every purchase and checked for **form only**.
- `client_order_id` — 1–64 characters of `A-Za-z0-9_.:-`, unique per account.

One transaction: the USD wallet is debited and the order is created **already paid**.
**201** returns the order (below) with `status: "buying"`. Repeating the call with the same
`client_order_id` never makes a second order: it writes nothing and answers **409
`duplicate_client_order_id`** with the existing order in `order`. No call goes out to a supplier
while you wait; the purchase happens in the background.

### `GET /orders/{order_id}` and `GET /orders`

`order_id` is our order number. `GET /orders?cursor=&status=` lists the account's API orders,
newest first, 50 a page; `status` is one of `buying`, `trade_sent`, `delivered`, `refunded`.

```json
{
  "order_id": "A1B2C3D4",
  "client_order_id": "shop-1042",
  "status": "refunded",
  "item": {
    "item_id": "4f1c…",
    "slug": "ak-47-redline-field-tested",
    "market_hash_name": "AK-47 | Redline (Field-Tested)"
  },
  "price_usd": "14.250",
  "created_at": "2026-10-09T08:20:00Z",
  "trade": null,
  "refund": { "amount_usd": "14.250", "reason": "sold_out" }
}
```

`trade` (`{offer_sent_at, accepted_at, release_at}`, each may be `null`) is present while the
status is `trade_sent` or `delivered`; `release_at` is when Steam's trade protection ends.
`refund` is present only when `refunded`.

| Status       | Meaning                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------ |
| `buying`     | paid, the purchase is under way — also an order held for support until a person settles it |
| `trade_sent` | the Steam offer is out                                                                     |
| `delivered`  | the buyer accepted (Steam's protection may still run: see `release_at`)                    |
| `refunded`   | the money is back in the USD wallet                                                        |

A delivered skin is never refunded automatically.

| Refund `reason`        | Cause                                                       |
| ---------------------- | ----------------------------------------------------------- |
| `sold_out`             | the offer was gone                                          |
| `invalid_trade_link`   | the supplier rejected the link                              |
| `trade_hold`           | the buyer's Steam account has a trade hold                  |
| `price_moved`          | the supplier's price rose above what we hold                |
| `supplier_refused`     | the supplier could not complete or the buyer did not accept |
| `cancelled_by_support` | a person cancelled the order                                |

Refunds go to the USD wallet only, once. No letters are sent for API orders.

## Errors

RFC 7807 `application/problem+json`; read `code`, not the text.

| HTTP | `code`                                                                                                                        |
| ---- | ----------------------------------------------------------------------------------------------------------------------------- |
| 401  | `unauthorized` — missing, unknown or revoked key                                                                              |
| 402  | `insufficient_balance` — nothing was written                                                                                  |
| 403  | `usd_wallet_disabled`, `ip_not_allowed`, `account_suspended`                                                                  |
| 404  | `item_not_found`, `order_not_found`                                                                                           |
| 409  | `offer_gone`, `price_above_max` (+ `price_usd`), `duplicate_client_order_id` (+ `order`), `buying_disabled`, `cursor_expired` |
| 422  | `trade_link_invalid`, body errors                                                                                             |
| 429  | `rate_limited`, with `Retry-After`                                                                                            |
| 503  | `feed_unavailable` (feed not built yet), `rate_unavailable` (no FX snapshot ever recorded)                                    |

## Limits

Per key, fixed one-minute windows: **60** reads, **10** `POST /orders`, **1** feed first page
(later pages of the same snapshot count as reads). Over the limit: 429 `rate_limited` with
`Retry-After`. Failed authentications are throttled per client address (30 a minute) and then
answer 429 too. A full feed pass every five minutes is well inside the limits.

## Not in v1

Webhooks («скоро», plan C), selling skins, free-text search, topping up the USD wallet through
the API, USD → soʻm, a second key.
