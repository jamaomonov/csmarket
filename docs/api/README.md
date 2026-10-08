# API

`openapi.json` is generated — never hand-edit. Regenerate with `make gen-api`; CI's
`openapi-drift` job fails when the committed file differs from the app.

- Base path: `https://api.csmarket.uz/api/v1`. Probes: `/healthz` (liveness), `/readyz`
  (readiness: Postgres + Redis, 503 when either fails). `/metrics` is scraped on the
  internal network and answers 404 from the public host.
- Errors: RFC 7807 `application/problem+json` with `type` under `https://csmarket.uz/errors/`;
  429s carry `Retry-After`.
- Every state-changing endpoint accepts `Idempotency-Key` (≥ 16 chars) — spec §13.

## Auth (M1)

Steam OpenID is the only sign-in (ADR-0004). The flow, in short:

1. `GET /auth/steam/start?app=web|admin&locale=ru|uz|en` — a top-level navigation, not
   an XHR. 302 to Steam and sets the `csmarket_oid` sign-in nonce cookie (`HttpOnly`, 10
   min); Steam returns the browser to the **app's** `/auth/steam/callback?locale=…&n=…`,
   not to the API.
2. `POST /auth/steam` `{app, params}` — the app forwards only the `openid.*` params, with
   credentials (`include`) so the nonce cookie goes along. The API requires the signed
   `return_to` to carry the cookie's nonce (else 401, nothing written), verifies with Steam
   and answers `{access_token, expires_in}` plus the cookie. The nonce is single-use: a
   failed attempt restarts from step 1.
3. Every other call sends `Authorization: Bearer <access_token>`.

- **Access token:** EdDSA JWT, 15 minutes, in the JSON body. Keep it in memory; never in a
  cookie or `localStorage`. Roles are not in the token; the server reads them per request.
- **Refresh:** `POST /auth/refresh` with the `csmarket_refresh` cookie (`HttpOnly`,
  `SameSite=Lax`, 30 days, `.csmarket.uz` in prod). Rotates on every use; reusing an old
  cookie revokes every session of the user. Send requests with credentials (`include`).
- **A failed refresh:** only `401` / `403` mean the session is over. A `5xx`, `429` or a
  network error is transient: keep the hint and do not call logout.
- **Sign-out:** `POST /auth/logout` (204, idempotent) revokes the session and the Bearer.
- **Keyless writes.** `/auth/steam`, `/auth/refresh`, `/auth/logout` and
  `/me/trade-link/check` take no `Idempotency-Key`; each says why in its docstring.
  `PATCH /me` and `PUT /me/trade-link` take one.
- **`/auth/dev-login`** (and the M3 dev pay route) is not in this schema. It exists only when dev login is on and the
  environment is not prod; 404 otherwise.

### Errors

| Status | `type` suffix       | When                                                                                                                                                                                                   |
| ------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 401    | `unauthorized`      | No, invalid, expired or revoked token; failed Steam verification. Refresh once, then sign in                                                                                                           |
| 403    | `account-suspended` | The account is banned. **Do not refresh**; show the suspension notice                                                                                                                                  |
| 403    | `forbidden`         | Signed in, but not an admin (`/admin/*`)                                                                                                                                                               |
| 422    | `validation`        | Body errors. Trade-link failures add `code`: `trade_link_invalid` (not a Steam trade link), `trade_link_not_yours` (belongs to another Steam account), `trade_link_missing` (check with nothing saved) |
| 429    | `rate-limited`      | `ip_guard` or the coarse limiter; honour `Retry-After`                                                                                                                                                 |

### Me and trade link

- `GET /me` — the owner's profile, roles and trade link with its last verdict.
- `PATCH /me` `{locale?, email?}` — omitted = unchanged, `null` clears; a new email is
  unverified.
- `PUT /me/trade-link` `{url}` — saves without calling anyone. A different link clears the
  previous verdict, reason and `checked_at`; re-saving the same link keeps them.
- `POST /me/trade-link/check` — advisory. `verdict` is `ok`, `warn` or `bad`, or `null`
  when the check was unavailable; `reason` is `invalid`, `private`, `trade_ban`, `hold` or
  `unavailable`. Cached 10 minutes; 4 s upstream timeouts.

### Skins catalogue (M2)

Public, no sign-in. Under `/skins`:

- `GET /skins/catalog` — filters `category`, `weapon`, `exterior`, `stattrak`, `souvenir`,
  `rarity`, `team`, `min_uzs`, `max_uzs`, `q`; `sort` (`price`, `-price` default, `discount`,
  `popular`); `limit` 1..100 (48); `cursor`. `weapon` takes one model or up to 30
  comma-separated (`AK-47,AWP`, any categories; more is a 422). The cursor is **opaque**: pass back `next_cursor`
  as given. A malformed cursor is 422. `min_uzs` / `max_uzs` compare with the soʻm a card
  shows (rounded up to 100), bounds included; without a CBU rate they are ignored.
- `GET /skins/facets?category=` — counts for the filters; an unknown category is 422.
- `GET /skins/suggest?q=` — search-box suggestions.
- `GET /skins/{slug}` — one item with its wears and cheapest offers; 404 for an unknown or
  hidden slug. `buy_enabled` (M4a) says whether to show the buy panel.
- `GET /skins/{slug}/listings` — live offers `{items, degraded}`. `degraded: true` means the
  answer is the last cached or last snapshot offers because Waxpeer could not answer; it is
  not an error. Rate-limited per IP in its own bucket (`skins-listings`); 429 carries
  `Retry-After`. Offers carry a string `listing_id` — `wx:<id>`, `sl:<id>` or `ls:<digits>`
  (LIS-SKINS, ADR-0012; opaque to the client; checkout echoes it back). Offers of every market
  are merged by price; one Steam asset listed twice is shown once, at the cheaper price.
- `GET /skins/seo/slugs?offset&limit` (≤ 5 000) — slugs for the sitemap.

Conventions: **money is a string** (`price_usd` with 2 decimals, `price_uzs` whole soʻm
rounded up to 100). **`price_uzs` is `null` without a fresh CBU rate** (clients show dollars
and soʻm filters are ignored). Hidden items and categories outside
`CSMARKET_SKINS_CATEGORIES` never appear. Nothing in a response names Waxpeer. These are `GET`s:
no `Idempotency-Key`. Bodies of the catalogue, facets and suggest are cached 60 s.

### Wallet and top-ups (M3)

Signed in (401 without a token), except the provider list.

- `GET /payments/providers` — anonymous; `{providers: [{slug}]}`, the kassas available now in
  the order `click, payme, uzum, mock` (`mock` never in prod). The balance page shows these.
- `POST /wallet/topups` `{amount_uzs, provider, locale}` + **required** `Idempotency-Key`
  (16..160 chars) → **201** `TopupOut {number, amount_uzs, provider, status, expires_at,
intent_url, awaiting_kassa}`. `amount_uzs` is a JSON **integer** of whole soʻm, 1 000..10 000 000 (a
  string, a fraction or a boolean is 422). `locale` `ru|uz|en` picks the kassa page and the
  page the customer returns to. Send the customer to `intent_url`; every kassa returns them
  to `/account/balance/topups/{number}`. The same key with the same amount and provider
  returns the same top-up (201 again) — also after that kassa became unavailable (then
  `intent_url` is `null`); with another amount or provider → 409
  `code: idempotency_mismatch`. Rate-limited by the `topup-create` bucket: 60 a minute per IP
  and 10 a minute per IP and account, then 429 with `Retry-After`.
- `GET /wallet/topups/{number}?locale=` → `TopupOut`. The owner's only: anyone else's, an
  unknown or a malformed number is a 404 (never 403). `status` is `pending`, `succeeded`,
  `expired` or `reversed`; `intent_url` is `null` once the top-up cannot be paid. A pending
  top-up no kassa took up expires after 30 minutes. `awaiting_kassa` is `true` while the
  top-up is `pending` and a kassa holds an attempt (it may still settle past `expires_at`):
  show "checking the payment" and keep polling, not "expired".
- `GET /wallet` → `{balance_uzs}`.
- `GET /wallet/entries?cursor=&limit=` (1..100, default 20) → `{items: [{id, kind,
amount_uzs, created_at, reference_number}], next_cursor}`, newest first. `amount_uzs` is
  **signed**: `+50000` credited, `-10000` debited. `kind` is `topup`, `topup_reversal`,
  `admin_adjust`, `purchase`, `refund`, `sale_credit` (a skin sale paid to the balance) or
  `payout_return` (a rejected card payout returned to the balance); `reference_number` is the
  top-up's number for `topup` and `topup_reversal`, the order's number for `purchase` and `refund`,
  the sale's number (`S…`) for `sale_credit` and `payout_return`, else `null`. The cursor is opaque; a malformed one is 422.
  `type=topup` keeps `topup` and `topup_reversal` lines; `type=withdrawal` is an empty list
  until payouts exist; any other `type` is 422 («Транзакции» filters).
- `POST /dev/topups/{number}/pay` is not in this schema: it pays the owner's top-up through
  the `mock` kassa, exists only when dev login is on and the environment is not prod, and
  answers 404 otherwise. Keyless (a repeat is a no-op); 409 `code: topup_not_payable` for an
  expired or reversed top-up.

| Status | `type` suffix | `code`                 | When                                             |
| ------ | ------------- | ---------------------- | ------------------------------------------------ |
| 422    | `validation`  | `topup_amount`         | Not a whole soʻm in range (carries `min`, `max`) |
| 422    | `validation`  | `topup_provider`       | Unknown, unavailable here, or `wallet`           |
| 422    | `validation`  | —                      | Missing, short or over-long `Idempotency-Key`    |
| 409    | `conflict`    | `idempotency_mismatch` | The key opened a top-up for another amount/kassa |
| 409    | `conflict`    | `topup_not_payable`    | Dev pay of an expired or reversed top-up         |

Money is a string of whole soʻm digits (`balance_uzs`, `amount_uzs`).

Kassa callbacks (below) and the admin routes are documented with their auth; design and the
rulings behind them: ADR-0006. Cabinet settings: `docs/runbooks/kassa-setup.md`.

### Orders (M4a)

Signed in (401 without a token). One skin per order.

- `POST /orders` `{slug, listing_id, price_uzs}` + **required** `Idempotency-Key` (16..160
  chars) → **201** `OrderOut`. `listing_id` is an offer id from `GET /skins/{slug}/listings`
  (`wx:<id>` / `sl:<id>` / `ls:<digits>`; a bare integer is still read as `wx:<id>` for one
  release, anything else is 422);
  `price_uzs` is the whole soʻm the panel showed for it (a JSON **integer** > 0). The server
  re-prices the offer from the same live listings: within ±2 % of `price_uzs` it bills **its
  own** price; further off → 409 `price_changed` with the new `price_uzs`. An offer sold in
  the meantime is never replaced (ADR-0013): 409 `offer_gone` with
  `next_offer: {listing_id, price_uzs}` (the cheapest offer left, a string id, either
  market) or `null`. A chosen `ls:` offer is re-checked live at LIS-SKINS (ADR-0012: one
  `check-availability` call, 4 s timeout, 100 a minute for the API, a 120 s breaker): sold →
  as an offer sold in the meantime (`offer_gone`); a live price beyond ±2 % of
  the shown one → `price_changed`; no answer → the snapshot price stands. So `POST /orders` for an `ls:`
  offer can take up to ~4 s. The same key
  again → **200** with the stored order, whatever the body. Rate-limited by the
  `order-create` bucket: 60 a minute per IP and 10 a minute per IP and account, then 429
  with `Retry-After`. The new order is `pending` and payable for 15 minutes.
- `POST /orders/{number}/pay` `{provider, locale}` + **required** `Idempotency-Key`
  (16..160 chars) → **200** `{order: OrderOut, intent_url}`. `provider` is `wallet` (the
  balance), `click`, `payme`, `uzum` or `mock` (dev only); `locale` is `ru`, `uz` or `en`
  (the kassa's page and the order page it returns to). From the balance the order is `paid`
  at once and `intent_url` is `null`; a short balance is 409 `balance_too_low` and changes
  nothing (no mixed payment). Through a kassa the order stays `pending` and `intent_url` is
  the kassa's payment page (a second call reuses the same attempt). The same key and body
  replay the first answer; the same key with another body is 409 `idempotency_mismatch`.
  The owner's only (404 otherwise). Rate-limited by the `order-pay` bucket (as
  `order-create`).
- `GET /orders/{number}` → `OrderOut`. The owner's only: anyone else's, an unknown or a
  malformed number is a 404.
- `GET /me/orders?cursor=` → `{items: [OrderOut], next_cursor}`, 20 a page, newest first;
  cancelled orders and unpaid ones past their time are left out. The cursor is opaque; a
  malformed one is 422.

`OrderOut`: `number`, `status` (`pending`, `paid`, `buying`, `trade_sent`, `delivered`,
`cancelled`, `failed`, `returned` — a `pending` order past `expires_at` already reads
`cancelled`), `slug`, `name`, `phase`, `image_url`, `float_value` (the bought offer's float
as a string without trailing zeros, `"0.6214"`; `null` when the market named none and on orders
before 2026-10-08), `paint_seed` (integer or `null`, likewise), `exterior` (the catalogue's
`FN` / `MW` / `FT` / `WW` / `BS` or `null`), `rarity_color` (`"#eb4b4b"` or `null`),
`price_uzs` / `price_usd` (strings),
`created_at`, `expires_at`, `paid_at`, `delivered_at`, `paid_with`, `refunded_to`
(`balance` or `null` — promise a refund only when it is set), `payable`, `trade`.
`trade` is `null` for `pending`/`cancelled`, else `{state, reason_code, offer_url,
send_until, release_date, seller, refunded_to}`: `state` is `buying`, `offer_sent` (accept
in Steam before `send_until`), `accepted` (Steam protects it until `release_date`),
`released` or `failed`; `reason_code` (`not_accepted`, `sold_out`, `try_later`, `trade_link`
— the buyer's trade link did not work, `support`, `other`) is set on `failed`; `support` is set whatever the state while a purchase is being
checked by hand (never promise a refund then).

| Status | `type` suffix      | `code`               | When                                                                                 |
| ------ | ------------------ | -------------------- | ------------------------------------------------------------------------------------ |
| 409    | `conflict`         | `buying_disabled`    | Buying is switched off                                                               |
| 409    | `conflict`         | `trade_link_missing` | No trade link saved                                                                  |
| 409    | `conflict`         | `trade_link_bad`     | The saved link was checked bad (`reason`: `invalid`, `private`, `trade_ban`, `hold`) |
| 409    | `conflict`         | `price_changed`      | The offer's price moved beyond ±2 % (`price_uzs`)                                    |
| 409    | `conflict`         | `offer_gone`         | Sold; never replaced (`next_offer` or `null`)                                        |
| 404    | `not-found`        | —                    | Unknown or hidden item                                                               |
| 503    | `rate-unavailable` | `rate_unavailable`   | No fresh soʻm rate                                                                   |
| 422    | `validation`       | —                    | Malformed body or missing/short/over-long key                                        |

`POST /orders/{number}/pay`:

| Status | `type` suffix          | `code`                 | When                                                                     |
| ------ | ---------------------- | ---------------------- | ------------------------------------------------------------------------ |
| 409    | `conflict`             | `order_not_payable`    | `reason`: `paid` (already paid, any way) or `expired` (also cancelled)   |
| 409    | `insufficient-balance` | `balance_too_low`      | The balance does not cover the order                                     |
| 409    | `conflict`             | `idempotency_mismatch` | The key answered another `provider` / `locale`                           |
| 422    | `validation`           | `order_provider`       | That kassa is not available here                                         |
| 422    | `validation`           | —                      | Malformed body (unknown `provider`/`locale`, extra field) or key missing |
| 404    | `not-found`            | —                      | Not the caller's order                                                   |

`POST /dev/orders/{number}/pay` is not in this schema: it pays the owner's order through the
`mock` kassa (the real `settle`), exists only when dev login is on and the environment is
not prod, and answers 404 otherwise. Keyless (a repeat is a no-op) → `OrderOut`; 409
`order_not_payable` (`reason: expired`) for an expired or cancelled order.

Two more dev routes exist only with the dev Waxpeer fake on (`CSMARKET_WAXPEER_FAKE=true`,
never in prod; 404 otherwise), both signed in, keyless and not in this schema:

- `POST /dev/orders/{number}/trade {action: "accept" | "decline" | "rollback"}` — moves the
  owner's trade at the fake and answers it as the fake now reports it (`WaxpeerTrade`). The
  order itself moves on the next reconcile tick (the protection watch for a delivered one).
  `accept` needs the offer out (status 4); `decline` any unaccepted trade; `rollback` an
  accepted one. A repeat of a done action is a no-op; otherwise 409 `fake_trade_state`, or
  `fake_trade_missing` before the buy. 404 for another account's order.
- `POST /dev/waxpeer/balance {units}` (≥ 0) — sets the fake's Waxpeer balance → `{units}`.

### Kassa callbacks: Click (M3)

Called by Click, not by our clients; anonymous, exempt from the per-IP limiter.

- `POST /payments/click/prepare` and `POST /payments/click/complete` — Click's Shop API.
  Body `application/x-www-form-urlencoded` (anything else is `-8`); authenticated by the MD5
  `sign_string` over the raw fields and our service's `SECRET_KEY`, checked before anything
  else. **Always HTTP 200** with `{error, error_note, …}`: `0` success, `-1` signature, `-2`
  amount (soʻm), `-3` action, `-4` already paid, `-5` unknown number, `-6` unknown
  transaction, `-7` internal, `-8` malformed or not POST, `-9` cancelled or not payable.
- No `Idempotency-Key`: prepare is idempotent on Click's `(click_trans_id, service_id)`,
  complete on our `merchant_prepare_id` (a replay is `-4`). `merchant_trans_id` is the
  top-up or order number (M4a); a completed order payment is never reversed. Details: `apps/api/src/csmarket/modules/click/README.md`.

### Kassa callbacks: Payme (M3)

Called by Payme, not by our clients; anonymous, exempt from the per-IP limiter.

- `POST /payments/payme/merchant` — Payme's Merchant API, JSON-RPC 2.0
  (`CheckPerformTransaction`, `CreateTransaction`, `PerformTransaction`, `CancelTransaction`,
  `CheckTransaction`, `GetStatement`, `SetFiscalData`). Authenticated by HTTP Basic
  `Paycom:<key>` (the production or the sandbox key), checked before the body is read.
  **Always HTTP 200** with `{result, id}` or `{error: {code, message: {ru, uz, en}, data}, id}`;
  any other HTTP method is `-32300`. Amounts are tiyin (soʻm × 100); the account field is
  `account.order` = the top-up or order number. Cancel of a performed order is `-31007`.
- No `Idempotency-Key`: every method is idempotent on Payme's transaction `id`. Codes and
  states: `apps/api/src/csmarket/modules/payme/README.md`.

### Kassa callbacks: Uzum (M3)

Called by Uzum, not by our clients; anonymous, exempt from the per-IP limiter.

- `POST /payments/uzum/check`, `/create`, `/confirm`, `/reverse`, `/status` — Uzum Bank's
  Merchant API, JSON bodies carrying `serviceId`. Authenticated by HTTP Basic
  `<login>:<password>` (the production or the sandbox pair), checked before the body is read.
  **HTTP 200 on success, HTTP 400 on every error** with
  `{"status": "FAILED", "errorCode", "serviceId", "transId"?}`; any other HTTP method is
  `10003`. Amounts are tiyin (soʻm × 100), except `/check`'s `data.amount.value`, which is
  whole soʻm. The account is `params.order` (also `orderId`, `order_id`) = the top-up or
  order number. `/reverse` of a confirmed order is `10017`.
- No `Idempotency-Key`: every call is keyed on Uzum's `transId`, and a replay answers a
  dedicated code (`10010` create, `10016` confirm, `10018` reverse). Codes and states:
  `apps/api/src/csmarket/modules/uzum/README.md`; Postman collection for Uzum's engineer:
  `docs/api/uzum.postman_collection.json`.

### Admin users (M3)

All under `/admin/users`, admin only (401 without a token, 403 for a customer). Details,
error codes and the replay rule: `apps/api/src/csmarket/modules/admin/README.md`, **Users**.

- `GET /admin/users?q=&cursor=&limit=` → `{items: [{id, display_name, avatar_url, steam_id,
roles, banned_at, created_at, balance_uzs}], next_cursor}` — newest first; `q` = part of the
  display name or an exact 17-digit Steam ID (≤ 80 chars); `limit` 1..100 (20); a bad cursor
  is 422 `cursor`. Free-text admin filters (`q` here and on payments; `action`,
  `target_type`, `target_id` on audit) refuse a NUL byte with 422.
- `GET /admin/users/{id}` → `AdminUserCard {user: {id, steam_id, display_name, avatar_url,
email, locale, roles, banned_at, ban_reason, created_at, trade_link_masked,
trade_link_verdict, trade_link_reason, trade_link_checked_at}, balance_uzs, entries: [{id,
kind, amount_uzs, created_at, reference_number, actor, reason}], topups: [{number,
amount_uzs, status, provider, created_at, succeeded_at}], orders: [AdminOrderRow] (M4a)}` —
  the latest 20 of each. Unknown or malformed id → 404.
- `POST /admin/users/{id}/ban` `{reason: 3..500}` → card. 409 `ban_self`, `ban_admin`,
  `already_banned`. Ends every session of the user.
- `POST /admin/users/{id}/unban` `{reason: 3..500}` → card. 409 `not_banned`.
- `POST /admin/users/{id}/wallet/adjust` `{amount_uzs: JSON integer ≠ 0, |x| ≤ 100 000 000,
reason: 4..500}` → card. 409 `balance_too_low` for a clawback beyond the balance.
- `POST /admin/users/{id}/wallet/adjust-usd` `{amount_usd: "250.000" (string, ≠ 0, ≤ 3 decimals,
|x| ≤ 100000), reason: 4..500}` → card (`balance_usd`, `usd_entries`). 409 `balance_too_low`.
- `PUT /admin/users/{id}/usd-wallet` `{enabled, reason: 3..500}` → card. Switching off with money
  on it is allowed: the balance stays, conversion and API purchases stop.
- Every write **requires** `Idempotency-Key` (16..160 chars; 422 otherwise). A replay returns
  the stored card and writes nothing; the same key with another body or user is 409
  `idempotency_mismatch`. Audited: `users.ban`, `users.unban`, `wallet.adjust`, `wallet.adjust_usd`, `wallet.usd_switch`.

### Admin orders and trades (M4a)

Admin only (401 without a token, 403 for a customer). Newest first, keyset on
`(created_at DESC, id DESC)`, `limit` 1..100 (20), a bad cursor is 422 `cursor`. Unknown or
malformed number → 404. Details: `apps/api/src/csmarket/modules/admin/README.md`,
**Orders and trades**.

- `GET /admin/orders?q=&status=&user_id=&cursor=&limit=` → `{items: [AdminOrderRow {number,
status, name, phase, price_uzs, paid_with, user: {id, display_name}, created_at,
attention_reason}], next_cursor}`. `q` (≤ 100 chars) = a number prefix (any case, ≤ 8 chars)
  or part of the item name; `attention_reason` is the **open** one (unresolved), else `null`.
- `GET /admin/trades?view=all|active|attention&q=&cursor=&limit=` → `{items: [AdminOrderRow +
{trade: {status, state, attention_reason, send_until}}], counts: {active, attention},
next_cursor}` — orders with a trade; `active` = `buying`/`trade_sent`, `attention` = an
  unresolved attention; the counts ignore `q`.
- `GET /admin/orders/{number}` → `AdminOrderDetail {order: {every orders column but
trade_link and idempotency_key, trade_link_masked, fx_rate, margin_usd}, user, trade: AdminTradeOut | null,
skinslink: AdminSkinslinkPurchaseOut | null, lisskins: AdminLisskinsPurchaseOut | null, payments: [{id, provider, status, amount_uzs, created_at}], can_refund, can_retry}`.
  The order's `source` is `waxpeer`, `skinslink` (ADR-0010) or `lisskins` (ADR-0012); a
  Skinslink order has `skinslink` (its purchase) and no `trade`, a LIS-SKINS order has
  `lisskins` `{custom_id, skin_id, purchase_id, status, return_reason, error, offer_id,
offer_url, offer_expiry_at, amount_usd, buy_pending, buy_unconfirmed_at, attention_reason,
resolved_at}` and no `trade`. `resolve` works on either purchase's attention; refund and
  retry refuse them (409) for now, and the trades list does not show them.
- `POST /admin/orders/{number}/resolve` `{note?: ≤ 500 | null}` → detail. 409
  `nothing_to_resolve`. Stamps `resolved_*` once; already resolved → unchanged, not audited.
- `POST /admin/orders/{number}/refund` (no body) → detail. 409 `already_refunded`,
  `order_in_flight` (also when a purchase is on record, or Waxpeer shows a live or
  once-accepted trade under the order), `order_not_refundable`, `order_busy`,
  `waxpeer_unavailable`. Asks Waxpeer before it books (one lookup, 4 s; ADR-0007 Y), so it
  can take up to ~4 s; a `waxpeer_unavailable` booked nothing and the same key may be sent
  again.
- `POST /admin/orders/{number}/retry` (no body) → detail. 409 `not_retryable` (also when a
  purchase is on record), `order_busy`.
- Every write **requires** `Idempotency-Key` (16..160 chars; 422 otherwise); a replay returns
  the stored page and writes nothing; the same key on another request is 409
  `idempotency_mismatch`. Audited: `orders.trade.resolve`, `orders.refund`, `orders.buy.retry`.

### Admin payments and audit (M3)

Admin only (401 without a token, 403 for a customer); read-only, so no `Idempotency-Key`. Newest
first, keyset on `(created_at DESC, id DESC)`, `limit` 1..100 (20), a bad cursor is 422
`cursor`. Details: `apps/api/src/csmarket/modules/admin/README.md`, **Payments and audit**.

- `GET /admin/payments?q=&status=&provider=&purpose=&cursor=&limit=` → `{items: [{id, number,
purpose, provider, amount_uzs, status, created_at, succeeded_at, user: {id, display_name}}],
next_cursor}`. `q` = a full or partial number (≤ 32 chars), any case, matched from the start (`T7K`).
  `status`, `provider`, `purpose` are enums (422 otherwise).
- `GET /admin/payments/{id}` → `{payment: row + {provider_ref, metadata}, topup: {number,
amount_uzs, status, expires_at, succeeded_at} | null, kassa: [{provider, external_id, status,
amount, amount_unit: "soum"|"tiyin", times: {created, performed, cancelled}, extra}]}`. Unknown
  or malformed id → 404. `extra` is an allow-listed string map; Uzum's payer phone is masked
  (`+998••••••67`), never whole.
- `GET /admin/audit?action=&target_type=&target_id=&actor_id=&cursor=&limit=` → `{items: [{id,
created_at, action, target_type, target_id, actor: {id, display_name}, payload}],
next_cursor}`. Filters are exact matches (≤ 64 chars each); a non-UUID `actor_id` is 422 `actor_id`.

### Admin catalogue (M2)

All under `/admin/skins`, admin only (401 without a token, 403 for a customer).

- `GET /admin/skins/catalog/status` — counts, newest price tick, last import / price-sync run,
  the CBU rate, `sync_enabled`, `waxpeer_key_set`.
- `GET /admin/skins/items?q=&hidden=&limit=` — find items, hidden ones included.
- `PATCH /admin/skins/items/{slug}` `{hidden}` — hide or show an item everywhere public.
- `GET /admin/skins/aliases`, `PUT /admin/skins/aliases/{alias}` `{text}`,
  `DELETE /admin/skins/aliases/{alias}` (204) — search aliases; alias one word of 1..64
  letters, digits or hyphens (no spaces), text 1..128, both stored lower-case.
- `PATCH`, `PUT` and `DELETE` take an `Idempotency-Key` (≥ 16 chars, optional here): a repeat replays the first response
  and writes nothing, including no second audit row. Every write is audited in
  `admin_audit_log`.

## Live order updates (M4b)

`WS /api/v1/realtime/orders` is not in OpenAPI. After the socket opens, send
`{"type":"auth","token":"<access token>"}` within 5 s; the server then sends
`{"type":"order.changed","number":"…"}` whenever one of your orders moves, and
`{"type":"ping"}` every 25 s. Close codes: **4401** — bad, revoked or expired token (at the
latest when the token expires; reconnect with a fresh one), **4429** — the `ws-connect`
ip_guard bucket (60 per minute per IP). A nudge carries no data: re-read
`GET /orders/{number}`. Keep polling as the fallback.

## Email confirmation (M4b)

Order letters go only to a confirmed address. `PATCH /me` with a new `email` resets
`email_verified` and queues a confirmation letter — one a minute per account: a second
address within that minute is saved but not mailed (`email_verification_sent_at: null`; the
user sends it from the profile later), and every email edit counts against the
`email-verify` bucket (10 a minute per IP and account, then 429).
`MeOut.email_verification_sent_at` says when the latest letter for the current address was
queued (`null` once confirmed or when none was sent).

- `POST /me/email/verification` (signed in; `Idempotency-Key` optional, a repeat replays
  202 and sends nothing): `202 {sent: true}`; 409 `email_missing` /
  `email_already_verified`; 429 `email_verify_cooldown` within 60 s of the last letter
  (`Retry-After`); 429 past the `email-verify` bucket (10 a minute per IP and account).
- `POST /email/confirm {token}` (anonymous — the link may be opened on another device;
  keyless: the token is single-purpose and the write idempotent): `200 {email_verified:
true}`, also when already confirmed; 422 `email_token_invalid` / `email_token_expired`
  (24 h); 409 `email_token_stale` when the account's email is no longer the token's. The
  `email-verify` bucket (60 a minute per IP) applies.

### Source callbacks: Skinslink (ADR-0010)

Called by Skinslink, not by our clients; anonymous, exempt from the per-IP limiter, not in the
OpenAPI schema.

- `POST /skinslink/webhook` — Skinslink's purchase / deposit status webhook. JSON body ≤ 4 KiB
  with `purchase_id` (or `trade_id`) and `sign`; authenticated by
  `sign == base64(sha256(str(id) + secret))` (constant time) before anything else is read.
  **200** `{ok: true}`; 403 `bad_signature` for a bad or missing `sign`; 400 `bad_body` for a
  body that is not a JSON object; **404 while Skinslink is off**.
- The signature covers only the id, so the body is **not trusted**: a purchase webhook queues a
  check and the worker reads the status from Skinslink's API; a deposit webhook (`trade_id`, ADR-0016) queues a check
  of the sale its `merchant_tx_id` names.
- No `Idempotency-Key`: a repeat queues one more check, and checks are idempotent. Details:
  `apps/api/src/csmarket/modules/skinslink/README.md`, `docs/runbooks/skinslink.md`.

## Selling skins (ADR-0016)

Signed in unless said. Money in whole soʻm as strings; a card by its type and last four.

- `GET /sell/config` — **public**: `enabled`, `balance_bonus_pct`, `card_fee_pct`,
  `card_min_uzs`, `min_sum_uzs` (a hint; `null` without a rate), `max_cards`.
- `GET /sell/inventory?refresh=1` — the items Skinslink accepts now at our prices, `max_items`,
  `min_sum_uzs`. Kept 5 minutes per user and trade link; `refresh` asks again. Rate-limited
  (`ip_guard` bucket `sell-inventory`). An advisory external call (AGENTS §11): 6 s, a 120 s
  breaker. 409 `sales_disabled` / `trade_link_missing` / `trade_link_bad` / `steam_refused`
  (+ `reason`: Skinslink's Steam account code); 503 `sales_unavailable` / `rate_unavailable`
  (no fresh soʻm rate).
- `POST /sell` — **`Idempotency-Key` required** (16..160); a replay answers 200 with the stored
  sale whatever the body. Body: `asset_ids`, `payout` (`{to: "balance"}` |
  `{to: "card", card_id}` | `{to: "card", new_card: {type, number}}`),
  `expected_payout_uzs` (the cart's figure; another is 409 `prices_changed`). Bucket
  `sell-create`. One `create-deposit` call (10 s) after the sale is committed. 409
  `prices_changed`, `below_minimum` (+ `min_sum_uzs`), `below_card_minimum`
  (+ `card_min_uzs`), `too_many_items` (+ `max_items`), `steam_refused`, `cards_limit`,
  `sales_disabled`, `trade_link_*`; 422 `card_invalid` (the number is never echoed); 404 a
  card that is not mine; 503 `sales_unavailable` / `rate_unavailable`. 201 `SaleOut`; a timeout
  answers `status: "creating"`. Two different keys make two sales (known gap,
  `docs/runbooks/sales.md`).
- `GET /sales?cursor=&status=`, `GET /sales/{number}` (`S…`; 404 for anyone else's),
  `GET /sales/pending` (`pending_uzs`: balance sales still in Steam's protection).
  `status` is optional and only `hold` is accepted (another value is 422): it keeps the sales in
  Steam's protection. Send the same `status` with the page's `cursor`. Each of a sale's
  `items[]` (`asset_id`, `name`, `image_url`, `price_uzs`) also carries `exterior` and
  `rarity_color` from our catalogue by market name — `null` for an item we do not list.
- `GET /payout-cards`; `DELETE /payout-cards/{id}` — `Idempotency-Key` required, but **no replay
  is stored**: the soft delete is its own replay (a repeat is a no-op 204).
- Socket: `{"type": "sale.updated", "number"}` on the order socket.
- Admin (`/admin/sales`): `GET /payouts?status=` (tabs with `counts`), `GET /payouts/{id}`,
  `POST /payouts/{id}/reveal {purpose: show|copy}` (**keyless on purpose**: it changes only the
  audit trail and a replay would store the number; audited on every call),
  `POST /payouts/{id}/paid {note?}` and `POST /payouts/{id}/reject {reason}` (keyed, audited;
  409 `payout_not_payable` unless `to_pay`; a reject credits the pre-fee amount to the seller's
  balance and shows the reason to the seller), `GET`/`PUT /settings` (keyed, audited
  `sales.settings.save`), `GET ""?status=&q=`, `GET /{number}`. The dashboard gains
  `payouts: {to_pay_count, to_pay_uzs}`.
- **422 shape (app-wide)**: a `RequestValidationError` handler (`bootstrap.py`) answers
  `{"detail": [{type, loc, msg}]}` and drops pydantic's `input` and `ctx`, so a request body
  (a card number, a trade link) is never echoed.

## Admin pricing and dashboard (M4b)

Admin only (401 without a token, 403 for a customer). Writes need `Idempotency-Key` (16–160);
a key reused for another body is 409 `idempotency_mismatch`. Details:
`apps/api/src/csmarket/modules/skins/README.md` «Pricing editor», `docs/runbooks/pricing.md`.

- `GET /admin/skins/pricing` → `PricingOut {rules, updated_at, updated_by: {id,
display_name} | null, items_active, items_overridden, rate_uzs}`.
- `PUT /admin/skins/pricing` body `PricingRules` → `PricingOut`. Reprices every active item in
  the same transaction and publishes the rules after the commit; an invalid document is 422
  with the validator's reason (brackets ascending from 0, liquidity bands descending to 0).
- `POST /admin/skins/pricing/preview` `{rules?, slug? | cost_usd + category, weapon?,
count_auto?, item_pp?, fixed_price_usd?}` → `PreviewOut` (every `Quote` component as a
  string, `price_uzs` at the current rate or `null`, `applied`). Keyless: it writes nothing.
  Neither a slug nor a cost and a category → 422; an unknown slug → 404.
- `PUT /admin/skins/items/{slug}/pricing` `{margin_override_pp: −100..500 | null,
fixed_price_usd: 0..100000 | null}` (2 decimals) → `AdminSkinItemOut` (now with `cost_usd`,
  `margin_override_pp`, `fixed_price_usd`). `GET /admin/skins/items?overridden=true` lists the
  items with either set.
- `GET /admin/dashboard?days=1|7|30` → `DashboardOut {days, since, sales {count, revenue_uzs,
revenue_usd, cost_usd, margin_usd, margin_percent}, refunds {count, amount_uzs}, in_flight,
attention, by_day [{day, sales_count, revenue_uzs, margin_usd}], waxpeer {balance_usd,
read_at}, skinslink {available_usd, hold_usd, read_at}, lisskins {available_usd, locked_usd,
read_at}}` (a balance is `null` when unknown; `attention` counts every source); days are Tashkent days; any other `days` is 422 `dashboard_days`. Reads only.
