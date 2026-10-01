# wallet

The double-entry ledger behind every soʻm balance (spec §5, rulings R1, R2). Ported by
allow-list (ADR-0002): UZS only, no currency column, whole soʻm.

**Owns:** tables `wallet_accounts`, `wallet_transactions` and `wallet_postings`
(migration `0006_wallet_ledger`).

- `wallet_accounts` — one per `(owner_type, owner_id, kind)`; `owner_type` is `user`,
  `house` or `provider`; `status` `active` | `frozen` (a frozen account takes no postings).
- `wallet_transactions` — one business event; `idempotency_key` is unique; `reference_*`
  says what it is about; `actor` who did it; `metadata` jsonb (never PII).
- `wallet_postings` — the legs: `direction` `D` | `C`, `amount numeric(14,0) > 0`.
  Append-only; deleted only by `CASCADE` from their transaction.

**Interface (`api.py`):** `post`, `ensure_account`, `user_account`, `balance`,
`user_balance`, `user_balance_column`, `credit_topup`, `reverse_topup`, `admin_adjust`,
`ADMIN_ADJUST_MAX`, `entries_for_user`, `entries_for_admin`, `Entry`, `AdminEntry`,
`EntriesPage`, `Leg`, `Reference`, `Direction`, `NORMAL_SIDE`, `TX_KINDS`,
`InsufficientBalanceError`, and the three models.

**Routes (`routes.py`):** `GET /wallet` → `{balance_uzs}` and `GET /wallet/entries` for
the signed-in customer. The top-up routes under `/wallet/topups` are mounted from
`payments.routes`.

**Direction:** `wallet` never imports `payments` — `payments` (and M4 `orders`, and
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
  returns the winner's — the caller's own work in that transaction survives.
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
| `house_payments_received` | `house` / `house`                     | D           | Orders paid from the balance (M4)           |
| `house_adjustments`       | `house` / `house`                     | D           | Contra-account of admin balance adjustments |

## Transaction kinds and keys

| Kind             | Legs                                                                  | Idempotency key                  |
| ---------------- | --------------------------------------------------------------------- | -------------------------------- |
| `topup`          | D `user_wallet` / C `provider_clearing`                               | `topup:{topup_id}`               |
| `topup_reversal` | D `provider_clearing` / C `user_wallet`                               | `topup_reversal:{topup_id}`      |
| `admin_adjust`   | credit: D `user_wallet` / C `house_adjustments`; clawback: the mirror | `admin_adjust:{idempotency_key}` |
| `purchase` (M4)  | D `house_payments_received` / C `user_wallet`                         | `purchase:{order_id}`            |
| `refund` (M4)    | D `user_wallet` / C `house_payments_received`                         | `refund:{order_id}`              |

M4 adds `purchase` and `refund` to `TX_KINDS`.

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

## Customer entries (`entries.py`)

`entries_for_user(db, user_id, *, cursor=None, limit=20)` — only the customer's
`user_wallet` leg of each transaction, newest first, keyset-paged on
`(posting.created_at DESC, posting.id DESC)` with an opaque base64 cursor (a malformed one
is a 422); `limit` 1..100. Each line: the transaction id, `kind`, the **signed** amount (+
when the leg is D — the account's normal side — − when C) and, for `topup` /
`topup_reversal`, the top-up's `T…` number. **Never the actor or the metadata** — an
admin's identity and reason stay in admin views. The number is read through a bare
`table("wallet_topups")` clause, so `wallet` still imports nothing from `payments`. No
wallet yet → an empty page (none is created).

`entries_for_admin(db, user_id, *, limit=20)` shares the query and returns `AdminEntry`
(an `Entry` plus `actor` and `reason` = `metadata.reason`) — admin views only; the customer
route never builds one. `user_balance_column(user_id_column)` is a correlated scalar
subquery of the `user_wallet` balance, for list queries (one statement per page).

**Logs:** `csmarket.wallet.service` writes `wallet.posted` (kind, transaction id, amount) —
no user id, so a log line never ties a person to money.

**Tests:** `tests/integration/test_wallet_ledger.py` (postings, replay, refused legs,
frozen and missing accounts, both SAVEPOINT races) and `test_wallet_ledger_props.py`
(hypothesis: `SUM(D) == SUM(C)` over random top-up series), `test_wallet_routes.py`
(balance, signed entries, redaction, keyset paging, owner only), `test_wallet_admin_adjust.py`
(credit, clawback, never below zero, replay, admin entries).
