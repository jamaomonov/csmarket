# Runbook — Selling skins to us (Skinslink deposits)

ADR-0016. Module: `apps/api/src/csmarket/modules/sales/`. Alert: `SalePayoutsOverdue`.

## Switching on

1. Skinslink buying's credentials are set (`CSMARKET_SKINSLINK_API_KEY`, `_SECRET`), the VPS
   IP is whitelisted in the cabinet, the merchant webhook URL is
   `https://api.csmarket.uz/api/v1/skinslink/webhook` (the same endpoint serves purchases
   and deposits) — `docs/runbooks/skinslink.md`.
2. Deploy with `CSMARKET_SALES_ENABLED=false`; then set it `true` in `secrets/api.env` and
   restart the API, the worker and the scheduler with the pinned `IMAGE_TAG`.
3. In the admin, «Выкуп» → «Настройки выкупа»: set the real card fees, the bonus, the margin
   brackets; leave «Выкуп включён» off.
4. The owner makes a test sale with «Выкуп включён» on for a minute: inventory, offer, accept,
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
with your reason (it shows on their sale page too).

## Rejecting

«Отклонить» needs a reason. It is possible only for a request «К выплате» — a request still
waiting for its 7 days cannot be decided (409 `payout_not_payable`).

## Stuck sales

- **`creating` for minutes**: `create-deposit` timed out. `sales.poll` asks `deposit/status`
  every minute; an unknown deposit is closed (`not_created`) after 2 minutes. If many pile up,
  check Skinslink (`csmarket_skinslink_calls_total{endpoint="deposit"}`).
- **`offered` for hours**: the seller has not accepted; Skinslink cancels expired offers and
  the poll closes the sale.
- **`hold` past its date**: the poll asks every 30 minutes; check the deposit in the cabinet
  by the sale id (= `merchant_tx_id`).

## Attention

- **`rolled_back`**: Skinslink reported `reverted` after the money left (the balance credited,
  or the card paid). Nothing is debited automatically. Look at the deposit in the cabinet; if
  the seller kept the money for skins we lost, contact them; adjust the balance only with the
  owner's word («Пользователи» → balance adjustment, audited).
- **`late_deposit`**: a sale we closed (`not_created`, a refusal) that Skinslink reports alive.
  The seller may have handed over skins: check the cabinet; if the deposit completed, pay the
  seller by hand (an admin balance adjustment with the sale number in the note).
- **`credit_blocked`**: Skinslink reports `completed` for a balance sale, but the seller's wallet
  is frozen, so the credit was refused. The sale stays in `hold`; each poll (30 min) retries
  and the flag clears when the credit lands. Unfreeze the wallet (or decide with the owner)
  and the next poll credits it; nothing is lost.

## Switching off

The admin's «Выкуп включён» off (instant), or `CSMARKET_SALES_ENABLED=false` (a restart).
Open sales keep settling: the poll and the worker run while the Skinslink key is set.

## Known gaps

Shipped on purpose; none of them puts money at risk.

- A replayed webhook signature can grow `sale_checks` (the signature covers only the id; the
  worker drains the rows and every check is idempotent).
- A failed Skinslink read leaves a sale's `last_polled_at` unset, so `hold` sales are polled
  again every 60 s instead of every 30 minutes until a read succeeds.
- A double submit with two different `Idempotency-Key`s creates two `creating` sales; the
  second one is closed by Skinslink or the poll, nothing is paid twice.
