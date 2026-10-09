# Introduction

The csmarket API lets your shop, bot or service buy CS2 skins from csmarket and have them
delivered to your customer's Steam account. You pay from a USD balance on your csmarket account;
every price in the API is in US dollars.

- **Base URL:** `https://api.csmarket.uz/api/v1/public`
- **Format:** JSON. Money is a string with three decimals (`"12.345"`); time is ISO 8601 UTC.
- **Errors:** `application/problem+json` (RFC 7807) — read the `code` field, not the text.

Every example on this site uses fake values: the token `csm_EXAMPLEtokenNotReal` and a trade link
with `partner=1&token=FAKEFAKE`.

## Quick start

1. Sign in on [csmarket.uz](https://csmarket.uz) with Steam and ask us to switch on your USD
   balance.
2. Issue a key: **Profile → API key**. Copy it — it is shown once.
3. Check the key and your balance:

   ```bash
   curl -s https://api.csmarket.uz/api/v1/public/me \
     -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal'
   ```

4. Read the catalogue (`GET /catalog`), pick an item and its offers
   (`GET /catalog/{item_id}/offers`), then buy (`POST /orders`).
5. Follow the order with `GET /orders/{order_id}` or a webhook.

# Authentication

Send your key on every call:

```http
Authorization: Bearer csm_EXAMPLEtokenNotReal
```

- The key (`csm_` + 43 characters) is shown **once** when you issue it; we keep only its
  SHA-256 hash. If you lose it, reissue it in your profile.
- A key can be issued after your first top-up or once your USD balance is switched on.
- One live key per account. **Reissuing revokes the old key at once**; your orders, balance,
  pricing and webhook stay.
- A key may be limited to a list of IP addresses (ask us). A call from elsewhere is
  `403 ip_not_allowed`. A missing, unknown or revoked key is `401 unauthorized`.

# Pricing and balance

Purchases are paid from your account's **USD balance**. Top it up on the site (from your soʻm
balance) or by arrangement with us. `GET /me` shows it.

Your key has a price list agreed with us. On a partner price list, every price object also
carries `retail_price_usd` — the price csmarket shows on its own storefront — so you can price
your shelf the same way.

Orders and `client_order_id` belong to your **account**, not to a key: after a reissue you still
see every earlier order, and an id you used before is still taken.

# Reading the catalogue

`GET /catalog` returns every item in stock with its lowest price, 1000 items a page. Follow
`next_cursor` until it is `null`.

- The catalogue is rebuilt every 60 seconds. Read it from the first page; a cursor that has
  lapsed answers `409 cursor_expired` — start again from the first page.
- Every page has a strong `ETag`. Send it back as `If-None-Match` to get `304 Not Modified`
  without a body.
- `updated_since=<ISO time>` keeps only the items priced since then. A page may then be empty
  while `next_cursor` is set — keep paging.
- The first page is limited to once a minute (revalidations included). A full pass every few
  minutes is well inside the limits.
- If the catalogue is briefly unavailable, the first page answers `503 feed_unavailable` with
  `Retry-After` — never an empty catalogue.

`GET /catalog/{item_id}/offers` lists the concrete offers of an item, cheapest first, with float,
pattern and stickers. An `offer_id` is opaque, belongs to its item and expires with the offer.
`delivery` is `instant` for every offer today.

# Buying skins

`POST /orders` buys one skin and sends it to the trade link you give:

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

- Without `offer_id` we buy the cheapest offer not above `max_price_usd`.
- `trade_link` is your **customer's** Steam trade link.
- `client_order_id` is your id for the purchase (1–64 characters of `A-Za-z0-9_.:-`), unique on
  your account. **Always send it and retry with the same value** after a timeout: a repeat never
  buys twice — it answers `409 duplicate_client_order_id` with the existing order.

The balance is debited and the order is created at once (`201`, status `buying`). The purchase
then completes in the background; follow it below.

| Status       | Meaning                                                            |
| ------------ | ------------------------------------------------------------------ |
| `buying`     | paid, the purchase is under way                                    |
| `trade_sent` | the Steam trade offer has been sent to your customer               |
| `delivered`  | your customer accepted it (`release_at`: Steam's protection ends)  |
| `refunded`   | the purchase did not happen; the money is back in your USD balance |

| Refund `reason`        | Cause                                                       |
| ---------------------- | ----------------------------------------------------------- |
| `sold_out`             | the offer was gone                                          |
| `invalid_trade_link`   | the trade link was rejected                                 |
| `trade_hold`           | your customer's Steam account has a trade hold              |
| `supplier_refused`     | the seller could not complete or the offer was not accepted |
| `cancelled_by_support` | our support cancelled the order                             |
| `price_moved`          | reserved for later; not sent today                          |

A delivered skin is never refunded automatically. A `402 insufficient_balance` writes nothing.

# Order events

Set one URL for your account and we `POST` every change of an order to it, so you need not poll.

```bash
curl -s -X PUT https://api.csmarket.uz/api/v1/public/webhook \
  -H 'Authorization: Bearer csm_EXAMPLEtokenNotReal' \
  -H 'Idempotency-Key: 6f0b1c2d-0000-4000-8000-000000000001' \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://partner.example/hooks/csmarket"}'
```

The URL must be `https`, have a valid certificate and resolve only to public addresses; we do
not follow redirects, so answer at the URL itself.

| Event              | The order now reads |
| ------------------ | ------------------- |
| `order.paid`       | `buying`            |
| `order.trade_sent` | `trade_sent`        |
| `order.delivered`  | `delivered`         |
| `order.refunded`   | `refunded`          |

```json
{
  "event": "order.trade_sent",
  "event_id": "0b6f3a52-5f0e-4d7b-9c1e-2f4a8d1c7e90",
  "created_at": "2026-10-09T08:21:30+00:00",
  "order": { "order_id": "A1B2C3D4", "client_order_id": "shop-1042", "status": "trade_sent" }
}
```

`order` is the same object `GET /orders/{order_id}` returns (shortened above).

- **At least once, in any order.** An event can arrive twice and a later one before an earlier
  one; an intermediate event can be skipped. Deduplicate on `event_id` and trust `order.status`
  (or `GET /orders/{order_id}`) over the order of arrival.
- Answer `2xx` within 5 seconds. Otherwise we retry after 1 min, 5 min, 30 min, 2 h, then every
  2 h — 10 attempts in all. `GET /webhook` shows the latest delivery.

## Verifying the signature

Every request carries `X-Csm-Event`, `X-Csm-Timestamp` (unix seconds) and `X-Csm-Signature` —
the hex HMAC-SHA256 of `"{timestamp}.{raw body}"`. The HMAC key is the **lowercase hex SHA-256 of
your API token, as text**. Reissuing the key changes the signing key at once.

```python
import hashlib, hmac, time

TOKEN = "csm_EXAMPLEtokenNotReal"
KEY = hashlib.sha256(TOKEN.encode()).hexdigest().encode()

def verify(headers: dict[str, str], body: bytes, tolerance: int = 300) -> bool:
    stamp = headers["X-Csm-Timestamp"]
    if abs(time.time() - int(stamp)) > tolerance:
        return False
    expected = hmac.new(KEY, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["X-Csm-Signature"])
```

```js
const crypto = require("node:crypto");

const TOKEN = "csm_EXAMPLEtokenNotReal";
const KEY = crypto.createHash("sha256").update(TOKEN).digest("hex");

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

Verify the **raw body bytes** before parsing the JSON.

# Errors and limits

| HTTP | `code`                                                                                                                    |
| ---- | ------------------------------------------------------------------------------------------------------------------------- |
| 401  | `unauthorized`                                                                                                            |
| 402  | `insufficient_balance`                                                                                                    |
| 403  | `usd_wallet_disabled`, `ip_not_allowed`, `account_suspended`                                                              |
| 404  | `item_not_found`, `order_not_found`                                                                                       |
| 409  | `offer_gone`, `price_above_max`, `duplicate_client_order_id`, `buying_disabled`, `cursor_expired`, `idempotency_mismatch` |
| 422  | `trade_link_invalid`, `webhook_url_invalid`, `webhook_url_private`, `idempotency_key`, invalid parameters                 |
| 429  | `rate_limited` — wait `Retry-After` seconds                                                                               |
| 503  | `feed_unavailable`, `rate_unavailable` — retry after `Retry-After`                                                        |

Limits per key, per minute: **60** reads, **10** purchases, **1** first catalogue page.
