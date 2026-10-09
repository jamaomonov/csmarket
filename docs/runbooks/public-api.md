# Runbook — public API

Spec: `docs/superpowers/specs/2026-10-09-public-api-design.md`; ADR-0017. This file grows with
plan C; today it covers the USD wallet and plan B (keys, the feed and buying). The contract is
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

## Set a tariff (until plan C's admin page)

The tariff is not shown to the customer on the site. `retail` is the storefront price, `cost` is
the supplier cost (csmarket earns nothing on it: only for YuPay). It applies to the live key at
once (the next call), and a reissue carries it over.

```sql
\set sid '7656119XXXXXXXXXX'
UPDATE api_keys SET pricing_profile = 'cost'
WHERE user_id = (SELECT id FROM users WHERE steam_id = :'sid') AND revoked_at IS NULL;
-- back to the default: SET pricing_profile = 'retail'
```

It must report `UPDATE 1`; `UPDATE 0` means the user has no live key yet (they issue one first).
The value is checked by the table (`retail` | `cost`).

## Revoke a key

The customer revokes or reissues it on the site (profile → «API-ключ»). For a leaked key or an
abuse, an operator does the same in SQL; the key stops working on the next call (auth reads the
database each time):

```sql
\set sid '7656119XXXXXXXXXX'
UPDATE api_keys SET revoked_at = now()
WHERE user_id = (SELECT id FROM users WHERE steam_id = :'sid') AND revoked_at IS NULL;
```

Never `DELETE` a key: `orders.api_key_id` is RESTRICT and old orders must stay readable. The
customer can issue a new key afterwards (it carries the tariff over only from a live key, so a
revoked `cost` key's replacement starts as `retail`: set the tariff again). To cut an account off
entirely, ban the user in the admin («Пользователи»): the key answers 403 `account_suspended`.
An IP allow-list is set the same way, with CIDRs: `UPDATE api_keys SET ip_allowlist =
ARRAY['203.0.113.0/24']::varchar[] WHERE id = '<key_id>';` (empty array = any address).

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
  client reads (`sold_out`, `invalid_trade_link`, `trade_hold`, `price_moved`,
  `supplier_refused`, `cancelled_by_support`). Never refund by hand-editing the ledger: use the
  order's admin refund.
- A delivered skin is never refunded automatically. A dispute over a delivered order is a
  decision for the owner.
- «внимание» on the order in the admin: handle it as for a site order (`orders.md`).
- Duplicate complaints: a repeated `client_order_id` answered 409 `duplicate_client_order_id`
  and charged nothing; check there is exactly one `orders` row for it.
- `402 insufficient_balance` from the client is the dollar balance; credit it by hand as above.

## The feed answers 503 `feed_unavailable`

The feed is a Redis snapshot rebuilt by the scheduler job `public_api.feed` every 60 s. After a
scheduler restart (or a Redis flush) the first build runs **~400 s later**, and until then the
first page answers 503 with `Retry-After: 60`; this is expected, not an incident. Clients retry.

If it lasts longer than ~10 minutes: check the scheduler is up and its log for
`public_api.feed.built` / `public_api.feed` errors; check Redis (`GET public_api:feed:current`
should exist, TTL ≤ 1500 s) and that some items have Skinslink or LIS-SKINS stock. Run the job
by restarting the scheduler (it only times work; the logic is `public_api.feed.build_snapshot`).
`409 cursor_expired` is normal when a client holds a cursor longer than 1800 s: it restarts from
the first page. A page 0 revalidation counts as the once-a-minute `feed` limit (429), by design.

## Limits and throttles

Per key: 60 reads, 10 orders, 1 feed first page a minute (`public_api:rl:{bucket}:{key_id}`);
failed authentications 30 a minute per address (`public_api:authfail:{ip}`). To lift a throttle
for a client, delete its Redis counter key (counters only; nothing else is stored under them).
