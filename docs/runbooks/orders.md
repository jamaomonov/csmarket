# Runbook — orders and trades

A customer's order buys one skin at Waxpeer; Waxpeer's seller sends it to the buyer's trade
link as a Steam offer. This runbook explains the lifecycle in plain words, what each alert
means and what to do, and the safe action for each trade that needs a human. Waxpeer itself
(the key, its IP whitelist, the balance, the dev fake): [`waxpeer.md`](./waxpeer.md). Code:
`apps/api/src/csmarket/modules/orders/README.md`; design: ADR-0007; flow:
[`buy.md`](../product/flows/buy.md).

## The lifecycle in plain words

1. **`pending`** — the buyer pressed «Купить»; the order holds the offer, the price in soʻm
   and a snapshot of their trade link. Unpaid after 15 minutes → **`cancelled`** (the
   `orders.expiry` sweep, every 60 s; an order a kassa is still processing waits for that
   kassa's own timeout).
2. **`paid`** — from the balance (one ledger `purchase`) or a kassa callback. The same
   transaction sends `NOTIFY orders`.
3. **`buying`** — the worker claimed it. It first looks the order up at Waxpeer by
   `project_id` (= the order's id), and buys only when nothing is there. A lost answer is
   resolved by the same lookup, **never by buying again**.
4. **`trade_sent`** — the seller's offer is in Steam (Waxpeer status 4). The buyer has about
   30 minutes to accept.
5. **`delivered`** — accepted. Steam's trade protection (7 days) can still roll it back; the
   hourly protection watch follows it.
6. **`returned`** (declined or expired in Steam) and **`failed`** (could not buy: sold, our
   Waxpeer balance ran out, a broken trade link) — the money goes **back to the balance**
   in the same transaction, once. Refunds never go to a card or a kassa.

The `trades.reconcile` sweep (every 10 s) moves orders from Waxpeer's answers. Anything it
cannot decide safely — an answer lost for 10 minutes, several trades under one order, a
rollback after delivery, a nightly audit mismatch, a 403 — becomes an **attention** on the
trade: the order keeps its status, nothing is refunded, the buyer reads «Мы проверяем
покупку…», and an admin decides.

## Admin screens

- **«Заказы»** (`/orders`): search by number (prefix) or skin name, filter by status. A badge
  «внимание» marks an open attention.
- **The order page** (`/orders/<number>`): regions «Заказ» (prices, margin, the trade link
  masked), «Платежи» (attempts), «Обмен» (Waxpeer status, `project_id` and Waxpeer id with
  copy buttons, the Steam offer link, seller, attention and its resolution) and «Действия».
- **«Обмены»** (`/trades`): tabs «Все», «В пути <n>» (`buying` / `trade_sent`) and
  «Требуют внимания <n>».
- The user card lists the user's latest 20 orders.

**What to check, in this order:** «Обмены» → the order → its «Обмен» block (status, Waxpeer
id, attention, last poll) → the Waxpeer dashboard, searched by the **`project_id`** («Скопировать
project id»). The `project_id` is what ties a Waxpeer purchase to our order.

## Actions

| Button                     | When it shows                                                                                      | What it does                                                                              |
| -------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| «Разобрано» + «Заметка»    | An open attention                                                                                  | Marks it resolved, with your note (what you found at Waxpeer — no personal data). Audited |
| «Вернуть деньги на баланс» | `buying`, not refunded, a **resolved** `buy_unconfirmed` / `ambiguous_trade` / `waxpeer_forbidden` | Refunds the price to the buyer's balance (`failed`, reason `admin`). Audited              |
| «Повторить покупку»        | The same, and no purchase on record (no Waxpeer id)                                                | Clears the attention and lets the next sweep look up, then buy once. Audited              |

Refusals (Russian text under the actions): «Скин ещё в пути — вернуть деньги нельзя.»
(`order_in_flight`), «Деньги уже на балансе.» (`already_refunded`), «Этот заказ нельзя
вернуть.» (`order_not_refundable`: unpaid, cancelled, delivered), «Покупка ещё идёт —
попробуйте через минуту.» (`order_busy`: a buy attempt holds the order, or a 403/429 backoff
of up to 60 s runs), «Повтор сейчас невозможен.» (`not_retryable`).

**Rules:**

- **«Разобрано» first.** Refund and retry need a resolved attention.
- **Refund only when Waxpeer shows nothing bought** under the `project_id` (or only failed
  trades, none accepted). If a skin went out, refunding gives away the skin and the money.
- **Retry only after checking the `project_id`.** The sweep looks up before it buys, so a
  purchase Waxpeer made is adopted, not repeated — but check anyway: it is the last guard
  against a second buy.
- **Never credit by hand.** No SQL on `wallet_*`, `orders` or `skin_trades`. A goodwill
  payment, or money owed for a case the buttons do not cover (a rollback after delivery),
  goes through the user card's «Изменить баланс» with a reason naming the order number
  ([`wallet.md`](./wallet.md)).

## Attention reasons

| Reason (admin label)                                  | Order       | Means                                                                                                                                     | Safe action                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `buy_unconfirmed` («ответ Waxpeer потерян»)           | `buying`    | The buy's answer was lost (network, 5xx, timeout) and the lookup still shows nothing after 10 min                                         | The attention opens 10 min after the lost answer. Wait at least one more reconcile cycle (10 s; a minute is plenty), then search the `project_id` in the Waxpeer dashboard. A trade there → do nothing: the next tick adopts it and clears the attention. Nothing there → «Разобрано», then «Повторить покупку» (the buyer still gets the skin) or «Вернуть деньги на баланс»                    |
| `ambiguous_trade` («несколько обменов»)               | `buying`    | Several live trades under one order, a known Waxpeer id that Waxpeer stopped reporting, or a buy that landed on rows another writer moved | Count the purchases at Waxpeer by `project_id`. One live or accepted → resolve, no refund (the sweep follows it once only one trade is live). Nothing bought → resolve, then refund or retry. Only failed (status 6) trades, and none of them was ever accepted → treat as nothing bought. Two bought → resolve, no refund (the buyer gets one); take the extra purchase up with Waxpeer support |
| `rolled_back` («откат после получения»)               | `delivered` | Waxpeer reports 6 after the buyer accepted (Steam protection rollback, penalties)                                                         | The money is spent; the app never refunds it. Decide with support whether anything is owed; if so, «Изменить баланс» with a reason. Then «Разобрано»                                                                                                                                                                                                                                             |
| `waxpeer_forbidden` («Waxpeer: IP не в белом списке») | `buying`    | Waxpeer answered 403: the key's IP whitelist                                                                                              | Fix the whitelist ([`waxpeer.md#forbidden`](./waxpeer.md#forbidden)); the sweep then buys and clears it by itself. See [Forbidden, then refunded](#forbidden-then-refunded) before refunding one                                                                                                                                                                                                 |
| `audit_divergence` («расхождение со сверкой»)         | any settled | The nightly audit disagrees with Waxpeer's record                                                                                         | [Audit divergence](#audit-divergence)                                                                                                                                                                                                                                                                                                                                                            |

An attention a sweep sees again after «Разобрано» stays resolved; a new reason (or a new 403)
re-opens it.

### Forbidden, then refunded

A `waxpeer_forbidden` order can be refunded once resolved. Rare edge (ruling U): if a buy
attempt **sent** the buy, then died before recording it, and its lease lapsed, the refund
skips the lookup the sweep would have made. So before refunding a resolved
`waxpeer_forbidden` order, **search its `project_id` at Waxpeer**: a purchase there means
"do not refund" (fix the whitelist and let the sweep adopt it). The nightly audit would flag
a refunded-and-delivered order as `delivered_refunded` the next night.

While Waxpeer keeps answering 403, refund and retry of a `waxpeer_forbidden` order answer
`order_busy` during each 60 s backoff: fix the whitelist first.

## Alerts

All in `infra/prometheus/alerts/orders.yml`; the gauges come from the scheduler's
`orders.health` job every 60 s ([`metrics.md`](../architecture/metrics.md)). After a
scheduler restart the gauges stay empty for about 260 s (the job's first run), so these
alerts cannot fire in that window; `OrdersHealthStale` covers a job that keeps failing.

## Paid stuck

`OrdersPaidStuck` (page): an order has been `paid` for over 5 minutes and no worker claimed
it. The buyer's money is taken and nothing is buying.

1. Is the worker up? `docker compose -f docker-compose.prod.yml ps worker` and
   `… logs --since 30m worker` (look for `orders.buy.crashed`, database errors). If it is
   down: [Worker down](#worker-down).
2. Is Postgres reachable from it? The worker also polls on a timer, so a lost `NOTIFY` only
   delays it.
3. Do not move the order by hand. Once the worker runs, it claims paid orders oldest first.

## Buying stuck

`OrdersBuyingStuck` (warn): an order claimed over 30 minutes ago is still `buying` with no
open attention.

1. Open it in «Обмены». No Waxpeer id and `buy_pending` on the trade → every lookup fails:
   check the worker / scheduler logs for `orders.buy` outcomes and
   `csmarket_waxpeer_calls_total{endpoint="lookup"}` by outcome. `unavailable` (no key,
   Waxpeer down) → wait or fix the key; `forbidden` → [`waxpeer.md#forbidden`](./waxpeer.md#forbidden).
2. A Waxpeer id and a status 0–2 → the seller has not sent the offer yet. Check the trade on
   the Waxpeer dashboard by `project_id`; Waxpeer cancels it by itself if the seller never
   sends, and the sweep then refunds.
3. **Never buy again by hand**, never «Повторить» while a Waxpeer id is on record (the button
   is hidden then).

## Trades unpolled

`TradesUnpolled` (warn): an order in `trade_sent` was last looked up at Waxpeer over 30
minutes ago. The buyer may have accepted and still sees «Обмен отправлен».

1. Is the scheduler up and `trades.reconcile` running? `… logs --since 15m scheduler | grep
orders.reconcile` — `lookup_failed` lines mean Waxpeer is refusing or down (a lookup
   failure writes nothing, every row stays due). 403 → [`waxpeer.md#forbidden`](./waxpeer.md#forbidden).
2. Scheduler down → [Scheduler down](#scheduler-down). It catches up by itself once running.

## Attention

`TradesNeedAttention` (warn, 15 min): at least one trade has an unresolved attention. Open
«Обмены» → «Требуют внимания» and handle each by [Attention reasons](#attention-reasons).
The buyer meanwhile reads «Мы проверяем покупку…»; an offer that is still open stays visible
to them.

## Audit divergence

`TradeAuditDivergence` (warn): the nightly audit (04:30 Tashkent, the last 14 days of settled
trades, looked up by `project_id`) found a new mismatch; the trade gets `audit_verdict` and
an `audit_divergence` attention. It changes nothing else.

| `audit_verdict`      | Means                                                                | Do                                                                                                                                                                   |
| -------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rolled_back`        | A delivered order that Waxpeer now shows as 6: a late rollback       | As `rolled_back` above                                                                                                                                               |
| `delivered_refunded` | We refunded the buyer, but Waxpeer shows the offer sent or completed | Check the dashboard and whether the buyer has the skin. If they have both, the owner decides; take the money back with a clawback adjustment naming the order number |
| `unknown`            | Waxpeer no longer knows a trade we saw                               | Search the dashboard by `project_id`; report to Waxpeer if it is gone                                                                                                |
| `ambiguous`          | Several live trades under one order                                  | As `ambiguous_trade` above                                                                                                                                           |

Then «Разобрано» with what you found. A changed verdict alerts again; agreement clears the
verdict but leaves the attention for you.

## Health stale

`OrdersHealthStale` (warn): the `orders.health` job has not finished a tick for 5 minutes, so
every gauge above is frozen and the alerts are judging old numbers. Look for
`orders.health.crashed` in the scheduler log (usually the database); restart the scheduler
if it is wedged: `docker compose -f docker-compose.prod.yml up -d --force-recreate scheduler`
(the tag comes from `.env`, [`deploy.md`](./deploy.md)).

## Worker down

`WorkerDown` (page): Prometheus cannot scrape `worker:9101` for 2 minutes. Paid orders are not
bought.

```bash
docker compose -f docker-compose.prod.yml ps worker
docker compose -f docker-compose.prod.yml logs --tail 200 worker
docker compose -f docker-compose.prod.yml up -d worker   # IMAGE_TAG from .env, never exported
```

A metrics port already taken logs a warning and the worker goes on — then the worker works
but is not scraped; fix the port clash. A worker that died mid-buy leaves a lease that
lapses after 5 minutes; the sweep then resolves the order by lookup first.

## Scheduler down

`SchedulerDown` (page): `scheduler:9102` not scraped for 2 minutes. Trades are not reconciled,
unpaid orders do not expire, and every order-health gauge is frozen. Same commands as for the
worker with `scheduler`. After a restart the jobs start staggered: expiry at 220 s,
reconcile at 240 s, the gauges at 260 s, the protection watch at 280 s.

## Other situations

- **A balance pay while a kassa attempt is live.** The buyer opened Payme (state 1), came back
  and paid from the balance. The order is paid once; if they then complete the kassa
  payment, the kassa's settle is refused (Click −4, Payme −31008, Uzum 10008), so the card is
  not charged. The held attempt closes by that kassa's timeout sweep (Click / Uzum 30 min,
  Payme 12 h). Nothing to do.
- **A kassa asks to reverse an order payment.** Always refused (Payme −31007, Uzum 10017;
  Click has none): the skin is bought at payment. If the owner agrees to refund a
  non-delivered order to the card, it is done in the kassa's cabinet and the balance
  side with a clawback adjustment — owner's decision, never automatic.
- **Low Waxpeer balance refunds.** [`waxpeer.md#balance-low`](./waxpeer.md#balance-low).
- **Switching buying off.** `CSMARKET_SKINS_BUY_ENABLED=false` in `secrets/api.env`, then
  `up -d api worker scheduler`: the buy panel disappears and new orders are 409
  `buying_disabled`. Orders already paid are still bought and their trades followed.

## Logs

`orders.created`, `orders.paid`, `orders.buy` (number, outcome), `orders.buy.stale_purchase`
(error: a purchase may exist twice — check the trade), `orders.buy.unrecorded`,
`orders.trade` / `orders.trade.rolled_back` / `orders.trade.refund_held`,
`orders.refunded` (number, amount, reason). They carry the order number and amounts, never a
user id or the trade link.

## Never

- Never buy at Waxpeer by hand for an order, and never press «Повторить» without searching
  the `project_id` first.
- Never refund an order whose skin may have reached the buyer.
- Never edit `orders`, `skin_trades` or `wallet_*` rows by hand; never copy a trade link or a
  Steam ID into chat or a note.
