# 0006. Wallet, payments and balance top-ups through Click, Payme and Uzum (M3)

- **Status**: Accepted
- **Date**: 2026-10-01
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security | data | frontend

## Context and problem statement

M3 (spec §15) gives every customer a soʻm balance and lets them top it up through the three
Uzbek kassas: `wallet` (the ledger), `payments` (top-ups and the attempts to pay them),
`click`, `payme` and `uzum` (each kassa's callback server), the storefront balance page, and
admin users, payments and audit pages. Nothing is bought yet: orders, paying from the balance
and refunds to it are M4. "Done when" is "a balance is topped up through a real kassa".

The owner took two decisions while planning:

- **D1.** One top-up is **1 000 to 10 000 000 soʻm**, whole soʻm only.
- **D2.** **No anti-fraud rules in M3**: only the minimum and the maximum.

Planning settled fourteen rulings (R1–R14) and execution refined several of them. This ADR
records both, so M4 builds on them instead of rediscovering them.

## Decision drivers

- Money is credited **at most once** per top-up, whatever retries, replays, races or second
  kassa transactions arrive, and a customer is never charged twice for one credit.
- Our own code never drives a balance below zero.
- Each kassa authenticates its caller before the body reaches business logic, and answers in
  its own protocol (Click and Payme HTTP 200 with an error body, Uzum HTTP 400), never a 500.
- YuPay's kassa code is proven in production; port it by allow-list (ADR-0002) and keep its
  sandbox-tested behaviour, but drop what served YuPay's products (orders-as-top-ups, guests,
  vetoes, Telegram).
- Logs never tie a person to money; the payer's phone Uzum sends is personal data.

## Considered options

1. **YuPay's model: a top-up is an order** paid like any other, settled by the order's
   provider hooks.
2. **A flat `ledger_entries` table** (one row per balance change) with top-ups as plain rows.
3. **A double-entry ledger, a top-up as its own payable, and attempts per kassa** (chosen).

## Decision outcome

**Chosen option:** 3, as the rulings below.

### Rulings taken while planning

- **R1 — Ledger tables are YuPay's three.** `wallet_accounts`, `wallet_transactions` (the
  header, with a unique idempotency key) and `wallet_postings` (the D/C legs, the spec's
  "ledger entries"). A flat table cannot hold `SUM(D) = SUM(C)` per event. UZS only, so no
  currency column; amounts `numeric(14,0)`.
- **R2 — Account kinds:** `user_wallet` (normal side D), `provider_clearing` (C, owner = the
  kassa slug), `house_payments_received` (D, M4 balance-paid orders) and `house_adjustments`
  (D, the contra-account of admin adjustments). Transaction kinds are the spec's: `topup`,
  `topup_reversal`, `admin_adjust`; M4 adds `purchase` and `refund`.
- **R3 — A top-up has 1..N payment attempts.** `wallet_topups` is what the customer pays;
  `payments` rows (`purpose='topup'`) are attempts, at most one live per kassa, so a declined
  card retried in the same kassa works. YuPay's 2026-09-29 retry fix comes along: a new
  attempt's `provider_ref` is suffixed with its id when an older attempt holds the plain one.
- **R4 — One payment FSM** (`payments.fsm.move`): `created → pending`, then `succeeded`,
  `failed` or `cancelled`; `succeeded → refunded`; `created → succeeded` is legal (a kassa may
  settle without a call we saw). Any other edge is a 409.
- **R5 — One payable resolver** (`payments.payable.resolve`) turns a kassa's account value
  into a payable: `T…` is a top-up, anything else is an order (M4; "not found" in M3).
  Nobody else loads a top-up by number.
- **R6 — Hooks by purpose:** `settle`, `reverse`, `cancel_pending`, plus `ensure_attempt` and
  `mark_pending`. A second successful attempt on a credited top-up is **refused** (Click −4,
  Payme −31051 / −31008, Uzum 10008). `purpose='order'` raises until M4.
- **R7 — A spent top-up cannot be reversed by a kassa.** Payme cancel of a performed
  top-up whose amount is no longer on the balance → −31007; Uzum `/reverse` → 10017. Unspent
  → `topup_reversal`, the top-up `reversed`.
- **R8 — Expiry.** A top-up no kassa has taken up expires after 30 minutes (5-minute sweep);
  attempts a kassa holds are left to that kassa's own timeout sweep (Click 30 min, Payme 12 h,
  Uzum 30 min).
- **R9 — Account field names on the wire:** Click `merchant_trans_id`; Payme `account.order`;
  Uzum `params.order`, also accepting `orderId` and `order_id`. The cabinets must match
  (`docs/runbooks/kassa-setup.md`).
- **R10 — The return URL is ours.** Every intent returns the customer to
  `/account/balance/topups/{number}`; there is no client-supplied return URL, so no open
  redirect to guard.
- **R11 — A dev `mock` kassa** (never in prod) and a dev-only pay route drive the real
  `settle`, for local work and e2e without kassas.
- **R12 — Not in M3:** paying from the balance (M4), admin "settle a stuck payment",
  a kassa kill-switch (credentials decide availability), card refunds from admin (refunds
  start in the kassa's own cabinet).
- **R13 — An admin clawback cannot go below zero** (409 `balance_too_low`). YuPay allowed it.
- **R14 — The real-kassa check moves to the first deploy.** It needs a public URL and the
  owner's kassa credentials; M3 is complete locally with sandbox-shaped tests and the mock
  kassa. The runbook lists the check. **Prod ignores sandbox credentials** (Payme test key,
  Uzum sandbox pair) unless `CSMARKET_KASSA_SANDBOX_ENABLED=true`, set only for the sandbox
  pass and logged at startup: a fake-money tool must never credit a real balance.

### Rulings refined during execution

- **Lock order, everywhere: top-up → kassa transaction row → payment → user wallet.** The
  planned order (payment first) deadlocks a kassa create racing a settle; two-session tests
  prove it. A handler that starts from a kassa transaction id reads the row **without** a
  lock, locks the top-up, then locks the row and re-checks its state. `mark_pending` and
  `cancel_pending` lock the top-up before the payment; timeout sweeps scan
  `FOR UPDATE OF wallet_topups SKIP LOCKED` and handle each row in a SAVEPOINT. Read-only
  methods (Payme `CheckTransaction`, `GetStatement`; Uzum `/status`) take no lock.
- **A refused second charge is persisted.** When a kassa completes a transaction on a top-up
  that was meanwhile credited (through another kassa, or a sibling row sharing the same
  attempt), the refusal is committed with the kassa's row closed — Click −4 and the row
  `CANCELLED`, Payme −31008 and state −1 reason 3, Uzum 10008 and `FAILED` — so the kassa
  drops the charge instead of retrying it. This closes a double-charge path YuPay had.
- **A shared attempt is released only when no other live kassa row holds it**, and
  `cancel_pending` never pulls a settled attempt back.
- **`settle` refuses a `reversed` top-up too**, and `ensure_attempt` refuses paid or reversed
  ones: a reversed top-up cannot be paid again.
- **Insert races:** `ensure_attempt`, `mark_pending` and the kassa row insert share one
  SAVEPOINT (Payme, Uzum), so a loser on another account leaves no pending attempt behind.
  Payme Create with an id of another account → −31008; Uzum `/create` with any known
  `transId` → 10010 (Uzum mandates it).
- **Click bodies are parsed with the standard library** (`application/x-www-form-urlencoded`
  only, ≤ 8 KiB, ≤ 32 fields; anything else −8), so `python-multipart` is not a dependency.
- **The Uzum checkout link sends `order=`** and the Uzum cabinet attribute must be named the
  same; if Uzum cannot name it `order`, the link changes (one line in
  `payments/gateways/uzum.py`), the callbacks already accept all three spellings.
- **Edge:** Payme's `185.234.113.0/28` is enforced in Caddy on top of Basic auth; Uzum has
  no published range and Basic auth is its only gate. Refused callbacks are counted in
  `csmarket_kassa_rejections_total{provider, reason}` and alerted by `KassaRejectionsSpike`.
- **Admin writes** (ban, unban, adjust) require `Idempotency-Key`, lock the target `users`
  row `FOR NO KEY UPDATE`, and are audited with the operator's reason. An admin may adjust any
  balance, including their own (every adjust is audited). Ban refuses oneself, an admin, and an
  already banned account; unban refuses an account that is not banned.
- **A banned account is told why.** The ban is checked before the session blocklist (403
  `account-suspended`, not 401); `refresh_tokens.revoked_reason` (`rotated`, `logout`,
  `admin`, `reuse`) scopes the refresh-reuse trip-wire to rotated tokens, so a device holding
  a cookie revoked by the ban can neither trip it after an unban nor end fresh sessions; the
  shared API client keeps a "suspended" session state distinct from signed out.
- **Top-up creation** is limited by an `ip_guard` bucket `topup-create` (60 a minute per IP,
  10 per IP and account). The status page auto-opens the kassa once, only within 8 s of
  load.

**Dependencies added in M3:** none. (New code only: `core.cursor`, `core.money.wire_uzs`,
the five modules, scheduler jobs, storefront and admin pages; no package or lockfile change.)

### Positive consequences

- A top-up is credited once: the ledger key is `topup:{topup_id}`, and every kassa refuses a
  second successful charge.
- A top-up whose money was spent cannot be reversed by a kassa; reversals of unspent money
  return the balance exactly.
- Order numbers never start with `T`, so one account field per kassa serves both top-ups and
  M4 orders; `payable.resolve` tells them apart.
- Every balance change is one balanced ledger transaction with an actor and, for admins, a
  reason; the audit log names who did what.
- Kassa handlers cannot deadlock each other or the expiry sweep (pinned by tests that fail
  with `DeadlockDetectedError` when the order is flipped).

### Negative consequences

- A customer who spent a top-up and then disputes it with the kassa gets a refusal from us
  (−31007 / 10017); the kassa and the owner settle it by hand.
- Three kassa timeout sweeps plus the top-up sweep: four 5-minute jobs to watch.
- The real-kassa proof waits for the first deploy (R14).
- M4 must add: `purpose='order'` in the hooks, the `wallet` gateway (pay from the balance),
  `purchase` / `refund` ledger kinds, the order FK on `payments`, and order payments in each
  kassa's timeout sweep (today they scan top-up attempts only).

## Validation

- Locally: `make lint typecheck test`; the five money modules at ≥ 95 % coverage; no OpenAPI
  drift; e2e on the dev stack (top-up through the mock kassa, admin adjust, refused clawback,
  ban, audit); hypothesis keeps `SUM(D) = SUM(C)` over random top-up series.
- After the first deploy (R14): one real 1 000 soʻm top-up through each kassa reaches the
  balance and admin Payments, and a reversal from the kassa's cabinet takes it back
  (`docs/runbooks/kassa-setup.md`, **First real top-up**).

## Alternatives considered (detail)

### YuPay's top-up-as-order

One payment path for everything. But a top-up then carries order fields, statuses and guards
it never uses, and M4's orders would inherit top-up special cases. Rejected: a top-up is its
own payable, and `payable.resolve` is the single switch.

### A flat `ledger_entries` table

Simpler to read. It cannot enforce "debits equal credits" per event, has nowhere to book the
kassa's side (clearing) or the house's side (adjustments), and makes reversals ad hoc.
Rejected (R1).

### Client-supplied return URLs

YuPay accepted a `return_url` and had to validate it against an allow-list. A top-up always
returns to the same page of ours, so the parameter buys nothing and costs an open-redirect
check. Rejected (R10).

## References

- Spec §5, §6, §7.9, §10, §12, §13, §15; plan
  `docs/superpowers/plans/2026-10-01-m3-wallet-payments.md`
- [ADR-0002](./0002-port-from-yupay-by-allowlist.md), [ADR-0003](./0003-own-caddy-behind-cloudflare.md),
  [ADR-0004](./0004-steam-auth-and-sessions.md)
- Runbooks: [`kassa-setup.md`](../runbooks/kassa-setup.md), [`click.md`](../runbooks/click.md),
  [`payme.md`](../runbooks/payme.md), [`uzum.md`](../runbooks/uzum.md),
  [`wallet.md`](../runbooks/wallet.md); flow:
  [`balance-topup.md`](../product/flows/balance-topup.md)
- Module READMEs: `apps/api/src/csmarket/modules/{wallet,payments,click,payme,uzum,admin}/README.md`
