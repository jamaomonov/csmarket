# Runbook — Selling skins to us (Skinslink deposits)

ADR-0016. Module: `apps/api/src/csmarket/modules/sales/`. Alerts: `SalePayoutsOverdue`,
`SaleAttentionOpen`, `SaleHoldOverdue`, `SaleUnknownStatus` (`infra/prometheus/alerts/sales.yml`,
Telegram).

## Switching on

1. Skinslink buying's credentials are set (`CSMARKET_SKINSLINK_API_KEY`, `_SECRET`), the VPS
   IP is whitelisted in the cabinet, the merchant webhook URL is
   `https://api.csmarket.uz/api/v1/skinslink/webhook` (the same endpoint serves purchases
   and deposits) — `docs/runbooks/skinslink.md`.
2. Deploy with `CSMARKET_SALES_ENABLED=false`; then set it `true` in `secrets/api.env` and
   restart the API, the worker and the scheduler with the pinned `IMAGE_TAG`.
3. In the admin, «Выкуп» → «Настройки выкупа»: set the real card fees, the bonus, the margin
   brackets; leave «Выкуп включён» off. Read the `warnings` the settings answer carries:
   `balance_bonus_eats_margin` means the top bracket's margin less the balance bonus less 1 %
   (Skinslink may credit 1 % under our quote) is zero or less — an expensive sale to the balance
   loses money. The save is not refused; fix the numbers before switching on.
4. Optional ceilings, in USD of Skinslink's prices (empty = no limit): `max_sale_usd` per sale,
   `max_user_day_usd` per seller over the last 24 h, `max_day_usd` for everyone over the last
   24 h. Sales that ended paying nothing (`closed`, `reverted`) do not count. A sale over one is
   refused at `POST /sell` with 409 `above_sale_maximum`, `user_daily_limit` or `daily_limit`
   (with `limit_usd` and `left_usd`). Start low while learning.
5. The owner makes a test sale with «Выкуп включён» on for a minute: inventory, offer, accept,
   `hold`. Check the sale page and «Продажи» in the admin; then decide whether to leave it on.

## Paying a card request

«Выкуп» → «Заявки на выплату» → «К выплате» (the default tab). Open a request:

1. «Скопировать номер» (or «Показать номер») — each is an audit row
   (`sales.card.copy` / `sales.card.show`). Never paste the number anywhere but the bank.
2. Pay the amount shown («К выплате») from the bank by hand.
3. «Выплачено», with the bank's reference as the note. The seller gets a letter.

The number is never in a list, a letter or a log; do not screenshot it.

## Overdue

`SalePayoutsOverdue`: a request has been «К выплате» for more than 48 h. Pay it as above, or
«Отклонить» with a reason when the card cannot take it (blocked, wrong bank): the amount
**before** the card fee goes to the seller's balance (`payout_return`), and they get a letter
saying the transfer failed. Your reason stays in the admin: the seller never sees it (write
it for the team, not for them).

## Rejecting

«Отклонить» needs a reason (admin-only — the seller's page and letter show a fixed
sentence). It is possible only for a request «К выплате» — a request still waiting for its
7 days cannot be decided (409 `payout_not_payable`).

## Saved cards

A seller has at most three live cards. Typing a number already saved reuses that card (no
second row), so retrying a refused card sale never hits `cards_limit`. A seller at the limit
deletes one in the profile («Мои карты»).

## Reverted while payable

Skinslink may report `reverted` after a card sale became payable. The request is **not**
canceled — you may be paying it at that moment. The sale gets `attention = rolled_back`
(`SaleAttentionOpen`) and the request stays «К выплате»; its page shows `can_cancel`.

- If the money already went out: «Выплачено» as usual (it is still recorded), then treat the
  sale as `rolled_back` below.
- If not: «Отменить (откат)» with a reason (`POST /admin/sales/payouts/{id}/cancel`, audited
  `sales.payout.cancel`) — nothing is paid, the sale becomes `reverted`, its attention is marked
  checked and the seller gets the canceled letter. Do **not** «Отклонить»: that would credit the
  seller's balance.

## Blocking a seller

`PUT /admin/sales/blocks/{user_id}` `{"blocked": true, "reason": "…"}` stops a user's
`POST /sell` (409 `sell_blocked`; the reason is never shown to them); `{"blocked": false}` lifts
it. Both are audited (`sales.user.block` / `sales.user.unblock`). `GET /admin/sales/blocks`
lists the blocked users. Open sales of a blocked user still settle normally.

## Stuck sales

- **`creating` for minutes**: `create-deposit` timed out (it sends the Steam offer before it
  answers; a slow Steam takes long). `sales.poll` asks `deposit/status` every minute; a
  deposit Skinslink still does not know after 10 minutes is closed (`not_created`, hidden from
  the seller). The poll keeps asking about it every 5 minutes for 24 h: if the offer went out
  after all, the sale is **reopened** and followed to the end (log `sales.reopened`) — paid like
  any other. If many pile up, check Skinslink
  (`csmarket_skinslink_calls_total{endpoint="deposit"}`).
- **`offered` for hours**: the seller has not accepted; Skinslink cancels expired offers and
  the poll closes the sale.
- **`hold` past its date**: the poll asks every 30 minutes; check the deposit in the cabinet
  by the sale id (= `merchant_tx_id`). See [Hold overdue](#hold-overdue).

## Attention

`SaleAttentionOpen` fires per reason while a sale has an attention nobody marked checked
(gauge `csmarket_sale_attention_open{reason}`, set by `sales.poll`). Find them with
`GET /admin/sales?attention=open` (or `&reason=…`; the page's `attention_open` counts them all;
the dashboard's `payouts.sales_attention` too). When handled, press «Проверено»:
`POST /admin/sales/{number}/resolve` `{"note": "…"}` — audited `sales.attention.resolve`,
stamps `resolved_at/by/note` once. A new reason on the same sale opens it again.

- **`rolled_back`**: Skinslink reported `reverted` after the sale became payable (the balance
  credited, or a card request payable or paid). Nothing is debited automatically. A card request
  still «К выплате» waits for you — see [Reverted while payable](#reverted-while-payable). Look
  at the deposit in the cabinet; if the seller kept money for skins we lost, contact them; adjust
  the balance only with the owner's word («Пользователи» → balance adjustment, audited).
- **`late_deposit`**: a sale we closed (`not_created`, a refusal) that Skinslink reports
  `reverted`: nothing was paid and the skins went back to the seller. Check the cabinet and mark
  it checked. (A closed or reverted sale Skinslink reports **alive** — `active`, `hold`,
  `completed` — is no longer flagged: it is reopened and paid normally.) The `create-deposit`
  answer itself reopens only a sale our poll closed as `not_created`: a sale a webhook check
  already moved on keeps that newer status (log `sales.deposit_answer_stale`).
- **`credit_blocked`**: Skinslink reports `completed` for a balance sale, but the seller's wallet
  is frozen, so the credit was refused. The sale stays where it was; each poll retries and the
  flag clears when the credit lands (or when the sale closes or is reverted). Unfreeze the wallet
  (or decide with the owner) and the next poll credits it; nothing is lost.

## Hold overdue

`SaleHoldOverdue`: a sale is still in `hold` 6 h after its `hold_end_at` (gauge
`csmarket_sale_holds_overdue`). The status read is failing — look for `sales.status_unread` in
the scheduler's logs and `csmarket_skinslink_calls_total{endpoint="deposit_status"}`; a 403
means the key was rotated or the VPS IP left the whitelist (`docs/runbooks/skinslink.md`). Once
the reads work, the next poll pays the sale.

## Unknown status

`SaleUnknownStatus`: Skinslink answered a deposit status the status machine does not know
(`csmarket_sale_outcomes_total{outcome="unknown"}`; statuses are compared lower-cased). The sale
does not move. Find `sales.unknown_status` in the logs (status, sale number), check the deposit
in the cabinet, and teach `sales/status.py` the status.

## Switching off

The admin's «Выкуп включён» off (instant), or `CSMARKET_SALES_ENABLED=false` (a restart).
Open sales keep settling: the poll and the worker run while the Skinslink key is set, and the
webhook stays open while both Skinslink credentials are set, whatever the switches.

## Known gaps

Shipped on purpose; none of them puts money at risk.

- A replayed webhook signature can grow `sale_checks` (the signature covers only the id; the
  worker drains the rows and every check is idempotent).
- A double submit with two different `Idempotency-Key`s: the second is refused with 409
  `items_in_sale` while the first sale's offer is open (`creating` / `offered`). The seller's
  inventory list still shows those items until it is read again.
- Settled sales (`credited`, `payout`, `reverted`) are not polled; a later `reverted` on them is
  seen only by the webhook.
