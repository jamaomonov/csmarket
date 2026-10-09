# Runbook — public API

Spec: `docs/superpowers/specs/2026-10-09-public-api-design.md`; ADR-0017. It covers the
USD wallet, keys, the feed, buying, webhooks and the admin pages. The contract is
[`docs/api/public-v1.md`](../api/public-v1.md).

## USD-кошелёк

Dollar balance for API clients and for users an admin chose. Amounts are integer milli-USD
(1000 = $1) in the ledger, strings with three decimals in the API.

### Switching on and off

Admin → «Пользователи» → the card → the USD block → «Включить» / «Выключить» with a reason
(audited `wallet.usd_switch`). On: the balance page shows «USD-кошелёк» and conversion works.
Off: conversion and API purchases stop; **the dollars stay** on the account and show in the card.

### A balance left after switching off

Nothing is lost or moved. Either switch it on again, or debit it by hand (the adjust form,
dollars, a negative amount, a reason) after paying the client out outside the system. There is no
dollars-to-soʻm conversion.

### Crediting a client (YuPay) by hand

Card → the adjust form → the currency toggle «USD» → amount → reason (4..500 chars) → apply.
Books D `user_wallet_usd` / C `house_adjustments_usd` (`admin_adjust_usd`), audited
`wallet.adjust_usd`, at most 100 000 $ per step, never below zero. Only a dot is a decimal
separator: type `1000` or `1000.5`; a comma is refused («Только точка»). The confirm button
groups digits (`$1 000.000`).

### What was converted (`house_fx_*`)

Each conversion adds soʻm to `house_fx_uzs` (debit-normal) and milli-USD to `house_fx_usd`
(credit-normal). Sums per currency:

```sql
SELECT a.kind, a.currency,
       COALESCE(SUM(p.amount) FILTER (WHERE p.direction = 'D'), 0)  AS debit,
       COALESCE(SUM(p.amount) FILTER (WHERE p.direction = 'C'), 0) AS credit
FROM wallet_accounts a
LEFT JOIN wallet_postings p ON p.account_id = a.id
WHERE a.kind IN ('house_fx_uzs', 'house_fx_usd')
GROUP BY a.kind, a.currency;
```

`house_fx_uzs` debits = soʻm taken from customers; `house_fx_usd` credits = milli-USD issued
(divide by 1000 for dollars). The implied average rate is the first over the second ×1000. Each
transaction's metadata keeps its rate and rate snapshot. Columns match
`apps/api/src/csmarket/modules/wallet/models.py` (`direction` is D or C).

## SQL access

Prod: `docker compose -f docker-compose.prod.yml exec postgres psql -U <user> <db>` (dev:
`make psql`). **Never paste a Steam ID, a user id or a trade link into chat or a ticket**; put
the value into a psql variable and print only what you need.

Find the user id of a customer without echoing it:

```sql
-- type the real Steam ID in your terminal only; keep the comment off the \set line
\set sid '7656119XXXXXXXXXX'
SELECT u.id IS NOT NULL AS found, k.id AS key_id, k.pricing_profile, k.created_at, k.last_used_at
FROM users u LEFT JOIN api_keys k ON k.user_id = u.id AND k.revoked_at IS NULL
WHERE u.steam_id = :'sid';
```

`key_id` (a uuid) is what logs and alerts carry; it names no person.

## Set a tariff

Admin → «API-ключи» → the key → the tariff switch (`retail` or `cost`) with a reason (audited
`api_keys.tariff` `{from, to, reason}`). The tariff is not shown to the customer on the site.
`retail` is the storefront price, `cost` is the supplier cost (csmarket earns nothing on it: only
for YuPay). It applies from the next order; placed orders keep their price. A reissue carries it
over. The same tariff is refused (409 `tariff_unchanged`), and so is a revoked key (409
`api_key_revoked`: find the owner's live key in the list). **Do not change it in SQL.**

The list shows each key's orders, revenue and cost (refunded orders left out); the card shows
the latest 20 orders and the webhook host with its last delivery.

## Revoke a key

The customer revokes or reissues it on the site (profile → «API-ключ»). For a leaked key or an
abuse, an operator uses admin → «API-ключи» → the key → «Отозвать» with a reason (audited
`api_keys.revoke`); the key stops working on the next call (auth reads the database each time).
SQL is only the fallback if the admin is down:

```sql
\set sid '7656119XXXXXXXXXX'
UPDATE api_keys SET revoked_at = now()
WHERE user_id = (SELECT id FROM users WHERE steam_id = :'sid') AND revoked_at IS NULL;
```

Never `DELETE` a key: `orders.api_key_id` is RESTRICT and old orders must stay readable. The
customer can issue a new key afterwards (the tariff carries over from the user's newest key, revoked or
not, so a `cost` client stays `cost`). To cut an account off
entirely, ban the user in the admin («Пользователи»): the key answers 403 `account_suspended`.
The IP allow-list is the customer's to set (see «The IP allow-list» below); SQL is only a
fallback: `UPDATE api_keys SET ip_allowlist = ARRAY['203.0.113.0/24']::varchar[] WHERE id =
'<key_id>';` (empty array = any address).

## A stuck or disputed API order

An API order is a normal paid order in the worker's eyes; the client sees `buying` until the
supplier answers. Find it by the client's `client_order_id`:

```sql
SELECT number, status, failure_reason, refunded_at, created_at, trade_sent_at
FROM orders
WHERE channel = 'api' AND client_order_id = 'shop-1042';
```

- `buying` for a long time: it is the same case as a stuck site order, read
  [`orders.md`](./orders.md) (attention on the trade, the lease, lookup-before-buy) and the
  source's runbook ([`skinslink.md`](./skinslink.md), [`lisskins.md`](./lisskins.md)). An order
  `failed` / `returned` without a refund is **held for support** and still reads `buying` to the
  client until a person settles it in the admin («Заказы» → the order).
- A refund books to the **USD wallet** (`refund:order:usd:{order_id}`), once, with the reason the
  client reads (`sold_out`, `invalid_trade_link`, `trade_hold`, `supplier_refused`,
  `cancelled_by_support`; `price_moved` is reserved and not produced yet). Never refund by
  hand-editing the ledger.
- **A held order of any source** is settled from the admin («Заказы» → the order → «Вернуть
  деньги на баланс»); for Skinslink / LIS-SKINS see the next section.
- A delivered skin is never refunded automatically. A dispute over a delivered order is a
  decision for the owner.
- «внимание» on the order in the admin: handle it as for a site order (`orders.md`).
- Duplicate complaints: a repeated `client_order_id` answered 409 `duplicate_client_order_id`
  and charged nothing; check there is exactly one `orders` row for it.
- `402 insufficient_balance` from the client is the dollar balance; credit it by hand as above.

## Refund of a Skinslink / LIS-SKINS order

Site or API order, ADR-0018. Press «Вернуть деньги на баланс» in the admin (the button is hidden
while the stored status shows the purchase plainly alive). The API asks the supplier **once**
(4 s, no lock held) and books only when it confirms the purchase did not happen:

- Skinslink `failed` / `canceled` for our `merchant_tx_id` and purchase id;
- LIS-SKINS `return` that is not a rollback, for every skin of ours in the answer, every entry
  readable and the ids matching;
- an empty answer, for a row older than 10 minutes with no market purchase id and no lost buy
  answer.

Anything else is **409 `order_in_flight`** («Скин ещё в пути»): the skin may still reach the
buyer, do not force it; wait or look in the supplier cabinet. Other refusals: **409 `order_busy`** (another action holds the order, try again),
**409 `order_needs_attention`** (the order is on the attention path, not this button) and
**409 `already_refunded`** (nothing to do). A failed or slow lookup is **409
`source_unavailable`**: nothing was booked, try again in a minute. A `trade_sent` order becomes
`returned`, a `buying` one `failed`; an API client reads `refunded` with
`cancelled_by_support`, and the money goes to the USD wallet, once. A `reverted` Skinslink order
or a LIS-SKINS rollback return means the skin was taken back after it was accepted: it stays with
the attention path, not this button. Retry still refuses these sources.

If every Skinslink refund answers `order_in_flight`, check that Skinslink's status body still
carries `merchant_tx_id`; the refund matches on it.

## A webhook does not arrive

A client says it gets no events (or too many). Look at the delivery rows by **order number** and
never print the URL (`api_webhooks.url` is the partner's address; admin shows the host only):

```sql
SELECT d.event, d.status, d.attempts, d.last_status_code, d.last_error,
       d.next_attempt_at, d.sent_at
FROM api_webhook_deliveries d JOIN orders o ON o.id = d.order_id
WHERE o.number = 'A1B2C3D4'
ORDER BY d.created_at;
```

- `pending` with a future `next_attempt_at`: the retry schedule is 1 m, 5 m, 30 m, 2 h, then
  every 2 h, 10 attempts in all. `last_status_code` is the partner's answer; `last_error` is
  `http_<code>`, `timeout`, `connect`, `private` or `invalid`.
- `private`: the URL's host now resolves to a non-public address. The partner fixes DNS or sets
  a new URL; the row retries on its own.
- `invalid`: the stored URL no longer passes the URL check (retried, like `private`); the
  partner sets a new URL.
- `exhausted` (status `failed`): the last attempt crashed before it recorded an outcome; look at
  the worker's log for that delivery id.
- `failed` with `no_key` or `no_webhook`: the key was revoked or the webhook removed. After 10
  attempts a delivery stays `failed`; there is no resend (`docs/tech-debt.md`). The client reads
  the order with `GET /public/orders/{id}`.
- No row for an event: no webhook was set when the order moved, the order is a site order, or
  that status event was skipped (an order may go `buying` → `delivered`). One row per
  (order, event) at most.
- A signature mismatch on the client side: after a **reissue** the signing key changed at once.
  The client must hash the new token; also the body must be checked as raw bytes.
- The worker is not draining: check `api_webhooks` in the worker's log and queue; the outcome
  counter `csmarket_api_webhooks_total{event,outcome}`. Log lines carry the delivery id, event,
  outcome and host, never the URL.

## The feed answers 503 `feed_unavailable`

The feed is a Redis snapshot rebuilt by the scheduler job `public_api.feed` every 60 s;
`public_api:feed:current` lives 1500 s. A scheduler restart alone keeps serving the old snapshot.
The 503 (`Retry-After: 60`) appears only on a cold Redis (a flush) or after the scheduler was
down for more than ~25 minutes: the first build then runs **~400 s** after the scheduler starts.
This is expected, not an incident. Clients retry.

If it lasts longer than ~10 minutes after the scheduler is up: check its log for
`public_api.feed.built` / `public_api.feed` errors; check Redis (`GET public_api:feed:current`
should exist, TTL ≤ 1500 s) and that some items have Skinslink or LIS-SKINS stock. Do not restart
the scheduler to force a run: that re-arms the ~400 s delay. Check and wait (the logic is
`public_api.feed.build_snapshot`).
`409 cursor_expired` is normal when a client holds a cursor longer than 1800 s: it restarts from
the first page. A page 0 revalidation counts as the once-a-minute `feed` limit (429), by design.

## Raising a key's limits

Per key and minute: 60 reads, 10 orders, 1 feed first page, 30 trade-link checks by default
(`public_api:rl:{bucket}:{key_id}`, buckets `read`, `order`, `feed`, `check`). A client who
needs more: admin → «API-ключи» → the key → «Лимиты» → enter the number (1–10 000) or leave a
field empty for the default; audited as `api_keys.limits` `{from, to}`. It applies on the next
call (the key row is read each time) and a reissue carries it over. YuPay runs at 600 reads /
30 orders / 1 feed. The card also shows the key's IP allow-list, read-only.
A temporary throttle is lifted by deleting the client's Redis counter key (counters only;
nothing else is stored under them). Failed authentications are 30 a minute per address
(`public_api:authfail:{hash_short(ip)}`).

## The IP allow-list

The customer sets it in the profile («API-ключ» → «Разрешённые IP-адреса»): up to 20 IPv4 /
IPv6 addresses or CIDRs, empty = any address. A bad entry is refused with 422
`ip_allowlist_invalid` naming its index. The admin sees the list on the key's card but does
not edit it. A client locked out by a wrong list clears or fixes it in the profile; if the
site is out of reach for them, use the SQL fallback in «Revoke a key». Addresses are PII-grade:
never put one in a ticket or a log.

## An API order buying for over 30 minutes

Alert `PublicApiOrderBuyingLong` (warn): the gauge
`csmarket_public_api_orders_buying_oldest_seconds` (the age of the oldest paid API order still
`buying`) has been over 1800 s for 5 minutes. It is not an error by itself: `buying` lasts as
long as the market takes to answer.

1. Find the order (admin → «Заказы», channel API, or the SQL in «A stuck or disputed API
   order») and read its purchase and the attention reason.
2. **Never buy again by hand.** The worker keys the buy by our own id and resolves a lost answer
   by lookup; a second buy would pay twice.
3. The outcome comes from the market: a delivered skin finishes the order; a refusal or
   cancellation books the refund. Refund by hand only through the admin and only on the
   market's refusal (see the next sections). A rollback after delivery is not refunded.
4. If the market is down for everyone, wait: the gauge returns to 0 when the orders settle.

## The trade-link check answers only `unavailable`

`POST /public/tradelink/check` returns `unavailable` when the check could not run; it never
blocks a purchase. If every call answers so: the Waxpeer key is missing or rejected
(`CSMARKET_WAXPEER_API_KEY` in `secrets/api.env`; the key must be whitelisted for the VPS IP,
`waxpeer.md`) or Waxpeer is down, and the breaker is open for its cool-down (look for the
breaker key in Redis and the `users.tradelink.unavailable` warnings in the API log). Fix the key or wait;
no restart is needed. The bucket `check` limits calls per key (`public_api:rl:check:{key_id}`).

## Releasing v1.1

On the owner's word, in this order:

1. Check the Waxpeer key is set, without printing it:
   `grep -c '^CSMARKET_WAXPEER_API_KEY=.\+' secrets/api.env` (expect `1`), and that the VPS IP
   is whitelisted at Waxpeer. Without either, every trade-link check answers `unavailable`
   (documented behaviour; purchases are not blocked).
2. Smoke-test one call with a fake link (`partner=1&token=FAKEFAKE`): expect `bad` /
   `invalid_link` or `unavailable`. Then one real link the owner supplies out of band.
3. Turn on alerts: `secrets/alertmanager.env` filled by the owner, `COMPOSE_PROFILES=alerts`
   in the checkout's `.env`, `docker compose -f docker-compose.prod.yml up -d alertmanager`,
   then an `amtool` test alert (`first-deploy.md`, step 9a).
4. Set YuPay's limits in the admin: 600 reads, 30 orders, 1 feed per minute (the default
   check limit stays).

## The partner docs at docs.csmarket.uz

Static files in `infra/docs-site`, served by the app stack's Caddy from `/srv/docs` (a directory
mount, so every deploy's checkout shows through without a restart).

- `/` is a hand-written landing page (`index.html`, `landing.js`): cards for the guide, the
  reference, webhooks, Postman, `llms.txt` and the SDK (marked «Soon»).
- `openapi.json`, `llms.txt` and `csmarket.postman_collection.json` are generated by
  `make gen-api` (`csmarket.scripts.export_public_docs`, `…postman`) from the app's schema
  (`/api/v1/public/*` only) and the guide `docs/api/partner-guide.md` (its `#` headings become the
  sidebar's guide sections). The request-body examples (fake values) live in `EXAMPLES` in the
  exporter. Edit the guide, the examples or the route docstrings, never the generated files; CI's
  openapi-drift job checks them.
- `/reference/` (`reference/index.html` + `reference/init.js`) loads Scalar from jsdelivr, pinned
  with an SRI hash. To bump it: change the version in `reference/index.html`, then
  `curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A` for the new `integrity`.
- The guide is public: no internals (ADR, runbooks, admin flows, the source of a skin). Every
  example uses fake values (`csm_EXAMPLEtokenNotReal`, `partner=1&token=FAKEFAKE`).
- "Test Request" calls `https://api.csmarket.uz` from the page: the server's `secrets/api.env`
  lists `https://docs.csmarket.uz` in `CSMARKET_CORS_ALLOW_ORIGINS`. Without it the page still
  reads, only the button fails (a CORS error in the browser console).
- `X-Robots-Tag: noindex` follows the storefront's indexing gate (`docs/runbooks/indexing.md`).
