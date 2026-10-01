# payments

Balance top-ups and the attempts to pay them through a kassa (spec §5, rulings R3–R6,
R10, R11). Builds on `wallet` (credits and reversals go through `wallet.api`); `wallet`
never imports `payments`.

**Owns:** tables `wallet_topups` and `payments` (migration `0007_payments_topups`).

- `wallet_topups` — what the customer pays: `number` (`T` + 7 Crockford chars, unique),
  `user_id`, `amount_uzs numeric(14,0) > 0`, `status` `pending` | `succeeded` | `expired` |
  `reversed`, `idempotency_key` (unique per user), `expires_at`, `payment_id` (the attempt
  that succeeded; `ON DELETE SET NULL`), `succeeded_at`. A top-up is a _payable_, so it
  lives here; the ledger stays in `wallet`.
- `payments` — one attempt to pay a payable through one kassa: `number`, `purpose`
  `topup` | `order` (`topup_id` set iff `topup`; `order_id` gets its key in M4), `user_id`,
  `provider`, `provider_ref` (unique per provider when set), `amount_uzs`, `status`,
  `idempotency_key` (unique when set), `metadata` (kassa event ids, never PII),
  `created_at`, `updated_at`, `succeeded_at`. A top-up has 1..N attempts, at most one live
  (`created`/`pending`) per provider.

**Interface (`api.py`):** `Payment`, `WalletTopup`, `Payable`, `resolve`, `ensure_attempt`,
`mark_pending`, `settle`, `reverse`, `cancel_pending`, `AlreadyPaidError`,
`TopupSpentError`, `move`, `TRANSITIONS`, `LIVE`, `InvalidTransitionError`,
`unclaimed_external_id`, `PaymentGateway`, `available_providers`, `get_gateway`,
`return_url`.

## Numbers

Top-ups and orders (M4) share the namespace a kassa sees in its account field. A top-up
number starts with `T`; an order number never does (`core.numbers`). `payable.resolve` tells
them apart by that letter.

## FSM (`fsm.py`, ruling R4)

```text
created ──► pending ──► succeeded ──► refunded
   │           ├──────► failed
   │           └──────► cancelled
   └──► succeeded | failed | cancelled
```

`move(payment, to)` is the only place a status changes; it stamps `updated_at`, and
`succeeded_at` on success. Any other edge raises `InvalidTransitionError` (409).
`created → succeeded` is legal: a kassa may settle without an earlier call we saw.

## Payable resolver (`payable.py`, ruling R5)

`resolve(db, account, *, lock=False) -> Payable` — the one way a kassa's account value
(Click `merchant_trans_id`, Payme `account.order`, Uzum `params.order`) becomes a payable.

| Top-up                         | `payable` | `reason`    |
| ------------------------------ | --------- | ----------- |
| `pending`, before `expires_at` | yes       | `ok`        |
| `pending`, past `expires_at`   | no        | `expired`   |
| `succeeded`                    | no        | `paid`      |
| `expired`                      | no        | `expired`   |
| `reversed`                     | no        | `reversed`  |
| anything else (orders in M4)   | no        | `not_found` |

`lock=True` reads the top-up `FOR UPDATE` (re-read even if already in the session).

## Hooks (`hooks.py`, ruling R6)

Every kassa calls these; nothing else changes money state. They flush; the caller commits.

| Hook                                  | Does                                                                             | Idempotent / refuses                                                                                                      |
| ------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `ensure_attempt(payable=, provider=)` | Reuses the top-up's live attempt of that provider, else inserts a `created` one  | `provider_ref = <provider>:<number>`, suffixed `:<payment id>` when an earlier attempt holds it (`unclaimed_external_id`) |
| `mark_pending(payment=)`              | `created → pending` (the kassa now holds a transaction)                          | no-op if `pending`; `InvalidTransitionError` otherwise                                                                    |
| `settle(payment=, event_id=)`         | attempt `succeeded`; top-up `succeeded` with `payment_id`; `wallet.credit_topup` | no-op if this attempt already succeeded; `AlreadyPaidError` if the top-up was credited through another attempt            |
| `reverse(payment=, event_id=)`        | `wallet.reverse_topup`; attempt `refunded`; top-up `reversed`                    | no-op if `refunded`; `TopupSpentError` if the balance no longer covers it (R7); `InvalidTransitionError` if never paid    |
| `cancel_pending(payment=)`            | `created`/`pending` → `cancelled`                                                | no-op on any other status — a settled attempt is never pulled back                                                        |

- **One credit per top-up**: the ledger key is `topup:{topup_id}`, and `settle` refuses a
  second attempt once the top-up is `succeeded` or `reversed` (the kassa then refuses the
  charge — Click −4, Payme −31051 / −31008, Uzum 10008).
- **Paid after expiry**: `settle` credits an attempt the kassa held even when the top-up's
  `expires_at` has passed — the money arrived. A kassa cannot _start_ paying an expired
  top-up: `resolve` refuses it first.
- **No overdraft**: `reverse_topup` locks the user's wallet and refuses when the balance is
  below the amount; nothing is written and the caller rolls back.
- **Lock order, everywhere: top-up → payment → user wallet.** A kassa opening an attempt
  resolves the top-up with `lock=True` before it touches the attempt, so `settle` and
  `reverse` lock the top-up first too (the other order deadlocks a create racing a settle
  — `test_settle_and_a_kassa_create_on_one_topup_do_not_deadlock`). `mark_pending` and
  `cancel_pending` lock only the payment.
- `purpose='order'` raises `NotImplementedError` until M4.

**Logs:** `payments.attempt.created`, `payments.topup.credited`, `payments.topup.reversed`,
`payments.topup.reverse_refused`, `payments.topup.second_payment_refused` — number,
provider and amount only, never the user.

## Gateways (`gateways/`, rulings R10, R11)

A gateway only builds the URL the customer is sent to — `intent_url(payable=, locale=)`;
`ensure_attempt` owns the row and each kassa's callbacks live in its own module.
`registry()` holds every gateway; `available_providers()` lists the available ones in the
order `click, payme, uzum, mock`; `get_gateway(provider)` raises `NotFoundError` (404) for
an unknown or unavailable one. Every intent returns the customer to our own page,
`return_url(number, locale)` = `{web_base_url}[/uz|/en]/account/balance/topups/{number}`
(ru has no prefix) — there is no client-supplied return URL.

`mock` is available everywhere but production; its intent URL is the top-up page with
`?mock=1`, from which the dev-only pay route drives the real `settle`.

**Tests:** `tests/unit/test_payment_fsm.py`, `tests/unit/test_payment_gateways.py`,
`tests/integration/test_payable_resolver.py`, `tests/integration/test_payment_hooks.py`
(including two real races: two kassas settling one top-up, a create racing a settle).
`tests/integration/payments_factory.py` makes users and top-ups for the payments suites.
