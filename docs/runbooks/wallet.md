# Runbook — the balance (wallet ledger)

Every customer balance is a double-entry ledger in soʻm. This runbook explains it in plain
words, how to read a customer's history in admin, how to adjust a balance, and why a kassa
reversal can be refused. Reference: `apps/api/src/csmarket/modules/wallet/README.md`; design:
ADR-0006. Kassas: [`kassa-setup.md`](./kassa-setup.md).

## The model in plain words

- Each balance change is **one transaction** with **two or more legs**; the debits equal the
  credits. Nothing changes a balance except `wallet.post()`.
- The customer's balance is their `user_wallet` account. The other side of a top-up is the
  kassa's clearing account (`provider_clearing`, what Click / Payme / Uzum collected for us);
  the other side of an admin adjustment is `house_adjustments`.
- Each transaction has an **idempotency key**, so a business event is booked once whatever
  retries arrive: `topup:{topup id}`, `topup_reversal:{topup id}`,
  `admin_adjust:{Idempotency-Key}`.
- **A balance never goes below zero** through our code. A reversal or a clawback that the
  balance does not cover is refused, and nothing is written.
- Whole soʻm only. M4 adds `purchase` (pay from the balance) and `refund`.

| What the customer sees («История») | Kind             | Effect                                  |
| ---------------------------------- | ---------------- | --------------------------------------- |
| «Пополнение»                       | `topup`          | + amount, from a kassa                  |
| «Пополнение отменено»              | `topup_reversal` | − amount, the kassa refunded it         |
| «Корректировка»                    | `admin_adjust`   | ± amount, an operator; reason not shown |

## Reading a customer's history in admin

Admin → «Пользователи» → search by name or exact 17-digit Steam ID → the card:

- «Баланс: N сум» — the current balance.
- «История баланса» — the latest 20 ledger lines, newest first: kind, signed amount, date. An
  adjustment also shows «кто: администратор» (a link to that admin) and «причина: …».
- «Пополнения» — the latest 20 top-ups: number (a link to «Платежи» filtered by it), amount,
  status («ждёт оплаты», «зачислено», «истекло», «отменено кассой»), kassa, date.

For one top-up's detail (attempts, kassa transactions): «Платежи» → search the number. For who
changed what: «Журнал», filter «Id цели» = the user's id.

The admin card shows the trade link masked and the Steam ID; never copy either into chat.

## Adjusting a balance

Use it for a compensation, or when money provably reached us without a credit (after checking
the kassa runbook). Never write to `wallet_*` tables by hand.

1. The user's card → «Изменить баланс».
2. «Сумма, сум»: positive to credit, negative to take back (up to 100 000 000 either way).
   «Причина изменения»: 4..500 characters, in plain words, naming the top-up number when there
   is one. No personal data in the reason (it is stored and shown to every admin).
3. «Продолжить» → check the confirm step («Начислить …» / «Списать …») → confirm.
4. The card reloads with the new balance; «Журнал» has a `wallet.adjust` row with your name,
   the signed amount and the reason.

- A clawback larger than the balance is refused: «На балансе меньше, чем вы хотите списать.»
  (409 `balance_too_low`). Nothing is written and no audit row appears.
- Pressing confirm twice, or a network retry, books once (the same idempotency key).
- An admin can adjust any balance, their own included; every adjustment is audited.

## Why a kassa reversal can be refused

A customer tops up, spends part of the balance (M4: buys a skin), then disputes the payment
with the kassa. The kassa calls our cancel / reverse; we would have to take the full top-up
back, and the balance no longer covers it. We refuse rather than go negative:

- Payme: −31007; Uzum: 10017; Click has no merchant reversal at all.
- Log: `payments.topup.reverse_refused number= amount=` (no user id). Nothing changes on our
  side; the top-up stays «зачислено».
- The kassa and the owner settle it outside the system. If the owner decides to take back
  what is left, use a clawback adjustment with a reason naming the top-up number.

An unspent top-up reverses cleanly: «Пополнение отменено», the top-up «отменено кассой», the
attempt «возвращён».

## Logs and checks

- `wallet.posted kind= transaction_id= amount=` — one per ledger transaction. Money log lines
  carry numbers and amounts, never a user id.
- To prove a balance by hand (read-only), in `make psql` on dev or
  `docker compose -f docker-compose.prod.yml exec postgres psql …` in prod, sum the user's
  `user_wallet` postings: D minus C. It must equal «Баланс» in admin.

## Never

- Never insert, update or delete `wallet_accounts`, `wallet_transactions` or
  `wallet_postings` by hand — not even to "fix" a balance.
- Never credit a top-up twice "to be sure": the ledger already refuses the second time, and an
  adjustment on top of a credit doubles the money.
