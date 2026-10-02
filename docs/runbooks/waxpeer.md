# Runbook — Waxpeer (our only supply)

Every order is bought at Waxpeer with our Waxpeer balance, and Waxpeer's seller sends the skin
to the buyer. This runbook covers the API key and its IP whitelist, the balance, the alerts
that point here, the dev fake versus the real key, and the checks still owed. Orders and the
admin actions: [`orders.md`](./orders.md). Catalogue and price sync:
[`skins-catalogue.md`](./skins-catalogue.md). Code: `apps/api/src/csmarket/modules/skins/README.md`
(«Buying at Waxpeer»); design: ADR-0007.

## What we call

| Call                            | Who                                  | How often                                                   |
| ------------------------------- | ------------------------------------ | ----------------------------------------------------------- |
| `GET /v1/check-many-project-id` | worker (before every buy), scheduler | reconcile every 10 s (≤ 100 orders a call), hourly, nightly |
| `GET /v1/buy-one-p2p`           | worker, reconcile (a pending buy)    | once per order (one substitute at most)                     |
| `GET /v1/user` (balance)        | scheduler `orders.health`; the buy   | every 5 min; on a buy refusal                               |
| `GET /v2/search-items-by-name`  | API (item page, checkout), worker    | cached 90 s, ≤ 18 a minute shared (Redis budget)            |
| price snapshot, `/v1/prices`    | scheduler `skins.price_sync`         | every 5 min                                                 |

Every call is counted in `csmarket_waxpeer_calls_total{endpoint, outcome}`
([`metrics.md`](../architecture/metrics.md)). The key and the trade link ride the query
string, so a Waxpeer URL, its body and its error text are never logged.

## The key and its IP whitelist

- Waxpeer accepts our key **only from the IPs whitelisted on the Waxpeer account**: the VPS's
  public egress IP in prod. A call from anywhere else gets **HTTP 403**.
- The key lives **only** in `secrets/api.env` on the server (`CSMARKET_WAXPEER_API_KEY`, read
  by the api, worker and scheduler) and, for the owner's local work, in the owner's own
  `.env` at the repo root (git-ignored). **Never in chat, a commit, a doc, an issue or a
  test.** A key that was pasted anywhere else is rotated at Waxpeer.
- For local work the owner may whitelist their own IP too and put that key in their local
  `.env` themselves — agents never ask for it, never write it.
- A new server or a changed egress IP (provider migration, a NAT change) means a new
  whitelist entry **before** the deploy goes live, or every buy and lookup answers 403.

Find the server's egress IP from the server itself:

```bash
curl -s https://ifconfig.me; echo
```

After changing the key: `docker compose -f docker-compose.prod.yml up -d api worker scheduler`
(never `restart`: it keeps the old environment — [`deploy.md`](./deploy.md)).

## Forbidden

`WaxpeerForbidden` (page): an order's lookup or buy got **HTTP 403** in the last 10 minutes.
It is a configuration error, never "sold out", so **nothing is refunded**: the order stays
`buying` with its buy pending, the trade gets the attention `waxpeer_forbidden` («Waxpeer:
IP не в белом списке»), and the reconcile sweep retries it every 60 s.

1. Compare the server's egress IP (above) with the whitelist in the Waxpeer cabinet. Fix it.
2. Check the key is the current one in `secrets/api.env` (a rotated or wrong key fails
   every call too); recreate the services if you changed it.
3. Watch `csmarket_waxpeer_calls_total{outcome="ok"}` grow again. The next attempt looks the
   order up, buys (or adopts what is there) and **clears the attention by itself**. No
   restart and no admin action is needed.
4. During the outage refund and retry of these orders answer «Покупка ещё идёт — попробуйте
   через минуту.» (`order_busy`) inside each 60 s backoff: fix the whitelist first. Refunding
   one anyway: [`orders.md#forbidden-then-refunded`](./orders.md#forbidden-then-refunded).

A 403 on a trade already bought (`trade_sent`) is a lookup failure: nothing is written, the
order waits, and `TradesUnpolled` fires after 30 minutes ([`orders.md#trades-unpolled`](./orders.md#trades-unpolled)).
The price sync logs `skins.prices.failed` at the same time.

## Balance low

Two alerts point here:

- `WaxpeerBalanceLow` (page): `csmarket_waxpeer_balance_usd` has been below
  `CSMARKET_WAXPEER_BALANCE_ALERT_USD` (default 50) for 10 minutes. The next buys will fail.
- `WaxpeerLowBalanceRefund` (page): an order **was** refunded because our balance did not
  cover it (`csmarket_order_refunds_total{reason="waxpeer_low_balance"}`).

What happens on a short balance: when Waxpeer refuses a buy and the refusal names the
balance, or `GET /v1/user` shows less than the price, the order goes `failed` and the money
goes back to the buyer's balance **at once** (owner's choice: never stall a paid order). The
buyer reads «Не получилось купить скин — деньги на балансе. Попробуйте через несколько
минут.»

1. **Top up the Waxpeer balance** in the Waxpeer cabinet (the owner's account).
2. Watch `csmarket_waxpeer_balance_usd` rise on the next read (every 5 minutes).
3. **Do not retry** the refunded orders: the money is already back, so «Повторить» is
   refused (`not_retryable`); the buyer buys again.

Keep the balance comfortably above the most expensive skin likely to sell plus a day of
sales; the threshold is a setting, not a rule.

## Balance unknown

`WaxpeerBalanceUnknown` (warn) has two causes (label `cause`):

- `never_read`: the scheduler has exported no balance for 30 minutes. It fires **30 minutes
  after the scheduler starts on a box with no Waxpeer key and no fake** — expected there
  (nothing reads the balance). In prod: the key is missing or wrong, Waxpeer is down, or
  the scheduler is gone (see `SchedulerDown`).
- `stale_read`: the last successful read is over 30 minutes old, so `WaxpeerBalanceLow` is
  judging an old number.

Look for `orders.health.balance_failed` in the scheduler log (it names the error type), and
`csmarket_waxpeer_calls_total{endpoint="balance"}` by outcome: `forbidden` → [Forbidden](#forbidden);
`unavailable` → Waxpeer down or the key missing. Check the balance in the Waxpeer cabinet by
hand meanwhile.

## The dev fake versus the real key

- **The dev compose runs with `CSMARKET_WAXPEER_FAKE=true`** (ruling R13): the worker,
  scheduler and API use a fake Waxpeer whose trades live in Redis. A local buy spends
  nothing; the fake "sends" the offer 6 s after the buy, and
  `POST /api/v1/dev/orders/{number}/trade {accept|decline|rollback}` drives the rest
  ([`local-setup.md`](../onboarding/local-setup.md#buying-locally-the-waxpeer-fake)). Prod
  refuses to start with the fake on.
- **The price sync is not faked** (ruling T): with a key in `.env` and the sync enabled, dev
  prices come from the real Waxpeer while buys go to the fake.
- **With the real key in `.env` and `CSMARKET_WAXPEER_FAKE=false`, a local buy is a REAL
  purchase with the shop's real Waxpeer money**, delivered to whatever trade link the test
  account saved. Do it only on purpose, with a cheap skin and your own trade link.
- The reconcile sweep's first run is about 240 s after the scheduler starts — ~24 s under the
  dev compose, which divides first runs by 10 (`CSMARKET_SCHEDULER_FIRST_RUN_DIVISOR`, dev
  only; prod refuses it). Run e2e (`make test-e2e`) about a minute after `make dev`. A
  rollback on a delivered order shows only after the hourly protection watch (first run at
  280 s, 28 s in the dev compose).

## Test buys after the deploy (M5)

Before buying is switched on for customers (`CSMARKET_SKINS_BUY_ENABLED=true`):

1. The key is whitelisted for the VPS IP, the Waxpeer balance is funded,
   `csmarket_waxpeer_balance_usd` reads it and no Waxpeer alert is firing.
2. Credit a test account (an admin's own) through «Изменить баланс» with a reason.
3. **Buy 1 — decline:** buy a cheap skin from the balance, decline the offer in Steam. The
   order goes `trade_sent` → `returned`, the balance is credited back once («Возврат на
   баланс»).
4. **Buy 2 — accept:** buy another, accept it. The order goes `delivered`; the admin
   «Обмен» block shows the Waxpeer id, the seller and the protection date.
5. Take the test balance back with a clawback adjustment naming both order numbers.

## Still owed

- **Orphan buys** (a Waxpeer purchase with no order of ours) are not detected: the nightly
  audit reads trades back by our own `project_id`. Detecting them needs Waxpeer's
  `my-history`, whose answer shape was never captured. M4b probes it once with the owner's
  locally whitelisted key, then extends the audit.
- **A refused buy followed by a substitute under the same `project_id`** has not been seen
  against the real Waxpeer. The code picks our trade by the Waxpeer id the buy returned, so a
  refused attempt under the same key is ignored; if Waxpeer rejects a reused key, the
  substitute is simply refused and the order refunds (`sold_out`).
