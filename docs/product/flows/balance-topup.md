# Flow — Top up the balance

A signed-in customer adds soʻm to their balance through Click, Payme or Uzum. In M3 the
balance only grows and shrinks by top-ups, kassa refunds and admin adjustments; paying from
it arrives with orders (M4). Design: ADR-0006; operations: `docs/runbooks/kassa-setup.md`.

## What the customer sees

1. `/account/balance` («Баланс») shows «На балансе», the top-up form and «История». Signed
   out, it asks to sign in with Steam.
2. They enter an amount (from 1 000 to 10 000 000 soʻm, whole soʻm; quick chips help), choose
   a kassa tile and press «Пополнить на 50 000 сум». A wrong amount is refused in the form with
   «Сумма от 1 000 сум до 10 000 000 сум, без тийинов.». No kassa available: «Пополнение сейчас
   недоступно.».
3. The browser moves to the top-up's own page, `/account/balance/topups/T…`, which opens the
   kassa once (only if the answer came within 8 s; otherwise the «Перейти к оплате» button
   stays). Coming back to this tab later never re-opens the kassa.
4. They pay in the kassa and are returned to the same page. It says «Ждём оплату» and checks
   every 3 seconds (and at once when the tab is focused again), then «Баланс пополнен на 50 000
   сум» with «К балансу».
5. The balance page shows the new balance and a history line «Пополнение» with the amount and
   the top-up's number.

Other endings on the top-up page:

- **Not paid in 30 minutes:** «Время на оплату вышло. Создайте новое пополнение.»
- **Past 30 minutes, but the kassa is still processing it** (`awaiting_kassa`): «Проверяем
  оплату» with «Если вы оплатили, баланс пополнится сам. Новое пополнение не нужно.»; the page
  keeps checking and turns into «Баланс пополнен на …» when the kassa confirms.
- **Refunded by the kassa:** «Пополнение отменено.», and the history shows «Пополнение
  отменено» with a minus.
- **Someone else's or unknown number:** «Пополнение не найдено.» (the API answers 404, never
  403, so a number reveals nothing).
- **Checks ran out** (about 2 minutes): an «Обновить» button restarts them.

Rules the customer never has to know: one top-up is credited once, whatever the kassa repeats;
a second charge on a paid top-up is refused at the kassa, so the card is not charged twice;
a refund the balance no longer covers is refused (the money was spent).

## Sequence

```mermaid
sequenceDiagram
    autonumber
    actor U as Signed-in customer
    participant Web as Balance page / status page
    participant API as API
    participant DB as Postgres
    participant K as Kassa (Click / Payme / Uzum)
    participant S as Scheduler

    U->>Web: Amount + kassa, «Пополнить на …»
    Web->>API: POST /wallet/topups {amount_uzs, provider, locale} + Idempotency-Key
    API->>API: ip_guard topup-create, 1 000..10 000 000 soʻm, kassa available
    API->>DB: wallet_topups T… (pending, expires_at +30 min) + payments attempt (created)
    API-->>Web: 201 {number, intent_url}
    Web->>Web: Go to /account/balance/topups/T…?go=1
    Web->>API: GET /wallet/topups/T…
    API-->>Web: pending, intent_url
    Web->>K: Auto-open intent_url once (within 8 s), else «Перейти к оплате»

    Note over API,DB: Every callback: auth before the body, then lock order<br/>top-up → kassa row → payment → user wallet
    K->>API: Check / prepare / create (account = T…, amount)
    API->>DB: resolve(T…, lock): payable? amount equal (soʻm / tiyin)?
    alt not payable (paid, expired, reversed, unknown) or wrong amount
        API-->>K: Kassa error code (nothing written)
    else payable
        API->>DB: kassa row + attempt created → pending
        API-->>K: OK
    end

    U->>K: Pays
    K->>API: Perform / complete / confirm
    API->>DB: Lock top-up, then kassa row, re-check state
    alt top-up already credited (another kassa or sibling row)
        API->>DB: Kassa row closed (cancelled / failed), committed
        API-->>K: Refused (Click −4, Payme −31008, Uzum 10008): no second charge
    else first success
        API->>DB: settle: attempt succeeded, top-up succeeded,<br/>ledger topup D user_wallet / C provider_clearing (key topup:{id})
        API-->>K: OK
    end
    K-->>Web: Customer returns to /account/balance/topups/T…

    loop every 3 s while pending (refetch on focus)
        Web->>API: GET /wallet/topups/T…
        API-->>Web: status, intent_url, awaiting_kassa
        opt pending, no intent_url, awaiting_kassa (a kassa holds it past expires_at)
            Web-->>U: «Проверяем оплату» (keeps checking)
        end
    end
    Web-->>U: «Баланс пополнен на …» → «К балансу»

    opt nobody paid
        S->>DB: Kassa sweeps close stale kassa rows (Click / Uzum 30 min, Payme 12 h)
        S->>DB: Top-up sweep (every 5 min): pending past expires_at, no live attempt → expired
        Web-->>U: «Время на оплату вышло. Создайте новое пополнение.»
    end

    opt refund started in the kassa's cabinet (Payme, Uzum)
        K->>API: Cancel / reverse
        alt amount still on the balance
            API->>DB: ledger topup_reversal (key topup_reversal:{id}), attempt refunded, top-up reversed
            API-->>K: OK
        else balance no longer covers it
            API-->>K: Refused (Payme −31007, Uzum 10017), nothing changes
        end
    end
```

Source: `docs/architecture/sequence-diagrams/topup.mmd`.

- Account field on the wire (R9): Click `merchant_trans_id`, Payme `account.order`, Uzum
  `params.order` (also `orderId`, `order_id`). Amount units: Click soʻm, Payme and Uzum tiyin
  (Uzum's `/check` answers soʻm).
- Locally and in e2e the `mock` kassa (never in prod) stands in: the top-up page shows
  «Оплатить (тест)», which calls the dev-only `POST /api/v1/dev/topups/{number}/pay` and runs
  the same `settle`.
- Rules: spec §5, §7.9, §13; module READMEs `payments`, `wallet`, `click`, `payme`, `uzum`.
