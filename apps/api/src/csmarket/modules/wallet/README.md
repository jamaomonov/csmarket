# wallet

The double-entry ledger behind every soʻm balance (spec §5, rulings R1, R2; ADR-0006).
Ported by allow-list (ADR-0002): UZS only, no currency column, whole soʻm. Operations
(reading a history, adjusting, refused reversals): `docs/runbooks/wallet.md`; order purchases and
refunds (M4a): ADR-0007, `docs/runbooks/orders.md`.

**Owns:** tables `wallet_accounts`, `wallet_transactions` and `wallet_postings`
(migration `0006_wallet_ledger`).

- `wallet_accounts` — one per `(owner_type, owner_id, kind)`; `owner_type` is `user`,
  `house` or `provider`; `status` `active` | `frozen` (a frozen account takes no postings).
- `wallet_transactions` — one business event; `idempotency_key` is unique; `reference_*`
  says what it is about; `actor` who did it; `metadata` jsonb (scalars such as the provider or an admin's reason — operator text; no personal data by convention).
- `wallet_postings` — the legs: `direction` `D` | `C`, `amount numeric(14,0) > 0`.
  Append-only; deleted only by `CASCADE` from their transaction.

**Interface (`api.py`):** `post`, `ensure_account`, `user_account`, `balance`,
`user_balance`, `user_balance_column`, `credit_topup`, `reverse_topup`, `debit_purchase`,
`credit_order_refund`, `credit_sale`, `credit_payout_return`, `admin_adjust`,
`ADMIN_ADJUST_MAX`, `entries_for_user`, `entries_for_admin`, `Entry`, `AdminEntry`,
`EntriesPage`, `Leg`, `Reference`, `Direction`, `NORMAL_SIDE`, `TX_KINDS`, `WALLET`
(`"wallet"`: `orders.paid_with` / `payments.provider` of a balance payment),
`InsufficientBalanceError`, and the three models.

**Sales (2026-10-08):** transaction kinds `sale_credit` (key `sale:{sale_id}`) and `payout_return` (key `payout_return:{request_id}`) post D `user_wallet` / C `house_skin_buys`; `house_skin_buys` is a credit-side house account.

**Routes (`routes.py`):** `GET /wallet` → `{balance_uzs}` and `GET /wallet/entries` for
the signed-in customer. The top-up routes under `/wallet/topups` are mounted from
`payments.routes`.

**Direction:** `wallet` never imports `payments` — `payments` (and M4a `orders`, and
`admin`) build on it, never the reverse. `wallet.api`, `service`, `adjust` and `entries` are
domain-pure (no other domain module); only `wallet.routes` imports `auth.api` and
`users.models` for the signed-in customer (`test_wallet_never_imports_payments`).

## Rules

- **`post()` is the only writer** of the three tables. Nothing else inserts or updates
  them. It flushes and never commits: the caller's transaction decides.
- Every transaction has **≥ 2 legs** with **`SUM(D) == SUM(C)`**; each amount is a
  positive whole soʻm (`ValidationError` otherwise, before anything is written); every
  account exists (`NotFoundError`) and is `active` (`ConflictError`).
- **One idempotency key per business event.** A key already used returns the stored
  transaction unchanged; a concurrent post of the same key loses inside a SAVEPOINT and
  returns the winner's — the caller's own work in that transaction survives. A key that
  booked another `kind` raises `ConflictError(code="idempotency_mismatch")` instead.
  `ensure_account` is race-safe the same way.
- **Balance = SUM on the normal side − SUM on the other side**, per account.
  `user_balance` is `0` when the user has no wallet yet and never creates one.
- **No overdraft by our code.** The ledger does not check a debit against a balance;
  a caller that debits a user wallet first takes `user_account(db, user_id, lock=True)`
  (`SELECT … FOR UPDATE`), then reads `balance`, then posts — and raises
  `InsufficientBalanceError` (409) when it does not cover the amount.

## Account kinds

| Kind                      | Owner                                 | Normal side | Meaning                                     |
| ------------------------- | ------------------------------------- | ----------- | ------------------------------------------- |
| `user_wallet`             | `user` / user id                      | D           | The customer's spendable soʻm               |
| `provider_clearing`       | `provider` / `click`, `payme`, `uzum` | C           | What a kassa collected for us               |
| `house_payments_received` | `house` / `house`                     | D           | Orders paid from the balance (M4a)          |
| `house_adjustments`       | `house` / `house`                     | D           | Contra-account of admin balance adjustments |

## Transaction kinds and keys

| Kind             | Legs                                                                                                                        | Idempotency key                  |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| `topup`          | D `user_wallet` / C `provider_clearing`                                                                                     | `topup:{topup_id}`               |
| `topup_reversal` | D `provider_clearing` / C `user_wallet`                                                                                     | `topup_reversal:{topup_id}`      |
| `admin_adjust`   | credit: D `user_wallet` / C `house_adjustments`; clawback: the mirror                                                       | `admin_adjust:{idempotency_key}` |
| `purchase`       | D `house_payments_received` / C `user_wallet` (an order paid from the balance)                                              | `purchase:order:{order_id}`      |
| `refund`         | balance-paid order: D `user_wallet` / C `house_payments_received`; kassa-paid: D `user_wallet` / C `provider_clearing` (R9) | `refund:order:{order_id}`        |

`purchase` and `refund` are in `TX_KINDS` since M4a; `orders` books them (one each per order)
through `purchases.py`, below.

`credit_topup(db, *, user_id, topup_id, amount, provider)` and `reverse_topup(...)` (same
arguments) book the first two rows; `payments.hooks` calls them. `reverse_topup` answers a
replayed key first, then locks the user's wallet and raises `InsufficientBalanceError` when
the balance is below the amount.

## Admin adjustments (`adjust.py`)

`admin_adjust(db, *, user_id, amount, reason, admin_id, idempotency_key)` — `amount` a
non-zero whole soʻm, `|amount| ≤ ADMIN_ADJUST_MAX` (100 000 000), and a non-blank reason
(`ValidationError` `adjust_amount` / `adjust_reason`). It locks the user's wallet, then looks
up the key `admin_adjust:{idempotency_key}`: a replay returns the booked transaction (before
any balance check); the key on another user or amount is `ConflictError`
`idempotency_mismatch`. A clawback the balance does not cover raises
`InsufficientBalanceError` with `code="balance_too_low"` (ruling R13 — never below zero).
`actor = "admin:<admin_id>"`, `metadata = {"reason"}`. Its own file only to keep `service.py`
under the size limit.

## Orders (`purchases.py`, rulings R8, R9)

`debit_purchase(db, *, user_id, order_id, amount)` — an order paid from the balance: C
`user_wallet` / D `house_payments_received`, reference `("order", order_id)`, actor `orders`.
It locks the user's wallet `FOR UPDATE` (the caller already holds the order row — lock
order order → payment → wallet), then looks up the key `purchase:order:{order_id}`: a
replay returns the booked transaction before any balance check. A balance below `amount`
raises `InsufficientBalanceError` with `code="balance_too_low"` and writes nothing.

`credit_order_refund(db, *, user_id, order_id, amount, paid_with, actor="orders")` — the
order's money back to the balance, once (key `refund:order:{order_id}`). `paid_with ==
"wallet"`: D `user_wallet` / C `house_payments_received` (the purchase undone). A kassa:
D `user_wallet` / C `provider_clearing:<paid_with>` — a kassa-paid order books nothing when
it is paid, so its refund has the shape of a top-up (the kassa's money becomes balance;
`provider_clearing`'s normal side is C, so it grows and never goes negative). No wallet lock
(a credit cannot overdraw). `metadata = {"paid_with"}`. A `paid_with` outside `wallet`,
`click`, `payme`, `uzum`, `mock` (`REFUND_SOURCES`) is a `ValueError` before anything is
written — a caller bug must not mint a stray clearing account. Sale revenue is not booked
in the ledger in M4a. `orders.refunds.refund_to_balance` is its only caller.

## Customer entries (`entries.py`)

`entries_for_user(db, user_id, *, cursor=None, limit=20, entry_type=None)` — only the customer's
`user_wallet` leg of each transaction, newest first, keyset-paged on
`(posting.created_at DESC, posting.id DESC)` with an opaque base64 cursor (a malformed one
is a 422); `limit` 1..100. Each line: the transaction id, `kind`, the **signed** amount (+
when the leg is D — the account's normal side — − when C) and the public number of what
it is about: the top-up's `T…` number for `topup` / `topup_reversal`, the order's number
for `purchase` / `refund`. **Never the actor or the metadata** — an admin's identity and
reason stay in admin views. The numbers are read through bare `table("wallet_topups")` /
`table("orders")` clauses (one query per kind present on the page), so `wallet` still
imports nothing from `payments` or `orders`. No
wallet yet → an empty page (none is created). `entry_type` (`ENTRY_TYPES`) narrows the
kinds: `topup` → `topup` + `topup_reversal`; `withdrawal` → none until payouts exist (an
empty page without a query).

`entries_for_admin(db, user_id, *, limit=20)` shares the query and returns `AdminEntry`
(an `Entry` plus `actor` and `reason` = `metadata.reason`) — admin views only; the customer
route never builds one. `user_balance_column(user_id_column)` is a correlated scalar
subquery of the `user_wallet` balance, for list queries (one statement per page).

**Logs:** `csmarket.wallet.service` writes `wallet.posted` (kind, transaction id, amount) —
no user id, so a log line never ties a person to money.

**Tests:** `tests/integration/test_wallet_ledger.py` (postings, replay, refused legs,
frozen and missing accounts, both SAVEPOINT races) and `test_wallet_ledger_props.py`
(hypothesis: `SUM(D) == SUM(C)` over random top-up series, and over random top-ups,
purchases and refunds with the balance never below zero), `test_wallet_purchase.py` (legs,
replays, `balance_too_low`, both refund shapes), `test_wallet_routes.py`
(balance, signed entries, redaction, keyset paging, owner only), `test_wallet_admin_adjust.py`
(credit, clawback, never below zero, replay, admin entries).

## Dollar wallet routes (public API plan A)

- `GET /wallet` carries `usd: {balance_usd, rate_uzs}` once `users.usd_wallet_enabled`; else `null`.
- `POST /wallet/convert {amount_uzs}` + `Idempotency-Key` converts soʻm to dollars at CBU plus the
  uplift (201; a replay 200). Ledger key `fx_convert:` + sha256 of `<user id>:<key>`. Errors: 403
  `usd_wallet_disabled`, 409 `balance_too_low` / `idempotency_mismatch`, 422 `convert_amount`,
  503 `rate_unavailable`.
- `GET /wallet/entries?currency=usd` lists dollar lines (`amount_usd`, signed; `amount_uzs` is `"0"`).
