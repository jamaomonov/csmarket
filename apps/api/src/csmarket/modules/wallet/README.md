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
`user_balance`, `credit_topup`, `reverse_topup`, `Leg`, `Reference`, `Direction`, `NORMAL_SIDE`, `TX_KINDS`,
`InsufficientBalanceError`, and the three models. `wallet` imports no other domain
module — `payments` (and M4 `orders`) build on it, never the reverse.

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

**Logs:** `csmarket.wallet.service` writes `wallet.posted` (kind, transaction id, amount) —
no user id, so a log line never ties a person to money.

**Tests:** `tests/integration/test_wallet_ledger.py` (postings, replay, refused legs,
frozen and missing accounts, both SAVEPOINT races) and `test_wallet_ledger_props.py`
(hypothesis: `SUM(D) == SUM(C)` over random top-up series).
