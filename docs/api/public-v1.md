# Public API v1 — keys and buying

Base: `https://api.csmarket.uz/api/v1/public`. JSON; money is a USD string with three decimals
(`"12.345"`); time is ISO 8601 UTC. Design: `docs/superpowers/specs/2026-10-09-public-api-design.md`,
ADR-0017. Operations: `docs/runbooks/public-api.md`. Order changes can also be pushed to your server:
see [Webhooks](#webhooks); polling `GET /orders/{order_id}` always works.

Every example uses fake values: a token `csm_EXAMPLE…` and a trade link with `partner=1&token=FAKEFAKE`.

## Getting a key

A signed-in user issues the key on the site (profile → «API-ключ»). The token (`csm_` + 43
characters) is shown **once**; only its SHA-256 is kept, so a lost token is replaced by
reissuing. One live key per account: reissuing revokes the old one at once; the tariff, the limits and the IP allow-list carry
over. Any signed-in user may issue a key (owner, 2026-10-09); with `CSMARKET_API_KEY_REQUIRES_FUNDING=true`
issuing needs a successful top-up or the USD wallet switched on by an admin. Buying always needs the USD wallet.

Site routes (a signed-in user, not a key; `Idempotency-Key` ≥ 16 chars on the writes):

| Method   | Path                       | Does                                                                                                                                                                                                                                                        |
| -------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/me/api-key`              | the live key `{id, pricing_profile, created_at, last_used_at}` or `null`; never the token                                                                                                                                                                   |
| `POST`   | `/me/api-key`              | issue (201 `{id, token, …}`); 409 `api_key_not_allowed` without a top-up or the USD wallet (only while `api_key_requires_funding` is on), 409 `api_key_race` when two issues collide (retry); a replayed `Idempotency-Key` is 409 `key_already_issued` (R3) |
| `DELETE` | `/me/api-key`              | revoke (204); 404 `api_key_missing` when none                                                                                                                                                                                                               |
| `PUT`    | `/me/api-key/ip-allowlist` | set the key's IP allow-list `{ip_allowlist: [...]}`; up to 20 IPv4 / IPv6 addresses or CIDRs, normalised and deduplicated; empty = any address; 422 `ip_allowlist_invalid` with the `index` of the bad entry                                                |

Send the token on every call: `Authorization: Bearer csm_EXAMPLEtokenNotReal`. The key may carry
an IP allow-list (set by the user in the profile or with `PUT /me/api-key/ip-allowlist`; empty =
any address): a call from outside is 403 `ip_not_allowed`. A suspended account is 403 `account_suspended`.

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
  "limits": { "read_per_min": 60, "orders_per_min": 10, "feed_per_min": 1, "check_per_min": 30 }
}
```

`limits` are the key's effective limits per minute: the defaults unless an admin raised them for
this key. `check_per_min` is the limit of `POST /tradelink/check`.

### `GET /catalog` — the feed

Items in stock, priced by the key's tariff. Pages are fixed at 1000
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

- **Snapshot.** The feed is refreshed every 60 s. On rare occasions the catalogue is briefly
  unavailable: the first page then answers **503 `feed_unavailable`** with `Retry-After: 60`
  (never an empty catalogue). Retry after the `Retry-After` delay.
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
item; it expires with the offer. Cached for 60 s per tariff and item. The source of an offer is
never named. `delivery` is `instant` for every offer today; treat other values (a future `manual`) as
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
`duplicate_client_order_id`** with the existing order in `order`. Nothing is sent to the seller
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

`trade` (`{offer_sent_at, accepted_at, release_at, steam_offer_id, seller_name}`, each may be
`null`) is present while the status is `trade_sent` or `delivered`; `release_at` is when Steam's
trade protection ends. `steam_offer_id` is Steam's trade offer id: the buyer accepts the offer at
`https://steamcommunity.com/tradeoffer/{id}/`. `seller_name` is the sender's Steam name when the
market gives it; usually `null`.
`refund` is present only when `refunded`.

| Status       | Meaning                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------ |
| `buying`     | paid, the purchase is under way — also an order held for support until a person settles it |
| `trade_sent` | the Steam offer is out                                                                     |
| `delivered`  | the buyer accepted (Steam's protection may still run: see `release_at`)                    |
| `refunded`   | the money is back in the USD wallet                                                        |

A delivered skin is never refunded automatically.

| Refund `reason`        | Cause                                                         |
| ---------------------- | ------------------------------------------------------------- |
| `sold_out`             | the offer was gone                                            |
| `invalid_trade_link`   | the trade link was rejected                                   |
| `trade_hold`           | the buyer's Steam account has a trade hold                    |
| `price_moved`          | reserved, not produced yet: the price rose above what we hold |
| `supplier_refused`     | the seller could not complete or the buyer did not accept     |
| `cancelled_by_support` | a person cancelled the order                                  |

Refunds go to the USD wallet only, once. No letters are sent for API orders.

### How long `buying` lasts

`buying` lasts as long as the market takes to answer: minutes usually, longer when the market is
slow. The order is not lost; keep polling or wait for the webhook. It ends in `trade_sent` when
the offer goes out, or in `refunded` when the market refuses or cancels the purchase, or when our
support cancels the order. A trade that is rolled back after the skin was delivered is not
refunded.

### `POST /tradelink/check`

An advisory check of a buyer's trade link, the one the site runs before checkout. Call it before
`POST /orders` to warn the buyer early. It never blocks a purchase and needs no `Idempotency-Key`.

```bash
curl -s https://api.csmarket.uz/api/v1/public/tradelink/check \
  -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal' \
  -H 'Content-Type: application/json' \
  -d '{"trade_link": "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE"}'
```

```json
{ "verdict": "bad", "reason": "trade_ban" }
```

`verdict` is `ok`, `bad` or `unavailable`. `unavailable` means the check could not run: do not
block a purchase on it. A link that does not parse is `bad` / `invalid_link` at once.

| `reason`            | Meaning                                                      |
| ------------------- | ------------------------------------------------------------ |
| `invalid_link`      | not a Steam trade link                                       |
| `private_inventory` | the buyer's inventory is private                             |
| `trade_ban`         | the buyer's Steam account cannot trade                       |
| `hold`              | the buyer's Steam account has a trade hold                   |
| `not_found`         | no such Steam account, or the token does not match the owner |

`reason` is `null` for `ok` and `unavailable`. The route has its own limit, `check_per_min`
(30 a minute by default).

## Webhooks

We tell your server when an order changes, so you need not poll. One URL per account (it stays
when you reissue the key).

| Method   | Path       | Does                                                                                                                  |
| -------- | ---------- | --------------------------------------------------------------------------------------------------------------------- |
| `PUT`    | `/webhook` | set or replace the URL `{"url": "https://…"}`; needs `Idempotency-Key` (≥ 16 chars); answers the webhook object below |
| `GET`    | `/webhook` | the URL and the latest delivery, or `null` when none is set                                                           |
| `DELETE` | `/webhook` | remove it (204, also when none was set); needs `Idempotency-Key`                                                      |

```json
{
  "url": "https://partner.example/hooks/csmarket",
  "created_at": "2026-10-09T08:00:00Z",
  "last_delivery": {
    "event": "order.paid",
    "status": "sent",
    "attempts": 1,
    "last_status_code": 200,
    "at": "2026-10-09T08:20:01Z"
  }
}
```

`last_delivery.status` is `pending`, `sent` or `failed`. The same `Idempotency-Key` with the same
URL replays the answer; with another URL it is **409 `idempotency_mismatch`**.

### The URL

- `https` only; at most 500 characters; no user name or password in it, no `#fragment`, no
  spaces or control characters. The host is lowercased (IDNA) and the URL stored in that form.
- **Every address the host resolves to must be public.** Private, loopback, link-local,
  multicast, reserved and unspecified addresses, the carrier-grade range `100.64.0.0/10`,
  `198.18.0.0/15`, and addresses that embed an IPv4 (NAT64, 6to4, Teredo; an IPv4-mapped IPv6
  address is read as its IPv4) are refused: **422 `webhook_url_private`**. A malformed URL is
  **422 `webhook_url_invalid`**. DNS gets 3 seconds.
- The check runs when you save **and before every delivery** (DNS may change). We connect to the
  address we checked, with TLS verified against your hostname; redirects are not followed and
  no proxy is used, so answer `2xx` at the URL itself. Your certificate must be valid.

### Events

| Event              | When the order reads…                      |
| ------------------ | ------------------------------------------ |
| `order.paid`       | `buying` (paid, the purchase is under way) |
| `order.trade_sent` | `trade_sent`                               |
| `order.delivered`  | `delivered`                                |
| `order.refunded`   | `refunded`                                 |

An event is sent whenever the order's public status changes, **once per (order, event)**. An
intermediate event can be skipped: an order may go `buying` → `delivered` when the first report
already shows the buyer accepted.

```json
{
  "event": "order.trade_sent",
  "event_id": "0b6f3a52-5f0e-4d7b-9c1e-2f4a8d1c7e90",
  "created_at": "2026-10-09T08:21:30+00:00",
  "order": {
    "order_id": "A1B2C3D4",
    "client_order_id": "shop-1042",
    "status": "trade_sent",
    "item": {
      "item_id": "4f1c…",
      "slug": "ak-47-redline-field-tested",
      "market_hash_name": "AK-47 | Redline (Field-Tested)"
    },
    "price_usd": "14.250",
    "created_at": "2026-10-09T08:20:00Z",
    "trade": { "offer_sent_at": "2026-10-09T08:21:29Z", "accepted_at": null, "release_at": null },
    "refund": null
  }
}
```

`order` is what `GET /orders/{order_id}` returned at the moment of the event; fetch the order again for the current state.

**Delivery is at least once and not ordered.** An event can arrive twice (a retry after a slow
answer) and a later event can arrive before an earlier one. Deduplicate on `event_id` (or on
`(order.order_id, event)`), and trust `order.status` in the payload or `GET /orders/{order_id}`
over the order of arrival.

### Request and signature

`POST` with `Content-Type: application/json`; the body is compact JSON with sorted keys. Headers:

| Header            | Value                                     |
| ----------------- | ----------------------------------------- |
| `X-Csm-Event`     | the event name                            |
| `X-Csm-Timestamp` | unix seconds when the attempt was made    |
| `X-Csm-Signature` | hex HMAC-SHA256 of `"{timestamp}.{body}"` |

The HMAC key is the **UTF-8 bytes of the lowercase hex SHA-256 of your token** (compute it from
the token you hold; we keep only that hash). **Reissuing the key changes the signing key at
once**: update your verifier the moment you reissue. Verify against the **raw body bytes** before
parsing, compare in constant time and reject an old timestamp (we recommend 5 minutes).

```python
import hashlib
import hmac
import time

TOKEN = "csm_EXAMPLEtokenNotReal"  # fake
KEY = hashlib.sha256(TOKEN.encode()).hexdigest().encode()  # hex text, as UTF-8 bytes


def verify(headers: dict[str, str], body: bytes, tolerance: int = 300) -> bool:
    stamp = headers["X-Csm-Timestamp"]
    if abs(time.time() - int(stamp)) > tolerance:
        return False
    expected = hmac.new(KEY, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["X-Csm-Signature"])
```

```js
const crypto = require("node:crypto");

const TOKEN = "csm_EXAMPLEtokenNotReal"; // fake
const KEY = crypto.createHash("sha256").update(TOKEN).digest("hex"); // hex text, used as a UTF-8 key

function verify(headers, rawBody, toleranceSeconds = 300) {
  const stamp = headers["x-csm-timestamp"];
  if (Math.abs(Date.now() / 1000 - Number(stamp)) > toleranceSeconds) return false;
  const expected = crypto
    .createHmac("sha256", KEY)
    .update(`${stamp}.`)
    .update(rawBody)
    .digest("hex");
  const given = Buffer.from(headers["x-csm-signature"] ?? "", "utf8");
  const wanted = Buffer.from(expected, "utf8");
  return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}
```

### Retries

A `2xx` answer within **5 seconds** is success. Anything else (another status, a timeout, a
connection error) is retried after 1 minute, 5 minutes, 30 minutes, 2 hours, then every 2 hours,
**10 attempts** in all (when the host has several addresses, each attempt connects to the next one in turn, IPv4 first), then the delivery is `failed` and is not sent again; read the order with
`GET /orders/{order_id}`. `GET /webhook` shows the latest delivery. If the key is revoked or the
webhook removed, pending deliveries end `failed`.

## Errors

RFC 7807 `application/problem+json`; read `code`, not the text.

| HTTP | `code`                                                                                                                                                                                                                 |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 401  | `unauthorized` — missing, unknown or revoked key                                                                                                                                                                       |
| 402  | `insufficient_balance` — nothing was written                                                                                                                                                                           |
| 403  | `usd_wallet_disabled`, `ip_not_allowed`, `account_suspended`                                                                                                                                                           |
| 404  | `item_not_found`, `order_not_found`                                                                                                                                                                                    |
| 409  | `offer_gone`, `price_above_max` (+ `price_usd`), `duplicate_client_order_id` (+ `order`), `buying_disabled`, `cursor_expired`, `idempotency_mismatch` (webhook)                                                        |
| 422  | `trade_link_invalid`, `ip_allowlist_invalid` (site route, + `index`), body errors, a bad `cursor` or `status` on `GET /orders`, a bad `updated_since`, `webhook_url_invalid`, `webhook_url_private`, `idempotency_key` |
| 429  | `rate_limited`, with `Retry-After`                                                                                                                                                                                     |
| 503  | `feed_unavailable` (feed not built yet), `rate_unavailable` (no FX snapshot ever recorded)                                                                                                                             |

## Limits

Per key, fixed one-minute windows: **60** reads, **10** `POST /orders`, **1** feed first page
(later pages of the same snapshot count as reads), **30** `POST /tradelink/check`
(`check_per_min`). `GET /me` shows the key's effective limits; an admin can raise them per key. Over the limit: 429 `rate_limited` with
`Retry-After`. Failed authentications are throttled per client address (30 a minute) and then
answer 429 too. A full feed pass every five minutes is well inside the limits.

## Not in v1

Selling skins, free-text search, topping up the USD wallet through
the API, USD → soʻm, a second key.

## Changelog

- **2026-10-09 — v1.1.** Only additions: limits per key (`limits.check_per_min` in `GET /me`);
  `POST /tradelink/check`; `trade.steam_offer_id` and `trade.seller_name` on an order; the user
  sets the key's IP allow-list in the profile (`PUT /me/api-key/ip-allowlist`, 422
  `ip_allowlist_invalid`); limits and the allow-list carry over on reissue.
- **2026-10-09 — v1.** Keys, feed, offers, buying, orders, webhooks.
