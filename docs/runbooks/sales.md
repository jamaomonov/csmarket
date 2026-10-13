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
3. In the admin, «Настройки» → «Выкуп»: set the real card fees, the bonus, the margin
   brackets; leave «Выкуп включён» off. A save made in a tab opened before someone else's save
   is refused («Настройки уже сохранил кто-то другой», 409 `settings_stale`): reload and edit
   again. Read the `warnings` the settings answer carries (a red banner on the page):
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

## Paying a card request (from a phone)

«Выкуп» → «Заявки на выплату» → «К выплате» (the default tab). The queue is **oldest first**:
the top card has waited longest («ждёт 2 д 3 ч» — orange after 6 h, red after 10 h; sellers are promised 12 h). The strip
above it shows what is payable now and what was paid / rejected since midnight (Tashkent) — the
numbers to check against the bank statement. A chip «платит <имя>» means another admin has
taken it; red chips are risks (below). The list refreshes itself every 15 s.

Open the top request. The first screen is everything you need to pay:

1. **«Беру в работу».** The request is yours for 15 minutes; everyone else sees «Платит <вы>»
   and cannot copy the number or press «Выплачено» without «Забрать себе» (audited). If the
   page says «Платит <другой> — не платите второй раз», stop: someone is paying it now. Changed
   your mind — «Отпустить».
2. **Look at the red banner and «Риски»** before sending money: a banned account or a frozen
   wallet («не платите»), «Та же карта у других» (one card cashing out several fresh accounts),
   a new account, many sales in 24 h, a large total. Not sure → do not pay; «Запретить выкуп»
   (reason for the team only) and ask the owner.
3. **«Скопировать сумму»** → paste into the bank app's amount (digits only, soʻm).
4. **«Скопировать номер»** → paste into the card number. Each copy or show is an audit row
   (`sales.card.copy` / `sales.card.show`) and also takes the request for you. If the phone
   says «Не скопировалось» the number stays on screen in a field: tap it, «Выделить всё»,
   «Скопировать». The number hides after a minute. Check the brand (Humo / Uzcard / Uzum Visa)
   and the last four in the bank app before confirming there.
5. Send the money in the bank app.
6. **«Выплачено»** → the confirm says «Выплачено N сум на Humo •••• 1234, получатель X?» —
   check it is the transfer you just made; put the bank's receipt number into «Комментарий
   (номер чека банка)»; «Да, выплачено». The seller gets a letter.

The number is never in a list, a letter or a log; do not screenshot it.

**Banned or frozen seller.** «Выплачено» asks «Почему всё равно платите?» and is refused
without an answer (409 `payout_user_blocked`); the answer goes into the audit row. Usually the
right move is not to pay: leave it, or «Отклонить» if the wallet is active.

**Pressed the wrong one?** For 10 minutes the page offers «Вернуть в очередь» (a reason is
required, audited `sales.payout.undo`):

- after «Выплачено»: the request is «К выплате» again. Use it only if the money did **not**
  go out. If the letter had not left yet, it is dropped; if it had, tell the seller.
- after «Отклонить»: the money credited to the seller's balance is taken back — only if it is
  still there. «Пользователь уже потратил эти деньги» (409 `balance_spent`) means the undo is
  impossible: pay nothing more and settle with the owner (a balance adjustment, audited).

After 10 minutes nothing can be undone from the page.

**Finding a request** when a seller calls: the search takes the sale number (`S…`), the card's
last four, part of the name or the Steam ID, across all statuses.

**After the deploy that brings migration 0033**, fill the fingerprint of cards saved before
(otherwise «Та же карта у других» says «неизвестно» for them):

```bash
docker compose -f docker-compose.prod.yml exec api python -m csmarket.scripts.backfill_card_fp
```

It prints `filled N` and can be run again safely.

## Overdue

`SalePayoutsOverdue`: a request has been «К выплате» for more than 10 h (sellers are promised the card within 12 h of the hold's end). Pay it as above, or
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
(`SaleAttentionOpen`) and the request stays «К выплате» with the red chip «обмен отменён»; its
page shows `can_cancel`.

- If the money already went out: «Выплачено» with a reason (the API answers 409
  `payout_sale_reverted` without `override_reason`; the reason is audited), then treat the sale
  as `rolled_back` below.
- If not: «Отменить (откат)» with a reason (`POST /admin/sales/payouts/{id}/cancel`, audited
  `sales.payout.cancel`) — nothing is paid, the sale becomes `reverted`, its attention is marked
  checked and the seller gets the canceled letter. Do **not** «Отклонить»: that would credit the
  seller's balance.

## Blocking a seller

In the admin: a payout's «Риски» → «Запретить выкуп» (a reason, never shown to the seller);
«Выкуп» → «Запрет выкупа» lists everyone blocked, with «Разрешить». API:
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
the dashboard's `payouts.sales_attention` too). In the admin: «Продажи» → «Пометка: ждут проверки» (the dashboard's «Продажи: проверить» tile
links there). When handled, press «Проверено» on the sale's page (an optional note):
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

## P&L and «Сверка»

Spec `2026-10-13-sales-pnl`. The dashboard's «Выкуп» block (today / 7 / 30 Tashkent days)
counts the sales Skinslink completed in the period:

- **получено** — what Skinslink credited (`amount_usd`); a sale rolled back after payout brings
  nothing;
- **выплачено** — card transfers plus the bank's charge to us (`bank_fee_pct`, «Настройки
  выкупа», default 1 %; written into the request at «Выплачено»), payouts to the balance with
  the bonus (a cost at once, owner ruling), rejected card requests at what the balance got;
  **к выплате** — card requests not paid yet, with the expected bank fee;
- **комиссии** — the card fee kept from sellers vs what the bank took; they should be close;
- **прибыль** — received minus paid out, soʻm converted at the CBU rate of the sale's creation.

«Выкуп» → «Сверка» (`/sales/reconciliation`) lists each sale: quoted, credited, difference.
Flags and what to do:

- **Недозачислено** — credited under 99 % of the quote (`min_prices` should prevent it): write to
  Skinslink support with the sale's `trade_id` (on the sale page).
- **Нет зачисления** — completed but no amount recorded: open the sale, check the Skinslink
  cabinet by `trade_id`; if it is credited there, the amount was lost on our side — tell the
  developer.
- **Откат** — `rolled_back` / `late_deposit` (see «Attention» above); handle it there, then
  «Проверено» removes it from the list once outside the period.

If the bank changes its fee, change «Комиссия банка, %»; requests paid before keep the fee
written at the time.

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
