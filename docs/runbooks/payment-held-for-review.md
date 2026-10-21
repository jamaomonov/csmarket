# Runbook — a kassa payment is held for review

Design: ADR-0022, spec `2026-10-21-payment-risk-limits-design.md`. Alert `PaymentHeldForReview`
fires when any hold is open for a minute (label `reason`: `kassa_limit`, `user_limit`,
`check_failed`).

## What it means

Money came in through a kassa (Payme, Click, Uzum, P2P) and went over a limit: the user's money
through that kassa in the window (default 2 000 000 soʻm / 24 h), or the user's own limit.
The kassa has the money. A top-up is **not credited** and an order's skin is **not bought**
until an admin decides. The buyer sees «Оплата получена, проверяем платёж».

`check_failed`: the check itself broke and the payment was held to be safe. Look at the API
logs for `payments.risk.check_failed`, fix the cause (usually the database), then decide the
hold as usual.

## Look at it

1. Admin → «На проверке» (a counter in the menu): number, kind, kassa, amount, reason, the
   window sum and the limit at hold time.
2. Open the user card → «Риск»: money in through kassas over the last 24 h and 7 d, other open
   holds, the policy. Also the user's orders and Steam profile age.
3. Decide. Both buttons ask for a confirm and are safe to press twice.

## Release — «Пропустить»

The payment looks honest. A top-up is credited to the balance; an order goes `paid` and the
worker buys. If the lot sold meanwhile, the usual buy failure refunds to the balance.
To stop asking about this person, set «Доверенный» on the card (Риск), or raise the kassa
limit.

## Return — «Вернул на карту»

The payment looks like carding. Return the money **first**, in the kassa, then press the
button (it only records the fact; nothing reaches the balance):

- **Payme:** merchant cabinet → the transaction → cancel / refund.
- **Click:** merchant cabinet → the payment → refund.
- **Uzum:** merchant cabinet → the payment → reverse.
- **P2P:** transfer the sum back from our card to the sender's card (the card number in the
  HUMO notification), then press the button.

A top-up ends `rejected`, an order `cancelled`. If the kassa cancels the payment on its own
(Payme `CancelTransaction`, a Click or Uzum reverse), the hold closes by itself as
`reversed_by_kassa`; nothing to press.

A decided hold answers 409 `hold_decided`; reload the list.

## Change limits and users

- Limits per kassa: Настройки → Оплата → «Лимит без проверки» (switch, sum, window).
  A stale tab is refused (409 `settings_stale`); reload.
- A user: card → «Риск»: «Доверенный» (bypasses both limits), «Запретить оплату кассой»
  (403 `kassa_payment_blocked` when starting a kassa payment; the balance still works), an own
  limit (sum, window), a note (not shown to the buyer).
