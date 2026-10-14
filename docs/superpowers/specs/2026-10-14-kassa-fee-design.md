# Kassa fee paid by the buyer

Approved in conversation with the owner on 2026-10-14. Comes before the analytics page (its
«Комиссии касс» lines read what this records).

## Goal

Click, Payme and Uzum take a percentage of every payment. The buyer pays it: the price stays the
skin's (or the top-up's) own, the kassa tile shows its percent, and the total adds it.

## Owner rulings

1. **A rate per kassa**, set by the admin, default 0 (nothing changes until a rate is typed).
2. **On top**: `fee = ceil(base × pct / 100)` whole soʻm; the kassa charges `base + fee`.
3. **Both an order paid through a kassa and a balance top-up** carry it — otherwise topping up
   would dodge it. Paying from the balance carries none.
4. **A failed order refunded to the balance gets the price back, not the fee.** The kassa keeps
   its fee whatever happens to the order.
5. **A kassa cancelling a payment** (Payme / Uzum reversal of a top-up) returns the whole paid sum
   to the card — that is the kassa's own doing; on our side the balance loses the credited amount,
   as today.
6. **No change to the legal documents** — «сумма заказа» is the price; the fee is obvious.

## Data

- `payment_settings` — a singleton JSONB document like `sale_settings`:
  `{fee_pct: {click, payme, uzum}}`, each a decimal 0–10 with two places. Admin read / write with
  If-Match and Idempotency-Key, audited `payments.settings`.
- `payments.fee_uzs numeric(14,0) not null default 0` and `payments.fee_pct numeric(5,2) not null
default 0`: what this attempt adds. `payments.amount_uzs` stays the **base** (the order's price,
  the top-up's credit); the kassa's amount is `amount_uzs + fee_uzs`.
- The rate is fixed when the attempt row is created (`ensure_attempt`): a later change in the admin
  does not move an open payment, and the amount the kassa was shown is the one it is checked against.

## Money path

- `Payable` gains `fee_uzs` and `charge_uzs = amount_uzs + fee_uzs`, read from the provider's
  attempt (or the current rate when the webhook creates it). Every kassa-facing amount uses
  `charge_uzs`: the Click and Payme intent URLs, Payme `CheckPerformTransaction` /
  `CreateTransaction` (−31001), Click prepare (−2), Uzum `/check` and create (10011).
- Settle: the order is paid at its price, the top-up credits its `amount_uzs` — unchanged.
- Ledger: the kassa's clearing account takes the gross (`amount + fee`); the fee lands in a new
  income account `kassa_fee` — so clearing still matches what the kassa settles.
- Refund to the balance credits `order.price_uzs` — unchanged (the fee stays booked as income).
- A top-up reversal debits the balance by `topup.amount_uzs` and reverses the fee entry.

## Storefront

- `GET /payments/providers` → `[{slug, fee_pct}]`.
- Payment tiles: under the name, «1 %» when the rate is above 0.
- The buy form and the order's pay block: «Цена», «Комиссия <kassa>», «Итого» when a kassa with a
  fee is picked; the pay button says the total. The balance tile: the price only.
- Top-up: «На баланс», «Комиссия <kassa>», «К оплате».
- The web computes the fee for display with the same rounding; the API's attempt is the truth (a
  rate changed between page load and pay shows the new total on the kassa's page — rare and honest).

## Admin

- «Настройки оплаты»: three fields «Комиссия Click / Payme / Uzum, %».
- Payment detail: «Комиссия» beside the amount; the payments list shows the total paid.

## Out of scope

Refund to card for orders (there is no such path; support handles it by hand, the whole paid sum).
Fee per amount band or a fixed fee part. Public API (it pays from the USD wallet, no kassa).

## Testing

Unit: the fee rounding (0 %, 1 %, 1.5 %, a sum that rounds up). Integration per kassa: the intent
amount, the webhook accepts `base + fee` and refuses `base`; the rate is frozen on the attempt; a
top-up credits the base; a refund returns the price; a Payme reversal of a top-up undoes the fee
entry; the settings endpoint validates and audits. Web: the tile percent, the totals on the buy
form, the order pay block and the top-up form.
