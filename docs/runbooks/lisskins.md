# Runbook — LIS-SKINS (the third buy source)

LIS-SKINS sells CS2 skins beside Skinslink. Every 5 minutes we take a snapshot of its instant
lots from its public price export, show them next to Skinslink's, and buy from it with our
LIS-SKINS balance when the buyer picked one of its lots. LIS-SKINS' bot sends the skin to the
buyer's trade link. There is no webhook: the scheduler polls purchase statuses every 30 s.
This runbook covers the key, switching it on and off, the balance and the alerts that point
here. Orders and admin actions: [`orders.md`](./orders.md). Skinslink:
[`skinslink.md`](./skinslink.md). Code: `apps/api/src/csmarket/modules/lisskins/README.md`;
design: [ADR-0012](../decisions/0012-lisskins-buy-source.md); flow:
[`lisskins-buy.mmd`](../architecture/sequence-diagrams/lisskins-buy.mmd).

## What we call

| Call                                                      | Who                                           | How often                                                  |
| --------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------- |
| `GET lis-skins.com/market_export_json/api_csgo_full.json` | scheduler `lisskins.snapshot`                 | every 5 min (~855 MB, streamed; no key)                    |
| `GET /market/check-availability?ids[]=…`                  | API, `POST /orders` for a chosen `ls:` lot    | once per checkout; ≤ 100/min for the API; 120 s breaker    |
| `POST /market/buy`                                        | worker (`orders` queue), `lisskins.reconcile` | once per order                                             |
| `GET /market/info?custom_ids[]=…`                         | scheduler `lisskins.reconcile`, the buy       | one call every 30 s for up to 200 purchases; on a known id |
| `GET /user/balance`                                       | scheduler `lisskins.balance`                  | every 5 min                                                |

LIS-SKINS allows 200 requests a minute per key (`market/buy` 500); a 429 carries
`Retry-After`. Every call is counted in `csmarket_lisskins_calls_total{endpoint, outcome}`
(`endpoint` = `export`, `check`, `buy`, `info`, `balance`;
[`metrics.md`](../architecture/metrics.md)). The key rides `Authorization: Bearer`; the trade
link travels as `partner` + `token` in the `market/buy` body. Error bodies are never logged.

## Credentials

- One value: `CSMARKET_LISSKINS_API_KEY`, from the LIS-SKINS cabinet.
- It lives **only** in `secrets/api.env` on the server (read by the api, worker and
  scheduler). **Never in chat, a commit, a doc, an issue or a test.** It is on the log
  redaction list (`lisskins_api_key`, `authorization`).
- The key answers only from the VPS, **`57.131.198.69`**. A new server or a changed egress IP
  needs the key re-bound in the cabinet first. Check the egress IP from the server:
  `curl -s https://ifconfig.me; echo`.
- Rotation: issue a new key in the cabinet, replace the line, then
  `docker compose -f docker-compose.prod.yml up -d api worker scheduler` (never `restart`: it
  keeps the old environment — [`deploy.md`](./deploy.md)). Open orders settle under their
  `custom_id` with the new key.

## Enabling

1. The key is in `secrets/api.env`; the LIS-SKINS balance is topped up.
2. In `secrets/api.env`: `CSMARKET_LISSKINS_ENABLED=true`. LIS-SKINS is used only when the
   switch is on **and** the key is set (`lisskins_active`).
3. Restart with the deployed tag (the one pinned in `~/opt/csmarket/.env`, never another):
   `IMAGE_TAG=<tag> docker compose -f docker-compose.prod.yml up -d api worker scheduler`.
4. Watch the scheduler. The first snapshot lands after ~5–9 minutes (first run 320 s after
   start, then the download): `lisskins.snapshot.applied lots=… items=…`. The next
   `sources.prices` tick (≤ 2 min) puts LIS-SKINS prices on the catalogue.
   `csmarket_lisskins_enabled` reads 1 after the first balance tick (360 s); the admin
   dashboard shows the «LIS-SKINS» balance.
5. The first test buy: an admin's own account, credited through «Изменить баланс», buys one
   cheap LIS-SKINS lot to a test trade link (the admin order page shows
   «Источник: LIS-SKINS · ls:…»). Watch the worker's `orders.lisskins_buy number=…
outcome=bought`, then the scheduler's `lisskins.reconcile.tick` and the order moving to
   `trade_sent`; accept in Steam and see `delivered`. Check the balance tile dropped. Take the
   test balance back with a clawback naming the order.

## Snapshot stale

`LisskinsSnapshotStale` (warn): the applied export is over 20 minutes old (by the export's own
`last_update`). LIS-SKINS lots and prices are off the storefront until a fresh one is applied
(a stale snapshot sells nothing); the next `sources.prices` tick (≤ 2 min) deactivates items
only LIS-SKINS had. Skinslink is unaffected. Open LIS-SKINS orders keep moving: the reconcile
does not use the snapshot.

1. The scheduler log, every 5 minutes:
   - `lisskins.snapshot.failed error=<type>` — the export could not be read whole
     (transport, a non-200, a cut body, not `"status": "success"`). Nothing was written.
   - `lisskins.snapshot.refused lots=… before=…` — the export held under half of the last
     applied tick's lots. Nothing was written.
2. Does the export answer from the VPS? Its CDN wants a browser-like agent:

   ```bash
   curl -sI -A 'Mozilla/5.0 (compatible; csmarket.uz)' \
     https://lis-skins.com/market_export_json/api_csgo_full.json
   ```

   Not 200 → LIS-SKINS' side; wait. `csmarket_lisskins_calls_total{endpoint="export"}` by
   outcome shows the same.

3. A refused tick: wait one more tick (a half-written export usually heals). If it keeps
   refusing, compare the `before` count with `lots` in `lisskins_state`:

   ```bash
   docker compose -f docker-compose.prod.yml exec postgres psql -U <user> -d <db> -c \
     "select snapshot_at, synced_at, lots from lisskins_state"
   ```

   If LIS-SKINS' market really shrank by half, every tick will refuse until the baseline
   moves. Ask the owner, then `update lisskins_state set lots = 0 where id = 1` lets the next
   tick apply whatever the export holds.

4. The alert clears once a tick is applied; the next `sources.prices` tick puts the prices
   back.

## Balance low

`LisskinsBalanceLow` (page): `csmarket_lisskins_balance_available_usd` has been below
`CSMARKET_LISSKINS_BALANCE_ALERT_USD` (default 100) for 10 minutes. `WaxpeerLowBalanceRefund`
fires for every source: it counts refunds with reason `source_low_balance`.

On a short balance LIS-SKINS refuses the buy with `insufficient_funds`; the order goes
`failed` and the money goes back to the buyer's balance **at once** (`source_low_balance`).

1. **Top up the LIS-SKINS balance** in its cabinet (the owner's account).
2. Watch `csmarket_lisskins_balance_available_usd` rise on the next read (every 5 minutes).
   The admin dashboard shows the same («LIS-SKINS»: available and locked).
3. **Do not retry** the refunded orders: the money is already back.

The `locked` part is money in open purchases.

## Buy failures

`LisskinsBuyFailures` (warn): more than five `market/buy` calls were refused, forbidden or
unanswered in 15 minutes (worker and reconcile together). One sold lot is normal; a run is the
key, the IP, the balance or LIS-SKINS itself.

1. The worker log: `orders.lisskins_buy number=… outcome=…`; refusals log
   `lisskins.refused endpoint=buy status=… code=…`.
2. `csmarket_lisskins_calls_total{endpoint="buy"}` by outcome:
   - `forbidden` (401 / 403): the key is wrong, revoked or missing
     (`CSMARKET_LISSKINS_API_KEY` empty), or the call did not come from `57.131.198.69`. The order stays `buying` with the buy pending and the attention
     `source_forbidden`; nothing is refunded. Fix the key or the IP; the reconcile buys again
     (same `custom_id`, never a second purchase) and clears the attention.
   - `unavailable` (timeout, 5xx, network): the buy may have gone through. The order keeps
     `buy_unconfirmed_at`; the reconcile asks `market/info` under the same `custom_id` and
     adopts what is there. If nothing shows after `order_unconfirmed_minutes` (10), the buy
     is sent again under the **same** `custom_id` (log `orders.lisskins.repeat_unseen`):
     LIS-SKINS refuses a known `custom_id`, so this can never buy twice. A repeat that
     LIS-SKINS refuses for the lot (`skins_unavailable`, `skins_price_higher_than_max_price`,
     an unknown code) may be refused because our first send bought it: no refund — `market/info` is asked once more, and if it still shows nothing the purchase
     gets the `buy_unconfirmed` attention. A silence is never refunded. Many at once →
     LIS-SKINS' outage; wait.
   - `refused`: the `code` says why. `skins_unavailable` or
     `skins_price_higher_than_max_price` → a refund `sold_out`; no other offer is bought in its place
     (ADR-0013). Many at once can mean a stale snapshot (see
     [Snapshot stale](#snapshot-stale)). `insufficient_funds` → see
     [Balance low](#balance-low). A trade-link code (`invalid_trade_url`, `user_trade_ban`,
     `user_cant_trade`, `private_inventory`, `too_many_failed_attempts_for_user`) refunds
     `invalid_trade_link`: the buyer fixes the link. `custom_id_already_exists` adopts the
     stored purchase.
3. `rate_limited` (429) is not counted here: the order waits for `Retry-After` and tries again.

## Attentions

A LIS-SKINS attention sits on `lisskins_purchases`. It counts in `csmarket_trades_attention`
(so `TradesNeedAttention` fires) and in the dashboard's attention count, but the admin trades
page and its attention queue do not list it (`docs/tech-debt.md`). Find the order by number in
the admin order search; its «Покупка LIS-SKINS» block shows the purchase, its status, the
`custom_id` and the attention. Look the purchase up in the LIS-SKINS cabinet's purchase history
by that `custom_id` (the order id; an order bought before ADR-0013 may carry `<order id>:2`).

- `rolled_back` — a `return` with `rollback_user` / `rollback_supplier`, or a `return` after
  delivery. Steam undid an accepted trade; the skin may be gone from the buyer. Decide with the
  buyer what is owed. Nothing was refunded automatically.
- `ambiguous_trade` — LIS-SKINS reports `wait_unlock` / `wait_withdraw` (we never buy locked
  lots), or a buy went through while the order had moved. Check what LIS-SKINS holds under the
  `custom_id`.
- `buy_unconfirmed` — a lost buy was sent again and LIS-SKINS refused the lot, while
  `market/info` showed nothing under the `custom_id` (see [Buy failures](#buy-failures)).
  Look the `custom_id` up in the cabinet or ask LIS-SKINS support. While it is open the
  reconcile still asks `market/info` and adopts a purchase that shows up, but sends nothing;
  «Разобрано» lets it send once more under the same `custom_id` after the wait.
- `source_forbidden` — see [Buy failures](#buy-failures); it clears itself once a buy goes
  through.

When checked, press «Разобрано»: it works on a LIS-SKINS purchase, and resolving it frees a
refund the attention held. Admin retry still refuses a LIS-SKINS order (409); the admin refund asks LIS-SKINS first (`docs/runbooks/public-api.md`, «Refund of a Skinslink / LIS-SKINS order», ADR-0018).

## Disabling

Set `CSMARKET_LISSKINS_ENABLED=false` and restart as in [Enabling](#enabling) (step 3). At once:
no LIS-SKINS offers or checkout checks; the snapshot and balance jobs stop. The next
`sources.prices` tick (≤ 2 min) clears the roll-up and its prices and deactivates items only
LIS-SKINS had. `lisskins.reconcile` keeps running while the API key is set, so orders already
in flight settle, and paid ones not yet claimed are still bought.

**Keep the key** until no LIS-SKINS order is open. Without it open orders wait, and
`OrdersBuyingStuck` / `TradesUnpolled` fire after 30 minutes; putting the key back settles them
under each order's `custom_id`.

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U <user> -d <db> -c \
  "SELECT count(*) FROM orders WHERE source='lisskins' AND status IN ('paid','buying','trade_sent')"
```

Remove the key only when this is 0. Delivered orders are still polled for rollbacks for 8 days;
without the key a rollback in that window goes unseen.

## «На холде» in the admin

LIS-SKINS reports only `accepted` once the buyer takes the offer — no hold status and no end date —
and the order turns `delivered` at once. Steam still protects the trade for 7 days, so the admin's
«Обмены» shows such an order «на холде» with **≈** before the end: our estimate, accepted + 7
days. The reconcile asks LIS-SKINS about it every 10 minutes for 8 days; a rollback comes as
`return` and opens the `rolled_back` attention. Partners on the API keep reading `delivered`.
