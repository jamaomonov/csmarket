# Runbook — Skinslink (the second buy source)

Skinslink sells CS2 skins beside Waxpeer. We keep a mirror of its stock, show its offers next
to Waxpeer's, and buy from it with our Skinslink balance when the buyer picked one of its
offers. Its seller sends the skin to the buyer's trade link. This runbook covers the keys,
the IP whitelist, the webhook, switching it on and off, the balance and the alerts that point
here. Orders and admin actions: [`orders.md`](./orders.md). Waxpeer:
[`waxpeer.md`](./waxpeer.md). Code: `apps/api/src/csmarket/modules/skinslink/README.md`;
design: [ADR-0010](../decisions/0010-skinslink-buy-source.md); flow:
[`skinslink-buy.mmd`](../architecture/sequence-diagrams/skinslink-buy.mmd).

## What we call

| Call                               | Who                                            | How often                                 |
| ---------------------------------- | ---------------------------------------------- | ----------------------------------------- |
| `GET /merchant/purchase/available` | scheduler `skinslink.mirror`                   | the first tick, and after `reset`         |
| `GET /merchant/purchase/events`    | scheduler `skinslink.mirror`                   | every 15 s (more pages at once if `more`) |
| `POST /merchant/purchase`          | worker (`orders` queue), `skinslink.reconcile` | once per order                            |
| `GET /merchant/purchase/status`    | worker (`skinslink` queue), reconcile, buy     | per webhook; every 30 s per open purchase |
| `GET /merchant/balance`            | scheduler `skinslink.balance`                  | every 5 min                               |

Every call is counted in `csmarket_skinslink_calls_total{endpoint, outcome}`
([`metrics.md`](../architecture/metrics.md)). The key rides the `X-Api-Key` header; the
trade link travels as `partner` + `token` in the purchase body. Skinslink's error bodies are
never logged (they can echo the request).

## Credentials

- Two values: `CSMARKET_SKINSLINK_API_KEY` (the merchant API key) and
  `CSMARKET_SKINSLINK_SECRET` (signs the webhooks). Both come from the Skinslink merchant
  cabinet.
- They live **only** in `secrets/api.env` on the server (read by the api, worker and
  scheduler). **Never in chat, a commit, a doc, an issue or a test.** Both are on the log
  redaction list.
- The pair the owner pasted in chat on 2026-10-06 is burnt: **rotate it in the cabinet before
  first use**, then write the new pair to `secrets/api.env`.
- Rotation: issue a new pair in the cabinet, replace both lines, then
  `docker compose -f docker-compose.prod.yml up -d api worker scheduler` (never `restart`: it
  keeps the old environment — [`deploy.md`](./deploy.md)). A webhook signed with the old
  secret during the swap is refused (403); the reconcile polls the purchase anyway.

## IP whitelist

Skinslink accepts our key only from whitelisted IPs. A call from anywhere else gets
**HTTP 403**. Whitelist the VPS: **`57.131.198.69`**. A new server or a changed egress IP
needs a new entry **before** it goes live. Check the server's egress IP from the server:

```bash
curl -s https://ifconfig.me; echo
```

## Webhook URL

Set in the Skinslink cabinet:

```text
https://api.csmarket.uz/api/v1/skinslink/webhook
```

The webhook only says "something happened to purchase N". We check `sign` (sha256 of the
id and the secret), queue a check and answer 200; the worker then asks Skinslink for the
status. The body's own status is never trusted. A bad or missing `sign` is 403; the route is
404 while Skinslink is off. A deposit webhook (`trade_id`, ADR-0016) queues a check of the sale its `merchant_tx_id` names; the worker asks `deposit/status` (`docs/runbooks/sales.md`). The route answers while Skinslink buying **or** selling is active.
A lost webhook costs at most 30 s: `skinslink.reconcile` polls every open purchase.

## Enabling

1. The keys are rotated and in `secrets/api.env`; the IP is whitelisted; the webhook URL is
   set; the Skinslink balance is topped up.
2. In `secrets/api.env`: `CSMARKET_SKINSLINK_ENABLED=true`. Skinslink is used only when the
   switch is on **and** both values are set (`skinslink_active`).
3. `docker compose -f docker-compose.prod.yml up -d api worker scheduler`.
4. Watch: the scheduler logs `skinslink.mirror.loaded mode=full` within a minute;
   `csmarket_skinslink_enabled` reads 1 after the first balance tick (90 s);
   `csmarket_skinslink_calls_total{outcome="ok"}` grows; the `sources.prices` tick
   (every 2 min, first run 105 s after start) fills `skin_items.skinslink_count` and
   reprices. An item page now lists offers of both sources.
5. The first test buy: an admin's own account, credited through «Изменить баланс», buys a
   cheap Skinslink offer (the admin order page shows «Источник: Skinslink · sl:…») and
   accepts it in Steam; then one declined, which is refunded to the balance once. Take the
   test balance back with a clawback naming both orders.

## Balance low

`SkinslinkBalanceLow` (page): `csmarket_skinslink_balance_available_usd` has been below
`CSMARKET_SKINSLINK_BALANCE_ALERT_USD` (default 100) for 10 minutes. `WaxpeerLowBalanceRefund`
fires for every source: it counts refunds with reason `source_low_balance`.

What happens on a short balance: Skinslink refuses the purchase with `insufficient_balance`,
the order goes `failed` and the money goes back to the buyer's balance **at once**. The buyer
buys again.

1. **Top up the Skinslink balance** in the merchant cabinet (the owner's account).
2. Watch `csmarket_skinslink_balance_available_usd` rise on the next read (every 5 minutes).
   The admin dashboard shows the same number («Skinslink»: available and on hold).
3. **Do not retry** the refunded orders: the money is already back.

Keep the balance above the most expensive skin likely to sell plus a day of sales. The part
`on hold` is money in open purchases; it comes back on a failed one.

## Mirror stale

`SkinslinkMirrorStale` (warn): no mirror tick has succeeded for 10 minutes. Skinslink offers
and prices are off the storefront until one does (a stale mirror sells nothing); the next
`sources.prices` tick (≤ 2 min) deactivates items only Skinslink had. Waxpeer is unaffected. Open Skinslink
orders keep moving: the status checks and the reconcile do not use the mirror.

1. The scheduler log: `skinslink.mirror.failed error=<type>` on every tick names the error.
2. `csmarket_skinslink_calls_total{endpoint=~"available|events"}` by outcome:
   - `forbidden` (403) → the IP whitelist or a disabled merchant: see [IP whitelist](#ip-whitelist);
   - `unavailable` → Skinslink is down or slow: check their status page and wait;
   - `refused` → a bad key, or a cursor Skinslink no longer accepts.
3. A cursor problem heals itself: Skinslink answers `reset`, and the next tick downloads the
   whole list again (`skinslink.mirror.loaded mode=reset`).
4. The alert clears once a tick succeeds; the next `sources.prices` tick (≤ 2 min) puts
   Skinslink prices back.

## Buy failures

`SkinslinkBuyFailures` (warn): more than five purchase calls were refused, forbidden or
unanswered in 15 minutes (worker and reconcile together). One sold item is normal; a run is
the key, the IP whitelist or Skinslink itself.

1. The worker log: `orders.skinslink_buy number=… outcome=…`.
2. `csmarket_skinslink_calls_total{endpoint="purchase"}` by outcome:
   - `forbidden` (403): the order stays `buying` with the buy pending and the attention
     `source_forbidden`; nothing is refunded. Fix the whitelist or the key; the reconcile
     buys again (same `merchant_tx_id`, never a second purchase) and clears the attention.
   - `unavailable` (timeout, 5xx, network): the buy may have gone through. The order keeps
     `buy_unconfirmed_at`; the reconcile asks Skinslink under the same id and adopts what is
     there. If Skinslink still has no purchase under it after `order_unconfirmed_minutes`
     (10), the buy is sent again under the **same** `merchant_tx_id` (log
     `orders.skinslink.repeat_unseen`): Skinslink is idempotent on it, so this can never buy
     twice. A silence is never refunded.
   - `refused`: sold or price moved. The order is refunded `sold_out`; no other
     offer is bought in its place (ADR-0013). Many at once can mean a stale mirror (see
     [Mirror stale](#mirror-stale)).
3. A refusal naming the trade link (`trade_link_*`, `trade_banned`, `profile_private`,
   `hold`, `permissions`, …) refunds `invalid_trade_link`: the buyer fixes the link.

A webhook naming a purchase id we do not know logs `orders.skinslink.unknown_purchase` and is
dropped (the reconcile polls our own purchases anyway).

**Known gap:** a Skinslink attention (`source_forbidden`, `ambiguous_trade`, `rolled_back`)
counts in `csmarket_trades_attention`, so `TradesNeedAttention` fires for it, but the trades
attention queue and the dashboard tile do not list it (`docs/tech-debt.md`). Find the order by
number in the admin order search: its «Покупка Skinslink» block shows the attention. Check the
purchase in the Skinslink cabinet by its `merchant_tx_id`, then press «Разобрано» — it works
on a Skinslink purchase, and resolving it frees a refund the attention held. Admin refund and
retry still refuse a Skinslink order.

## Disabling

Set `CSMARKET_SKINSLINK_ENABLED=false` and
`docker compose -f docker-compose.prod.yml up -d api worker scheduler`. At once: no Skinslink
offers (the next `sources.prices` tick, ≤ 2 min, clears the roll-up and its prices and
deactivates items only Skinslink had; it keeps running until nothing is left to clear), the
webhook answers 404, and the mirror and balance jobs stop. The reconcile and the check drain
keep running while the API key is set, so orders already in flight settle.

What happens to Skinslink orders already in flight:

- **Paid, not yet claimed:** the worker still sends the purchase while the API key is in
  `secrets/api.env`; without the key it is recorded as unconfirmed and waits.
- **`buying` / `trade_sent`:** with the key still set, the reconcile polls them every 30 s
  (10 min while Steam's trade hold runs) and settles them as usual. Removing the key stops
  that: they wait, `OrdersBuyingStuck` / `TradesUnpolled` fire after 30 minutes, and putting
  the key back settles them under each order's `merchant_tx_id`.

So turn the switch off first, and remove the key only once none is left open.

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U <user> -d <db> -c \
  "select number, status from orders where source = 'skinslink' and status in ('paid','buying','trade_sent')"
```

Removing the keys parks every open Skinslink order for an admin; the admin refund cannot
book one yet (see the known gap above), so keep the keys until the list is empty.
