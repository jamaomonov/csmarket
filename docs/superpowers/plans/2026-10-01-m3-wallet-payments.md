# M3 — Wallet, Balance Top-ups through Click / Payme / Uzum, Admin Users and Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in customer tops up their soʻm balance through Click, Payme or Uzum and sees it on
`/account/balance`; the money lands in a double-entry ledger exactly once; an admin finds any
customer or payment, adjusts a balance with a reason, bans an account, and every such action is
audited.

**Architecture:** New `wallet` module (YuPay's three-table ledger: accounts, transactions,
postings; UZS only) and new `payments` module (payments + `wallet_topups`, an explicit payment
FSM, one payable resolver by number, three provider hooks re-pointed from YuPay's orders to a
purpose switch), plus the acquirer webhook twins `click`, `payme`, `uzum` ported from YuPay with
their transaction tables keyed by payment instead of order. Top-up numbers are `T` + 7
Crockford chars; M4 order numbers will never start with `T`. Storefront gets `/account/balance`
and a top-up status page; admin gets Users, Payments and Audit pages.

**Tech Stack:** FastAPI · SQLAlchemy 2 async · Alembic · Postgres 16 · Redis 7 · APScheduler ·
pytest + testcontainers + hypothesis · Next.js 15 + next-intl · Vite + React 19 + TanStack Query ·
Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md` — §2 (decisions 2, 3, 6), §3.2
(`payments`+`click/payme/uzum`, `wallet`, `admin`), §5 (`payments`, `wallet_accounts`,
`ledger_entries`, `wallet_topups`, `admin_audit_log`), §6 (numbers), §7.5, §7.9, §10 (`/account/balance`,
admin Users / Payments / Audit), §12 (alerts), §13, §14, §15 row M3. Rulebook: `AGENTS.md` (§4–§12,
§14).

**Source material (read-only):** `/Users/macbook_uz/Projects/yupay`. Backend modules under
`yupay:apps/api/src/yupay/modules/` are written `ym:<module>/<file>`; tests under
`yupay:apps/api/tests/`. Copy a Python file through the rename filter from the repo root —
`sed -f scripts/port-rename.sed <yupay file> > <dst>` — then apply the task's deltas. Never write to
YuPay. YuPay's design docs worth reading for each acquirer are named in its task.

## Global Constraints

- **Owner decisions for M3 (2026-10-01, in conversation):** (D1) one top-up is **1 000 to 10 000 000 soʻm**, whole soʻm only; (D2) **no anti-fraud rules in M3** — only the min/max.
- **Money:** `Decimal`, whole soʻm in our tables (`numeric(14,0)`); Payme and Uzum speak **tiyin** on the wire (1 soʻm = 100 tiyin; Uzum's `/check` `data.amount.value` is soʻm), Click speaks **soʻm**; never floats. (spec §5, §13)
- **Ledger:** every balance change is one `wallet.post()` with ≥ 2 legs and `SUM(D) == SUM(C)`; nothing else writes `wallet_*` tables; an idempotency key per business event; the user's balance is never driven below zero by our own code. (spec §5, AGENTS §10)
- **Top-up credited at most once** (key `topup:{topup_id}`), whatever retries, replays or second acquirer transactions arrive.
- **Webhooks:** each acquirer authenticates before the body is parsed into business logic; Click and Payme answer HTTP 200 with an error body, Uzum answers 400 on any error; a DB commit failure still renders a protocol error, never a 500. Acquirer routes are exempt from slowapi in `bootstrap._exempt_self_authenticating_routes`. (spec §13)
- **Idempotency:** every state-changing customer/admin endpoint takes `Idempotency-Key` (≥ 16 chars) and persists by it; a replayed key with a different body is 409. (AGENTS §10)
- **Admin actions audited** in `admin_audit_log` (ban, unban, wallet adjust) with a reason; payloads carry no PII. (spec §13)
- **Never log PII** (Steam ID, email, IP, trade-link token) **or secrets** (Click secret, Payme keys, Uzum passwords, Basic-auth headers); Uzum `payment_source` holds the payer's phone — stored, never logged, masked in admin. No user id in money log lines ("logs never correlate identity with financial activity"). (AGENTS §10)
- **Copy (owner):** short sentences; outcome, not mechanism; no refund/acquirer internals for customers; «вы»; ru / uz / en, every key in all three; UZ uses ʻ (U+02BB) after o/g and ʼ (U+02BC) elsewhere. Admin copy is Russian. (AGENTS §12)
- **Payment-provider names in indexed storefront copy:** M2 removed Click/Payme/Uzum from SEO meta until kassas work; M3 does **not** put them back (they return with M5 launch copy). The balance page (not indexed) shows the provider tiles.
- **Forbidden tokens** in `apps/*/src`, `packages/*/src`: `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`, `merchant_api`, `voucher`, `game_id`; `merchant_trans_id` is allow-listed (Click wire field). YuPay comments saying "supplier" or "order" for a top-up are reworded. (AGENTS §6)
- **Routers mount in `apps/api/src/csmarket/api/v1/router.py`** from each module's `routes.py`; `tests/unit/test_import_order.py` lists every new module; `wallet` never imports `payments` (one direction: `payments` → `wallet`). Every route change regenerates `docs/api/openapi.json` in the same commit.
- **Scheduler jobs** only time work, `first_run_after(n)` staggered ≥ 15 s; existing first runs are 20, 60, 120, 300 s. (AGENTS §4)
- **Dev ports** api 8100, web 3100, admin 3102; never touch `yupay*` containers or testcontainers you did not start; kill processes by PID only.
- **Commits:** Conventional Commits, scopes `api/wallet`, `api/payments`, `api/click`, `api/payme`, `api/uzum`, `api/admin`, `scheduler`, `infra`, `web/balance`, `admin/users`, `admin/payments`, `e2e`, `docs`; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push.

## Rulings taken while planning (owner may veto)

- **R1 — Ledger tables are YuPay's three**, not the spec's two names: `wallet_accounts`, `wallet_transactions` (header with the unique idempotency key) and `wallet_postings` (the D/C legs = the spec's "ledger entries"). Spec §5 says "as YuPay wallet"; a flat `ledger_entries` table cannot hold the D = C invariant per event. UZS only, so no currency column; amounts `numeric(14,0)`.
- **R2 — Account kinds:** `user_wallet` (normal side D), `provider_clearing` (C, owner = provider slug), `house_payments_received` (D, used by M4 balance-paid orders), `house_adjustments` (D, contra-account of admin adjustments — YuPay misused `house_promo_expense`). Transaction kinds are the spec's names: `topup`, `topup_reversal`, `admin_adjust`; M4 adds `purchase`, `refund`.
- **R3 — A top-up has 1..N payment attempts.** `wallet_topups` (spec columns + `idempotency_key`, `expires_at`) is the thing the customer pays; `payments` rows (`purpose='topup'`, `topup_id`) are attempts, one live per provider (YuPay's `_ensure_payment` reuse), so a declined card retried in the same kassa works (YuPay's 2026-09-29 incident fix `unclaimed_external_id` comes along). `wallet_topups.payment_id` = the attempt that succeeded.
- **R4 — Payment FSM is enforced in one place** (`payments.fsm`): `created` (intent issued, the kassa has not called) → `pending` (the kassa holds a transaction) → `succeeded` | `failed` | `cancelled`; `succeeded` → `refunded`; terminal otherwise. `created` → `succeeded` is allowed (a kassa may settle without an earlier call we saw). YuPay had no central guard.
- **R5 — One payable resolver** (`payments.payable.resolve(db, account)`) turns the acquirer's account value into a payable: `T…` → top-up; anything else → order (M4; "not found" in M3). Every acquirer uses it; nobody else loads top-ups by number.
- **R6 — Hooks re-pointed by purpose:** `settle` (credit the top-up, mark it succeeded), `reverse` (claw back if the money is unspent, else refuse), `cancel_pending` (only if still pending). `purpose='order'` raises "not implemented" until M4. A second successful attempt on an already-credited top-up is **refused** (Click −4, Payme −31051 at check / −31008 at perform, Uzum 10008), so a customer is never charged twice for one credit.
- **R7 — A spent top-up cannot be reversed by the kassa:** Payme `CancelTransaction` on a performed top-up whose amount is no longer on the balance → −31007; Uzum `/reverse` → 10017; logged `payments.topup.reverse_refused` (number + amount, no user). Unspent → reversed (`topup_reversal`), top-up `reversed`.
- **R8 — Expiry:** a top-up whose attempts are all still `created` (no kassa transaction) expires after `topup_expiry_minutes` (30) by a 5-minute sweep; a kassa then asking to pay it gets "not payable". Attempts the kassa already holds are left to that kassa's own timeout sweep (Click 30 min, Payme 12 h, Uzum 30 min — YuPay's).
- **R9 — Account field names on the wire:** Click `merchant_trans_id`; Payme `account.order` (spec §6); Uzum `params.order`, also accepting `orderId` and `order_id` (YuPay learned on 2026-09-04 that Uzum sends camelCase). The kassa cabinets must be configured to match — runbook.
- **R10 — Return URL is ours, not the client's:** every intent returns the buyer to `{web_base_url}[/uz|/en]/account/balance/topups/{number}`; no `return_url` parameter, so no open-redirect check is needed.
- **R11 — Dev "mock" provider** (not in prod) creates attempts the storefront can complete through a dev-only `POST /api/v1/dev/topups/{number}/pay` (404 unless `dev_login_active`), driving the real `settle` hook — local work and e2e without kassas.
- **R12 — Not in M3:** paying from the balance (the `wallet` gateway — M4 with orders), admin "settle a stuck payment" (needs a provider reference; add when a real case appears), payment-provider kill-switch (credentials decide availability), card refunds from admin (no acquirer offers them; reversals come from the kassa side).
- **R13 — Admin clawback cannot go below zero** (409): YuPay allowed a negative balance through `admin_adjust`; csmarket refuses it.
- **R14 — "Done when" (spec §15: "a balance is topped up through a real kassa") needs a deployed public URL and the owner's kassa credentials** — the owner said work stays local. M3 is complete locally with sandbox-shaped tests and the mock provider; the real-kassa check moves to the first deploy (runbook lists it).

## Review Focus

1. **One top-up, one credit.** A replayed Click complete, a Payme `PerformTransaction` replay, an Uzum `/confirm` retry, the mock simulate pressed twice, or a second kassa transaction on a top-up already paid → the balance grows once; the second charge is refused at the kassa. → Task 3 `test_settle_twice_credits_once`, `test_a_second_attempt_on_a_paid_topup_is_refused`; Task 5 `test_a_second_prepare_on_a_paid_topup_is_minus4`.
2. **A reversal after the money was spent is refused, never a negative balance.** → Task 3 `test_reverse_refused_when_spent`; Task 6 `test_cancel_performed_spent_topup_is_31007`; Task 7 `test_reverse_spent_topup_is_10017`.
3. **An expired top-up cannot be paid; a top-up the kassa holds is not expired under it.** → Task 4 `test_expired_topup_is_not_payable`, `test_sweep_keeps_a_topup_with_a_kassa_transaction`.
4. **Wrong amount or units is refused** (Payme/Uzum tiyin = soʻm × 100; Click soʻm string). → Tasks 5–7 amount-mismatch tests.
5. **Admin money actions are safe:** clawback below zero is 409; a replayed adjust or ban writes one ledger/audit row. → Task 9 `test_clawback_below_zero_is_409`, `test_replayed_adjust_posts_once`.

---

## File structure (what M3 creates or changes)

```
apps/api/src/csmarket/
├── core/numbers.py                                   (T1) order/top-up numbers, Crockford
├── core/config.py                                    (T1) topup_*, click_*, payme_*, uzum_*
├── core/logging.py                                   (T1) redact the new secrets
├── modules/wallet/{__init__,api,models,service,schemas,routes}.py + README.md   (T2, T4)
├── modules/payments/{__init__,api,models,fsm,payable,hooks,external_ids,gateways/{base,mock,__init__}.py,
│                     topups.py,schemas.py,routes.py,admin_routes.py,dev_routes.py} + README.md (T3, T4, T10)
├── modules/click/{__init__,api,errors,signature,models,service,routes}.py + README.md, payments/gateways/click.py (T5)
├── modules/payme/{…same…} + payments/gateways/payme.py                         (T6)
├── modules/uzum/{…same…} + payments/gateways/uzum.py                           (T7)
├── modules/users/admin_routes.py, modules/admin/audit_routes.py                 (T9, T10)
├── api/v1/router.py, bootstrap.py                                               (mounts, exemptions)
apps/api/migrations/versions/0006_wallet_ledger.py 0007_payments_topups.py 0008_click_transactions.py
                             0009_payme_transactions.py 0010_uzum_transactions.py
apps/scheduler/src/csmarket_scheduler/jobs/{topup_expiry,click_timeout,payme_timeout,uzum_timeout}.py (T4–T8)
infra/caddy/Caddyfile.prod                                                       (T8) Payme allowlist
apps/web/src/lib/{balance,amount-input}.ts, app/[locale]/account/balance/{page.tsx,topups/[number]/page.tsx},
  components/balance/*                                                           (T11, T12)
packages/i18n/locales/{ru,uz,en}/web.json                                        (+ web.balance)
apps/admin/src/features/{users,payments,audit}/*                                 (T13, T14)
e2e/tests/{balance,admin-money}.spec.ts                                          (T15)
docs/: decisions/0006-wallet-payments-topups.md, runbooks/{kassa-setup,click,payme,uzum,wallet}.md,
       product/flows/balance-topup.md, architecture/sequence-diagrams/topup.mmd, … (T16)
```

---

### Task 1: Numbers, settings, secret redaction

**Files:**

- Create: `apps/api/src/csmarket/core/numbers.py`
- Modify: `apps/api/src/csmarket/core/config.py`, `apps/api/src/csmarket/core/logging.py` (redaction keys), `.env.example`, `apps/api/.env.example`, `infra/secrets-example/api.env`, `docker-compose.yml` (`x-app-env` passes the new vars)
- Test: `apps/api/tests/unit/test_numbers.py`, `apps/api/tests/unit/test_config.py` (extend), `apps/api/tests/unit/test_logging.py` (extend or create a redaction test)

**Interfaces:**

- Produces:
  - `core.numbers`: `ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"`, `TOPUP_PREFIX = "T"`, `order_number() -> str` (8 chars, first char never `T`), `topup_number() -> str` (`"T"` + 7), `is_topup_number(value: str) -> bool`, `is_number(value: str) -> bool` (8 chars from the alphabet), `async allocate(db, column, make: Callable[[], str], *, attempts: int = 3) -> str` (returns a value not present in `column`; raises `RuntimeError` after `attempts` collisions).
  - `Settings`: `topup_min_uzs: int = 1000`, `topup_max_uzs: int = 10_000_000`, `topup_expiry_minutes: int = 30`; Click `click_merchant_id: int | None = None`, `click_service_id: int | None = None`, `click_secret_key: str = ""`, `click_pay_url: str = "https://my.click.uz/services/pay"`; Payme `payme_merchant_id: str = ""`, `payme_key: str = ""`, `payme_test_key: str = ""`, `payme_login: str = "Paycom"`, `payme_checkout_url: str = "https://checkout.paycom.uz"`; Uzum `uzum_service_id: int | None = None`, `uzum_login: str = ""`, `uzum_password: str = ""`, `uzum_test_login: str = ""`, `uzum_test_password: str = ""`, `uzum_open_service_url: str = "https://uzumbank.uz/open-service"`. Blank strings for the `int | None` fields become `None` (YuPay's `field_validator(mode="before")`).

- [ ] **Step 1: Numbers (tests first)**

```python
# apps/api/tests/unit/test_numbers.py
import re

from csmarket.core.numbers import ALPHABET, is_number, is_topup_number, order_number, topup_number

CROCKFORD = re.compile(r"^[0-9ABCDEFGHJKMNPQRSTVWXYZ]{8}$")


def test_order_numbers_are_8_crockford_chars_never_starting_with_t() -> None:
    seen = {order_number() for _ in range(5000)}
    assert all(CROCKFORD.match(n) for n in seen)
    assert not any(n.startswith("T") for n in seen)
    assert len(seen) > 4990  # random, not sequential


def test_topup_numbers_are_t_plus_7() -> None:
    for _ in range(500):
        n = topup_number()
        assert CROCKFORD.match(n) and n.startswith("T") and is_topup_number(n)


def test_classifiers() -> None:
    assert is_number("7K3M9QX2")
    assert not is_topup_number("7K3M9QX2")
    assert is_topup_number("T7K3M9QX")
    for bad in ("", "T", "7k3m9qx2", "7K3M9QXI", "7K3M9QX", "7K3M9QX22", "T7K3M9QU"):
        assert not is_number(bad), bad
        assert not is_topup_number(bad), bad
    for letter in "ILOU":
        assert letter not in ALPHABET
```

```python
# apps/api/src/csmarket/core/numbers.py
"""Short public numbers (spec §6): 8 Crockford base32 chars, random, never sequential.

Orders (M4) and top-ups share the namespace the kassas see in the account field: a top-up is
``T`` + 7 chars, so an order number must never start with ``T`` — the payable resolver
(``payments.payable``) tells them apart by that one letter.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TOPUP_PREFIX = "T"
_FIRST = ALPHABET.replace(TOPUP_PREFIX, "")
_LEN = 8


def _chars(n: int, alphabet: str = ALPHABET) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def order_number() -> str:
    """An order number: 8 chars, the first never ``T``."""
    return secrets.choice(_FIRST) + _chars(_LEN - 1)


def topup_number() -> str:
    """A top-up number: ``T`` + 7 chars."""
    return TOPUP_PREFIX + _chars(_LEN - 1)


def is_number(value: str) -> bool:
    """8 chars, all from the alphabet (upper case)."""
    return len(value) == _LEN and all(c in ALPHABET for c in value)


def is_topup_number(value: str) -> bool:
    """A well-formed top-up number."""
    return is_number(value) and value.startswith(TOPUP_PREFIX)


async def allocate(
    db: AsyncSession,
    column: Any,  # Any: an InstrumentedAttribute of any model's unique number column
    make: Callable[[], str],
    *,
    attempts: int = 3,
) -> str:
    """A fresh number not yet in ``column`` (32⁷ ≈ 3.4 × 10¹⁰ — collisions are rare).

    The unique index is still the real guard; this only keeps a collision from becoming
    a failed request.
    """
    for _ in range(attempts):
        candidate = make()
        taken = await db.scalar(select(exists().where(column == candidate)))
        if not taken:
            return candidate
    raise RuntimeError("could not allocate a unique number")
```

Run: `cd apps/api && uv run pytest tests/unit/test_numbers.py -q` → FAIL first, then PASS.

- [ ] **Step 2: Settings + redaction (tests first)**

Append to `tests/unit/test_config.py` (reuse the file's env-clearing idiom):

```python
def test_money_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (s.topup_min_uzs, s.topup_max_uzs, s.topup_expiry_minutes) == (1000, 10_000_000, 30)
    assert s.click_service_id is None and s.click_secret_key == ""
    assert s.payme_login == "Paycom" and s.payme_checkout_url == "https://checkout.paycom.uz"
    assert s.uzum_service_id is None
    assert s.uzum_open_service_url == "https://uzumbank.uz/open-service"


def test_blank_int_ids_are_none(monkeypatch) -> None:
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", "")
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", "")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.click_service_id is None and s.uzum_service_id is None
```

Redaction test: log an event with `click_secret_key="s"`, `payme_key="k"`, `uzum_password="p"`, `authorization="Basic x"` through the real `configure_logging()` and assert none of `s`/`k`/`p`/`Basic x` appears (use the live log-capture idiom of `tests/contract/test_waxpeer_catalogue.py`). Add the key stems (`secret`, `password`, `authorization`, `payme_key`, `payme_test_key`) to `core/logging.py`'s redactor if not already covered (check first — M0 may already redact `secret`/`password`/`authorization`).

Add the fields (with `description`s) under `# --- money (M3) ---`; the `int | None` blank→None validator for `click_merchant_id`, `click_service_id`, `uzum_service_id` (port `ym:../../core/config.py:966-985` shape). Env templates: all keys present and empty in `.env.example` / `apps/api/.env.example` (comment: "kassa credentials — prod only; tests and dev use the mock provider"); `infra/secrets-example/api.env` gets `CHANGE_ME` placeholders with one-line comments (where each value comes from: Click cabinet service, Payme cabinet "Ключ" and "Тестовый ключ", Uzum login/password pair handed to their engineer); `docker-compose.yml` passes them through with `${VAR:-}`.

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_numbers.py tests/unit/test_config.py tests/unit/test_logging.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/payments): public numbers, kassa settings, secret redaction

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Wallet ledger — accounts, transactions, postings (migration 0006)

**Files:**

- Create: `apps/api/src/csmarket/modules/wallet/{__init__,api,models,service}.py`, `modules/wallet/README.md`, `apps/api/migrations/versions/0006_wallet_ledger.py`
- Modify: `apps/api/migrations/env.py`, `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER`), `apps/api/tests/unit/test_import_order.py`
- Test: `apps/api/tests/integration/test_wallet_ledger.py`, `apps/api/tests/integration/test_wallet_ledger_props.py` (hypothesis)

**Interfaces:**

- Produces (`wallet.api`):
  - Models `WalletAccount(id, owner_type: "user"|"house"|"provider", owner_id: str, kind, status: "active"|"frozen", created_at, updated_at)` unique `(owner_type, owner_id, kind)`; `WalletTransaction(id, kind, reference_type, reference_id, idempotency_key UNIQUE, actor, metadata jsonb, created_at)`; `WalletPosting(id, transaction_id FK CASCADE, account_id FK RESTRICT, direction "D"|"C", amount numeric(14,0) > 0, created_at)`.
  - `NORMAL_SIDE: dict[str, Literal["D","C"]] = {"user_wallet": "D", "provider_clearing": "C", "house_payments_received": "D", "house_adjustments": "D"}`; `TX_KINDS = ("topup", "topup_reversal", "admin_adjust")` (M4 adds `"purchase"`, `"refund"`).
  - `Leg(account_id: str, direction: Literal["D","C"], amount: Decimal)`, `Reference(type: str, id: str)` (frozen dataclasses).
  - `async ensure_account(db, *, owner_type, owner_id, kind) -> WalletAccount` (SAVEPOINT race-safe).
  - `async user_account(db, user_id, *, lock: bool = False) -> WalletAccount` (ensures, then optionally `SELECT … FOR UPDATE`).
  - `async post(db, *, kind, legs, idempotency_key, reference=None, actor="system", metadata=None) -> WalletTransaction` (replay by key returns the existing txn; validates ≥ 2 legs, amounts > 0 whole soʻm, `SUM(D)==SUM(C)`, accounts exist and are `active`; SAVEPOINT for the insert race).
  - `async balance(db, account_id) -> Decimal`, `async user_balance(db, user_id) -> Decimal` (0 when no account).
  - `class InsufficientBalanceError(ConflictError)`.

- [ ] **Step 1: Port the ledger core, UZS-only (tests first)**

Read `ym:wallet/service.py:24-268` and `ym:wallet/models.py`. Port `Leg`, `Reference`, `_validate_legs`, `ensure_account`, `post`, `balance` with deltas: no `currency` anywhere (UZS only, R1) — drop the column, the per-currency sums (one sum), and currency checks; amounts must be whole (`amount == amount.to_integral_value()`) else `ValidationError("ledger amounts are whole soʻm")`; `NORMAL_SIDE` and owner types reduced to R2's; logger `csmarket.wallet.service`; docstrings cite spec §5 / R1, never YuPay ADR numbers.

```python
# apps/api/tests/integration/test_wallet_ledger.py
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ValidationError
from csmarket.modules.users.api import upsert_user_by_steam
from csmarket.modules.wallet.api import Leg, balance, ensure_account, post, user_account, user_balance


async def _user(db: AsyncSession, sid: str = "76561198000000101") -> str:
    return (await upsert_user_by_steam(db, steam_id=sid, display_name=None, avatar_url=None)).id


async def test_post_moves_money_and_balances_follow_normal_side(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    wallet = await user_account(db_session, uid)
    clearing = await ensure_account(db_session, owner_type="provider", owner_id="payme", kind="provider_clearing")
    await post(db_session, kind="topup", legs=[Leg(wallet.id, "D", Decimal(50000)), Leg(clearing.id, "C", Decimal(50000))], idempotency_key="t1")
    await db_session.commit()
    assert await balance(db_session, wallet.id) == Decimal(50000)
    assert await balance(db_session, clearing.id) == Decimal(50000)
    assert await user_balance(db_session, uid) == Decimal(50000)


async def test_replay_by_key_posts_once(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(db_session, owner_type="provider", owner_id="click", kind="provider_clearing")
    legs = [Leg(w.id, "D", Decimal(1000)), Leg(c.id, "C", Decimal(1000))]
    a = await post(db_session, kind="topup", legs=legs, idempotency_key="same")
    b = await post(db_session, kind="topup", legs=legs, idempotency_key="same")
    await db_session.commit()
    assert a.id == b.id and await user_balance(db_session, uid) == Decimal(1000)


@pytest.mark.parametrize(
    "legs",
    [
        lambda w, c: [Leg(w, "D", Decimal(100))],
        lambda w, c: [Leg(w, "D", Decimal(100)), Leg(c, "C", Decimal(99))],
        lambda w, c: [Leg(w, "D", Decimal("100.5")), Leg(c, "C", Decimal("100.5"))],
        lambda w, c: [Leg(w, "D", Decimal(0)), Leg(c, "C", Decimal(0))],
    ],
)
async def test_bad_legs_are_refused(db_session: AsyncSession, legs) -> None:  # type: ignore[no-untyped-def]
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(db_session, owner_type="house", owner_id="house", kind="house_adjustments")
    with pytest.raises(ValidationError):
        await post(db_session, kind="admin_adjust", legs=legs(w.id, c.id), idempotency_key="bad")


async def test_no_account_means_zero(db_session: AsyncSession) -> None:
    assert await user_balance(db_session, await _user(db_session)) == Decimal(0)
```

```python
# apps/api/tests/integration/test_wallet_ledger_props.py — spec §14: hypothesis on the ledger
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account
from csmarket.modules.wallet.models import WalletPosting

amounts = st.lists(st.integers(min_value=1, max_value=10_000_000), min_size=1, max_size=20)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(amounts=amounts)
async def test_debits_always_equal_credits(db_session: AsyncSession, amounts: list[int]) -> None:
    from csmarket.modules.users.api import upsert_user_by_steam

    uid = (await upsert_user_by_steam(db_session, steam_id="76561198000000199", display_name=None, avatar_url=None)).id
    w = await user_account(db_session, uid)
    c = await ensure_account(db_session, owner_type="provider", owner_id="uzum", kind="provider_clearing")
    for i, a in enumerate(amounts):
        await post(db_session, kind="topup", legs=[Leg(w.id, "D", Decimal(a)), Leg(c.id, "C", Decimal(a))], idempotency_key=f"p{len(amounts)}:{i}:{a}")
    await db_session.flush()
    d = await db_session.scalar(select(func.coalesce(func.sum(WalletPosting.amount), 0)).where(WalletPosting.direction == "D"))
    c_sum = await db_session.scalar(select(func.coalesce(func.sum(WalletPosting.amount), 0)).where(WalletPosting.direction == "C"))
    assert d == c_sum
    await db_session.rollback()
```

(If hypothesis + the async fixture combination is awkward in this suite, run the property inside one test with `hypothesis.find`-free loops over `st.lists(...).example()`-style data is NOT acceptable; instead use `@given` on a sync wrapper that calls `asyncio.run` on a fresh engine — keep the property, adapt the harness. Confirm `hypothesis` is in apps/api dev deps; it was added in M2.)

- [ ] **Step 2: Models + migration 0006**

`0006_wallet_ledger.py` (`down_revision = "0005_admin_audit_log"`): the three tables per **Interfaces**; CHECKs `owner_type IN ('user','house','provider')`, `kind IN ('user_wallet','provider_clearing','house_payments_received','house_adjustments')`, `status IN ('active','frozen')`, `direction IN ('D','C')`, `amount > 0`; indexes `ix_wallet_postings_account_created (account_id, created_at DESC)`, `ix_wallet_postings_transaction`, `ix_wallet_transactions_reference (reference_type, reference_id)`, partial `ix_wallet_accounts_user_wallet (owner_id) WHERE kind='user_wallet' AND owner_type='user'`. Remember the naming convention: a CHECK named `kind` becomes `ck_wallet_accounts_kind` (do not prefix it yourself). `migrations/env.py` imports the models; `_EMPTY_IN_ORDER` gets `"wallet_postings", "wallet_transactions", "wallet_accounts"` before `"users"`; `test_import_order.py` lists the wallet modules.

`wallet/README.md`: owns the three tables; `post()` is the only writer; kinds and normal sides; idempotency key shapes (`topup:{topup_id}`, `topup_reversal:{topup_id}`, `admin_adjust:{idempotency_key}`; M4 `purchase:{order_id}`, `refund:{order_id}`); balance = SUM by normal side; no overdraft by our code (callers lock `user_account(lock=True)` before reading the balance).

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_wallet_ledger.py tests/integration/test_wallet_ledger_props.py tests/integration/test_migrations.py tests/unit/test_import_order.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/wallet): double-entry ledger — accounts, transactions, postings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Payments core — payments, top-ups, FSM, payable resolver, hooks, mock gateway (migration 0007)

**Files:**

- Create: `apps/api/src/csmarket/modules/payments/{__init__,api,models,fsm,payable,hooks,external_ids}.py`, `modules/payments/gateways/{__init__,base,mock}.py`, `modules/payments/README.md`, `apps/api/migrations/versions/0007_payments_topups.py`
- Modify: `apps/api/src/csmarket/modules/wallet/service.py` (+ `credit_topup`, `reverse_topup`), `wallet/api.py`, `migrations/env.py`, integration `conftest.py` (`_EMPTY_IN_ORDER`: `"payments"` and `"wallet_topups"` — they reference each other; put both before `"users"` and rely on the TRUNCATE fallback or delete `payments` first after nulling `wallet_topups.payment_id`; simplest: list `"payments", "wallet_topups"` and make `wallet_topups.payment_id` `ON DELETE SET NULL`), `tests/unit/test_import_order.py`
- Test: `apps/api/tests/unit/test_payment_fsm.py`, `apps/api/tests/integration/test_payment_hooks.py`, `apps/api/tests/integration/test_payable_resolver.py`

**Interfaces:**

- Consumes: `wallet.api` (Task 2), `core.numbers` (Task 1).
- Produces:
  - `payments.models.Payment` — `payments (id uuid pk, number varchar(8) NOT NULL, purpose varchar(8) CHECK IN ('topup','order'), order_id uuid NULL (FK added in M4), topup_id uuid NULL FK wallet_topups ON DELETE RESTRICT, user_id uuid NOT NULL FK users, provider varchar(16) NOT NULL, provider_ref varchar(160) NULL, amount_uzs numeric(14,0) NOT NULL CHECK > 0, status varchar(12) CHECK IN ('created','pending','succeeded','failed','cancelled','refunded'), idempotency_key varchar(160) NULL, metadata jsonb NOT NULL DEFAULT '{}', created_at, updated_at, succeeded_at NULL)`; CHECK `(purpose='topup') = (topup_id IS NOT NULL)`; partial UNIQUE `uq_payments_provider_ref (provider, provider_ref) WHERE provider_ref IS NOT NULL`; partial UNIQUE `uq_payments_idempotency_key WHERE idempotency_key IS NOT NULL`; indexes `ix_payments_number`, `ix_payments_topup`, `ix_payments_status_created (status, created_at DESC)`, `ix_payments_created (created_at DESC, id DESC)`.
  - `payments.models.WalletTopup` — `wallet_topups (id, number varchar(8) UNIQUE, user_id FK users, amount_uzs numeric(14,0) CHECK > 0, payment_id uuid NULL FK payments ON DELETE SET NULL (use_alter), status varchar(12) CHECK IN ('pending','succeeded','expired','reversed'), idempotency_key varchar(160) NOT NULL, expires_at timestamptz NOT NULL, created_at, succeeded_at NULL)`; UNIQUE `(user_id, idempotency_key)`; index `ix_wallet_topups_user_created (user_id, created_at DESC)`, `ix_wallet_topups_pending_expires (expires_at) WHERE status='pending'`. (Lives in `payments` — it is a payable; the ledger stays in `wallet`.)
  - `payments.fsm`: `TRANSITIONS: dict[str, frozenset[str]]` per R4, `InvalidTransitionError(ConflictError)`, `move(payment, to: str) -> None` (sets `status`, `updated_at`, and `succeeded_at` on success; raises on an illegal edge).
  - `payments.payable`: `Payable(kind: Literal["topup","order"], number: str, amount_uzs: Decimal, user_id: str, payable: bool, reason: Literal["ok","paid","expired","reversed","not_found"], topup: WalletTopup | None)`; `async resolve(db, account: str, *, lock: bool = False) -> Payable` (top-up by number, `FOR UPDATE` when `lock`; `not_found` for anything else in M3).
  - `payments.external_ids`: `async unclaimed_external_id(db, *, provider, external_id, payment_id) -> str` (port of `ym:payments/external_ids.py`).
  - `payments.hooks`: `async ensure_attempt(db, *, payable: Payable, provider: str) -> Payment` (reuse the top-up's live `created|pending` attempt of that provider, else insert a new `created` one with `provider_ref = unclaimed_external_id(f"{provider}:{number}")`); `async mark_pending(db, *, payment) -> None` (created → pending, no-op if already pending); `async settle(db, *, payment, event_id: str) -> None`; `async reverse(db, *, payment, event_id: str) -> None` (raises `TopupSpentError`); `async cancel_pending(db, *, payment) -> None`; `TopupSpentError(ConflictError)`, `AlreadyPaidError(ConflictError)`.
  - `wallet.service`: `async credit_topup(db, *, user_id, topup_id, amount, provider) -> WalletTransaction` (`D user_wallet / C provider_clearing:<provider>`, kind `topup`, key `topup:{topup_id}`); `async reverse_topup(db, *, user_id, topup_id, amount, provider) -> WalletTransaction` (locks the user account, `InsufficientBalanceError` if balance < amount, kind `topup_reversal`, key `topup_reversal:{topup_id}`).
  - `payments.gateways.base`: `PaymentGateway` Protocol (`provider: str`, `available: bool`, `intent_url(*, payable: Payable, locale: str) -> str`); `available_providers() -> list[str]`; `get_gateway(provider) -> PaymentGateway` (404 if unknown or unavailable). `gateways.mock.MockGateway` (`available = not settings.is_prod`; `intent_url` = the top-up status page with `?mock=1`).

- [ ] **Step 1: FSM (unit tests first)**

```python
# apps/api/tests/unit/test_payment_fsm.py
import pytest

from csmarket.modules.payments.fsm import TRANSITIONS, InvalidTransitionError, move


class P:
    def __init__(self, status: str) -> None:
        self.status = status
        self.succeeded_at = None
        self.updated_at = None


@pytest.mark.parametrize(
    ("start", "to"),
    [("created", "pending"), ("created", "succeeded"), ("created", "cancelled"), ("created", "failed"),
     ("pending", "succeeded"), ("pending", "cancelled"), ("pending", "failed"), ("succeeded", "refunded")],
)
def test_legal_edges(start: str, to: str) -> None:
    p = P(start)
    move(p, to)  # type: ignore[arg-type]
    assert p.status == to
    assert (p.succeeded_at is not None) == (to == "succeeded")


@pytest.mark.parametrize(
    ("start", "to"),
    [("succeeded", "pending"), ("succeeded", "cancelled"), ("cancelled", "succeeded"), ("failed", "succeeded"),
     ("refunded", "succeeded"), ("pending", "created"), ("pending", "refunded")],
)
def test_illegal_edges_raise(start: str, to: str) -> None:
    with pytest.raises(InvalidTransitionError):
        move(P(start), to)  # type: ignore[arg-type]


def test_terminal_states_have_no_exits() -> None:
    assert TRANSITIONS["cancelled"] == TRANSITIONS["failed"] == TRANSITIONS["refunded"] == frozenset()
```

```python
# apps/api/src/csmarket/modules/payments/fsm.py
"""The payment state machine (ruling R4) — the only place a status changes.

created   intent issued; the kassa has not called yet
pending   the kassa holds a transaction (Click prepare, Payme create, Uzum create)
succeeded money arrived; refunded only through ``hooks.reverse``
"""

from __future__ import annotations

from typing import Literal, Protocol

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError

Status = Literal["created", "pending", "succeeded", "failed", "cancelled", "refunded"]

TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"pending", "succeeded", "failed", "cancelled"}),
    "pending": frozenset({"succeeded", "failed", "cancelled"}),
    "succeeded": frozenset({"refunded"}),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "refunded": frozenset(),
}


class InvalidTransitionError(ConflictError):
    """An edge the FSM does not allow."""


class _HasStatus(Protocol):
    status: str


def move(payment: _HasStatus, to: Status) -> None:
    """Change ``payment.status`` along a legal edge, stamping the times.

    Raises:
        InvalidTransitionError: ``to`` is not reachable from the current status.
    """
    if to not in TRANSITIONS.get(payment.status, frozenset()):
        raise InvalidTransitionError(f"payment cannot go {payment.status} -> {to}")
    payment.status = to
    stamp = now()
    payment.updated_at = stamp  # type: ignore[attr-defined]
    if to == "succeeded":
        payment.succeeded_at = stamp  # type: ignore[attr-defined]
```

(Fix the attr typing by adding `updated_at`/`succeeded_at` to the Protocol instead of the ignores.)

- [ ] **Step 2: Models + migration 0007 + resolver (tests first)**

```python
# apps/api/tests/integration/test_payable_resolver.py
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core import clock
from csmarket.modules.payments.payable import resolve
from tests.integration.payments_factory import make_topup  # Step 4 helper


async def test_pending_topup_is_payable(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, amount=Decimal(50000))
    p = await resolve(db_session, t.number)
    assert (p.kind, p.payable, p.reason, p.amount_uzs) == ("topup", True, "ok", Decimal(50000))


async def test_paid_expired_reversed_are_not_payable(db_session: AsyncSession) -> None:
    for status, reason in (("succeeded", "paid"), ("expired", "expired"), ("reversed", "reversed")):
        t = await make_topup(db_session, status=status)
        p = await resolve(db_session, t.number)
        assert (p.payable, p.reason) == (False, reason)


async def test_pending_past_expiry_is_not_payable(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, expires_at=clock.now() - timedelta(seconds=1))
    assert (await resolve(db_session, t.number)).reason == "expired"


async def test_unknown_and_order_numbers_are_not_found(db_session: AsyncSession) -> None:
    for account in ("TZZZZZZZ", "7K3M9QX2", "", "drop table", "t1234567"):
        p = await resolve(db_session, account)
        assert (p.payable, p.reason) == (False, "not_found")
```

`tests/integration/payments_factory.py` (shared by Tasks 3–9): `make_user(db, sid=…) -> User`, `make_topup(db, *, user=None, amount=Decimal(50000), status="pending", expires_at=None) -> WalletTopup` (allocates a `topup_number()`, idempotency key `f"test-{uuid4()}"`, expires in 30 min by default, commits). Keep it importable as `tests.integration.payments_factory` (check the suite's import style; M2 tests import helpers this way or via conftest fixtures — follow what exists).

Migration `0007_payments_topups.py` (`down_revision = "0006_wallet_ledger"`): `wallet_topups` first without the `payment_id` FK, then `payments`, then `ALTER TABLE wallet_topups ADD CONSTRAINT … FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE SET NULL` (`op.create_foreign_key` after both exist); downgrade in reverse.

- [ ] **Step 3: Wallet credit/reverse + hooks (tests first — Review Focus 1, 2)**

```python
# apps/api/tests/integration/test_payment_hooks.py
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.payments.hooks import TopupSpentError, cancel_pending, ensure_attempt, mark_pending, reverse, settle
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account, user_balance
from csmarket.modules.wallet.models import WalletTransaction
from tests.integration.payments_factory import make_topup


async def _attempt(db: AsyncSession, provider: str = "payme", amount: Decimal = Decimal(50000)):  # type: ignore[no-untyped-def]
    t = await make_topup(db, amount=amount)
    p = await ensure_attempt(db, payable=await resolve(db, t.number, lock=True), provider=provider)
    await db.commit()
    return t, p


async def test_settle_credits_and_marks_topup(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await db_session.refresh(t)
    assert (p.status, t.status, t.payment_id) == ("succeeded", "succeeded", p.id)
    assert await user_balance(db_session, t.user_id) == Decimal(50000)


async def test_settle_twice_credits_once(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await settle(db_session, payment=p, event_id="e1-replay")
    await db_session.commit()
    assert await user_balance(db_session, t.user_id) == Decimal(50000)
    assert await db_session.scalar(select(func.count()).select_from(WalletTransaction)) == 1


async def test_a_second_attempt_on_a_paid_topup_is_refused(db_session: AsyncSession) -> None:
    from csmarket.modules.payments.hooks import AlreadyPaidError

    t, p1 = await _attempt(db_session, provider="payme")
    await settle(db_session, payment=p1, event_id="e1")
    await db_session.commit()
    # Another kassa attempt created before the first landed (e.g. a second tab) tries to settle.
    from csmarket.modules.payments.models import Payment

    p2 = Payment(number=t.number, purpose="topup", topup_id=t.id, user_id=t.user_id, provider="click",
                 provider_ref="click:" + t.number, amount_uzs=t.amount_uzs, status="pending")
    db_session.add(p2)
    await db_session.commit()
    with pytest.raises(AlreadyPaidError):
        await settle(db_session, payment=p2, event_id="e2")
    assert await user_balance(db_session, t.user_id) == Decimal(50000)


async def test_reverse_unspent_claws_back(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await db_session.refresh(t)
    assert (p.status, t.status) == ("refunded", "reversed")
    assert await user_balance(db_session, t.user_id) == Decimal(0)


async def test_reverse_refused_when_spent(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    # Spend 10 000 (stand-in for an M4 purchase).
    w = await user_account(db_session, t.user_id)
    house = await ensure_account(db_session, owner_type="house", owner_id="house", kind="house_payments_received")
    await post(db_session, kind="admin_adjust", legs=[Leg(w.id, "C", Decimal(10000)), Leg(house.id, "D", Decimal(10000))], idempotency_key="spend")
    await db_session.commit()
    with pytest.raises(TopupSpentError):
        await reverse(db_session, payment=p, event_id="r1")
    await db_session.rollback()
    assert await user_balance(db_session, t.user_id) == Decimal(40000)


async def test_cancel_pending_only_touches_pending(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await cancel_pending(db_session, payment=p)
    await db_session.commit()
    assert p.status == "succeeded"
    t2, p2 = await _attempt(db_session)
    await mark_pending(db_session, payment=p2)
    await cancel_pending(db_session, payment=p2)
    await db_session.commit()
    assert p2.status == "cancelled"


async def test_ensure_attempt_reuses_a_live_attempt_of_the_same_provider(db_session: AsyncSession) -> None:
    t = await make_topup(db_session)
    a = await ensure_attempt(db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme")
    b = await ensure_attempt(db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme")
    assert a.id == b.id
    await cancel_pending(db_session, payment=await _pending(db_session, a))
    c = await ensure_attempt(db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme")
    assert c.id != a.id and c.provider_ref != a.provider_ref  # unclaimed_external_id suffix


async def _pending(db: AsyncSession, p):  # type: ignore[no-untyped-def]
    await mark_pending(db, payment=p)
    return p
```

`hooks.py` — the contracts (port the locking and money-safety of `ym:payments/service.py:1329-1460` — `settle_provider_payment`, `reverse_provider_payment`, `cancel_pending_provider_payment` — onto top-ups):

```python
"""Provider hooks (ruling R6) — every kassa calls these, nothing else changes money state.

Each takes the session-attached payment, re-reads it ``FOR UPDATE`` (one top-up can have
sibling attempts; a timeout sweep and a late callback must not both see ``pending``), then
locks the top-up. The caller commits.
"""

async def settle(db: AsyncSession, *, payment: Payment, event_id: str) -> None:
    """Money arrived for ``payment``: credit the top-up once.

    No-op if this payment already succeeded. Raises ``AlreadyPaidError`` when the top-up was
    already credited through another attempt (the kassa then refuses the second charge).
    """
    await db.refresh(payment, with_for_update=True)
    if payment.status == "succeeded":
        return
    if payment.purpose != "topup":
        raise NotImplementedError("orders are paid from M4")
    topup = await db.get(WalletTopup, payment.topup_id, with_for_update=True)
    assert topup is not None
    if topup.status == "succeeded" and topup.payment_id != payment.id:
        raise AlreadyPaidError("top-up already paid")
    move(payment, "succeeded")
    topup.status, topup.payment_id, topup.succeeded_at = "succeeded", payment.id, payment.succeeded_at
    await credit_topup(db, user_id=topup.user_id, topup_id=topup.id, amount=topup.amount_uzs, provider=payment.provider)
    log.info("payments.topup.credited", number=topup.number, provider=payment.provider, amount=str(topup.amount_uzs))
```

`reverse`: lock payment; `refunded` → no-op; must be `succeeded` else `InvalidTransitionError`; lock top-up; `reverse_topup` (raises `InsufficientBalanceError` → re-raise as `TopupSpentError` after logging `payments.topup.reverse_refused` with number + amount); `move(payment, "refunded")`; top-up `reversed`. `cancel_pending`: lock; only `created|pending` → `cancelled`. `mark_pending`: lock; `created` → `pending`; `pending` no-op; anything else → `InvalidTransitionError`. Note an expired top-up whose attempts are cancelled by the sweep cannot reach `settle` through a kassa (the resolver refuses payability first); if a kassa still calls perform/confirm/complete on an attempt it holds (`pending`), `settle` credits even if the top-up's `expires_at` passed — the money arrived (YuPay's "paid after expiry" rule for deposits). Pin that: `test_a_late_settle_on_a_held_attempt_still_credits`.

`gateways/base.py`, `gateways/__init__.py` (`REGISTRY` built lazily from settings: mock + whatever Tasks 5–7 add), `gateways/mock.py` per **Interfaces**. Port the shape of `ym:payments/gateways/base.py` but slimmed to R10's `intent_url` (no `create_intent` DB writes inside gateways — `ensure_attempt` owns the row; no `verify_webhook`/`refund` — kassas have their own modules). `available_providers()` returns slugs in the order `click, payme, uzum, mock` filtered by `available`.

`payments/README.md`: tables, FSM, resolver, hooks and their contracts (the table from YuPay's inventory 3.2 rewritten for top-ups), gateways, the order/top-up number rule.

- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_payment_fsm.py tests/integration/test_payable_resolver.py tests/integration/test_payment_hooks.py tests/integration/test_migrations.py tests/unit/test_import_order.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/payments): payments and top-ups, FSM, payable resolver, provider hooks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Top-up API, balance API, expiry sweep, dev pay

**Files:**

- Create: `apps/api/src/csmarket/modules/payments/{topups,schemas,routes,dev_routes}.py`, `apps/api/src/csmarket/modules/wallet/{schemas,routes}.py`, `apps/scheduler/src/csmarket_scheduler/jobs/topup_expiry.py`
- Modify: `apps/api/src/csmarket/modules/wallet/service.py` (+ `entries_for_user`), `apps/api/src/csmarket/api/v1/router.py`, `apps/scheduler/src/csmarket_scheduler/main.py` (register + import wallet/payments models), `jobs/__init__.py`, `apps/scheduler/tests/test_main.py`, `tests/unit/test_import_order.py`, `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_topups.py`, `apps/api/tests/integration/test_wallet_routes.py`, `apps/api/tests/integration/test_topup_expiry.py`, `apps/scheduler/tests/test_topup_expiry.py`

**Interfaces:**

- Consumes: Tasks 1–3; `auth.api.current_user`; `core.idempotency` (pattern of `users/routes.py`).
- Produces:
  - `payments.topups`: `async create_topup(db, *, user_id, amount_uzs: Decimal, provider: str, idempotency_key: str, locale: str) -> tuple[WalletTopup, Payment, str]` (validates D1 limits → `ValidationError(code="topup_amount")`; provider must be available and not `wallet` → `ValidationError(code="topup_provider")`; replay by `(user_id, idempotency_key)` returns the same top-up when amount and provider match, else `ConflictError(code="idempotency_mismatch")` — also on the IntegrityError race; allocates `topup_number()`; `expires_at = now + topup_expiry_minutes`; `ensure_attempt`; returns the intent URL from the gateway); `async expire_stale(db, *, limit: int = 500) -> int` (R8).
  - HTTP (customer, signed in):
    - `GET /api/v1/payments/providers` (anonymous) → `{providers: [{slug}]}` (available, ordered).
    - `POST /api/v1/wallet/topups` + `Idempotency-Key` body `{amount_uzs: int, provider: str, locale: "ru"|"uz"|"en"}` → 201 `TopupOut {number, amount_uzs, provider, status, expires_at, intent_url}`.
    - `GET /api/v1/wallet/topups/{number}` → `TopupOut` (owner only; 404 otherwise, never 403 — no number enumeration).
    - `GET /api/v1/wallet` → `{balance_uzs: str}`; `GET /api/v1/wallet/entries?cursor=&limit=` → `{items: [EntryOut {id, kind, amount_uzs (signed string, + credit / − debit for the customer), created_at, reference_number}], next_cursor}` (only the customer's `user_wallet` leg; no actor, no metadata — YuPay's customer-redaction lesson).
    - Dev: `POST /api/v1/dev/topups/{number}/pay` (404 unless `settings.dev_login_active`; owner only; the top-up's live `mock` attempt → `mark_pending` + `settle`) → `TopupOut`.
  - Scheduler job `wallet.topup_expiry` (every 5 min, `first_run_after(140)`).

- [ ] **Step 1: Tests first (Review Focus 3 included)**

`tests/integration/test_topups.py` — through HTTP with the `customer_headers` fixture (M2) and `payments_factory`:

- `test_create_topup_returns_number_and_intent` — 201, number `T…`, status `pending`, intent_url points at `/account/balance/topups/<number>` for mock; `uz` locale → `/uz/account/balance/topups/…`.
- `test_limits` — 999 → 422 `topup_amount`; 10 000 001 → 422; 1 000 and 10 000 000 → 201; a non-integer (`"1000.5"` or `1000.5`) → 422.
- `test_unknown_or_unavailable_provider_is_422` — `"paynet"`, `"wallet"`, `"click"` without credentials → 422 `topup_provider`.
- `test_replay_same_body_returns_same_topup` / `test_replay_different_amount_is_409` / `test_replay_different_provider_is_409`.
- `test_missing_or_short_key_is_422`.
- `test_someone_elses_topup_is_404`.
- `test_dev_pay_credits_once` — dev pay twice → balance once, status `succeeded`; in prod settings dev pay → 404.
- `test_a_late_settle_on_a_held_attempt_still_credits` (moved here if not in Task 3).
- `test_providers_endpoint_lists_mock_in_dev_only`.

`tests/integration/test_wallet_routes.py` — balance 0 for a new user; entries after a dev-paid top-up show `+50000` kind `topup` with `reference_number`; keyset paging over 30 entries (limit 10 → 3 pages, stable, no duplicates); another user sees nothing; anonymous → 401.

`tests/integration/test_topup_expiry.py`:

```python
async def test_sweep_expires_only_untouched_topups(db_session: AsyncSession) -> None:
    stale = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    await ensure_attempt(db_session, payable=await resolve(db_session, stale.number, lock=True), provider="mock")
    held = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    a = await ensure_attempt(db_session, payable=await resolve(db_session, held.number, lock=True), provider="payme")
    await mark_pending(db_session, payment=a)
    fresh = await make_topup(db_session)
    await db_session.commit()
    assert await expire_stale(db_session) == 1
    await db_session.commit()
    for t in (stale, held, fresh):
        await db_session.refresh(t)
    assert (stale.status, held.status, fresh.status) == ("expired", "pending", "pending")


async def test_expired_topup_is_not_payable(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    await expire_stale(db_session)
    await db_session.commit()
    assert (await resolve(db_session, t.number)).reason == "expired"
```

(`test_sweep_keeps_a_topup_with_a_kassa_transaction` = the `held` assertion; name the test so Review Focus 3 can find it, e.g. split into two tests.)

- [ ] **Step 2: Implement**

`topups.py` per **Interfaces** (port the replay-matching of `ym:wallet/funding.py:40-162` — `_assert_replay_matches` in both the pre-check and the IntegrityError race path — onto `wallet_topups`; drop surfaces, client hints, currencies). `expire_stale`: select `pending` top-ups with `expires_at < now()` that have no attempt in `pending|succeeded`, `FOR UPDATE SKIP LOCKED`, limit; set `expired`, `cancel_pending` every `created` attempt; return the count. Routes follow `users/routes.py`'s idempotency pattern (scope `wallet.topups:{user_id}` — the top-up table's own `(user_id, idempotency_key)` unique is the source of truth; the replay store is optional here, say which you used in the report). `entries_for_user`: keyset on `(created_at DESC, id DESC)`, opaque base64 cursor, limit 1..100 default 20; signed amount = `+amount` when the user leg is D (normal side), `−` when C; `reference_number` = the top-up number for `topup`/`topup_reversal` (join on `reference_type='topup'`), else null. Mount `payments.routes` (providers + wallet top-ups — or put top-up routes in `wallet/routes.py` importing from `payments`: NO — `wallet` must not import `payments`; put `/wallet/topups*` in `payments/routes.py` under the `/wallet` prefix) and `wallet.routes` (balance + entries) and `payments.dev_routes`. Job `topup_expiry.py` like Task M2's `fx_refresh.py` shape (`run()` never raises, logs `wallet.topup_expiry.done count=`).

Regenerate `docs/api/openapi.json`.

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_topups.py tests/integration/test_wallet_routes.py tests/integration/test_topup_expiry.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/payments): balance top-ups, balance and entries API, expiry sweep, dev pay

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Common deltas for the three kassa ports (Tasks 5–7)

Every acquirer task ports YuPay's module and its tests through the rename filter, then applies
these deltas. The task lists only what is specific to its kassa.

1. **No orders.** Every `select(Order)…` / `_resolve_order` / `_check_order_state` becomes
   `payable = await payable.resolve(db, account, lock=True)` (Task 3). Map `payable.reason`:
   `not_found` → "account not found", `paid` → "already paid", `expired`/`reversed` →
   "cannot be paid" (per-kassa codes below). Amounts compare against `payable.amount_uzs`.
2. **Transaction tables key by payment, not order.** Replace `order_id … FK orders` with
   `payment_id uuid NOT NULL FK payments ON DELETE RESTRICT` and add `account varchar(8) NOT NULL`
   (the number the kassa sent; used in statements and admin) with an index. Keep every other
   column, constraint and index as YuPay's.
3. **`_ensure_payment` → `hooks.ensure_attempt(db, payable=payable, provider=<slug>)`**, then
   `hooks.mark_pending(db, payment=…)` when the kassa's transaction is born (Click prepare,
   Payme CreateTransaction, Uzum `/create`).
4. **Provider hooks:** `settle_provider_payment` → `hooks.settle(db, payment=…, event_id=…)`;
   `reverse_provider_payment` → `hooks.reverse(…)`; `cancel_pending_provider_payment` →
   `hooks.cancel_pending(…)`. `AlreadyPaidError` and `TopupSpentError` map to kassa codes below.
   YuPay's delivery guards (`_any_goods_delivered`, `skin_trade_in_flight`,
   `refunded_to_wallet`, order statuses `fulfilled/delivered`) are replaced by `TopupSpentError`
   for top-ups; M4 adds the order guards.
5. **Drop:** anti-fraud veto (`orders.risk`, `precharge_veto_full`), guest orders, the non-UZS
   currency guard (UZS only by construction — keep exact-amount checks), `click_miniapp`,
   affiliate, notifications/Telegram alerts (log a warning instead; M4 brings email),
   `import yupay.api.v1  # noqa` cycle hacks (csmarket's `wallet` never imports `payments`, so the
   cycle does not exist — if one appears, fix the import, do not paper over it).
6. **Routes:** prefix `/api/v1/payments/<kassa>`; mount in `api/v1/router.py`; add every handler
   to `bootstrap._exempt_self_authenticating_routes` (one audited list, with a one-line comment
   per kassa); add the module to `tests/unit/test_import_order.py`. Commit inside the
   try/except so a commit failure still renders the kassa's internal-error code (YuPay's
   `_install_flaky_commit` tests come along).
7. **Logging:** method + outcome code + number + amount; never the Basic-auth header, the
   Click `sign_string`, Uzum `payment_source` (holds the payer's phone) or raw bodies.
8. **Tests:** port the kassa's `*_service`, `*_webhook`/`*_merchant`, `*_timeout`, `*_errors`,
   `*_signature`/`*_config`, `*_gateway` suites; replace `_make_order`/`_seed_order` with
   `payments_factory.make_topup`; replace Telegram/guest login helpers with nothing (kassas are
   anonymous callers) or `customer_headers` where a customer call is involved; delete tests of
   dropped behaviour (veto, guest, SKU/fulfilment delivery guards, currency) and replace the
   delivery guards with the top-up "spent" equivalents. Keep the sandbox sequences and every
   money-safety test (shared attempt, retry after cancel, race on insert). Coverage of the kassa
   module ≥ 95 % (`uv run pytest --cov=csmarket.modules.<kassa> --cov-report=term-missing`).
9. **Docs:** module `README.md` ported and rewritten for top-ups (YuPay's `click|payme|uzum/README.md`);
   cabinet settings the owner must enter go to Task 16's `kassa-setup.md` — list them in the report.

---

### Task 5: Click (Shop API: prepare / complete, MD5 sign)

**Files:**

- Create: `apps/api/src/csmarket/modules/click/{__init__,api,errors,signature,models,service,routes}.py`, `modules/click/README.md`, `apps/api/src/csmarket/modules/payments/gateways/click.py`, `apps/api/migrations/versions/0008_click_transactions.py`, `apps/scheduler/src/csmarket_scheduler/jobs/click_timeout.py`
- Modify: `payments/gateways/__init__.py` (register), `api/v1/router.py`, `bootstrap.py`, `migrations/env.py`, integration `conftest.py` (`_EMPTY_IN_ORDER`: `"click_transactions"` first), scheduler `main.py` + `test_main.py`, `tests/unit/test_import_order.py`, `docs/api/openapi.json`
- Test: `apps/api/tests/unit/{test_click_errors,test_click_signature,test_click_gateway}.py`, `apps/api/tests/integration/{test_click_service,test_click_webhook,test_click_timeout}.py`, `apps/scheduler/tests/test_click_timeout.py`

**Interfaces:**

- Consumes: Common deltas; Task 3 hooks/resolver; settings `click_merchant_id`, `click_service_id`, `click_secret_key`, `click_pay_url`.
- Produces: `ClickTransaction` (`click_transactions`: YuPay columns with delta 2 — `merchant_prepare_id BIGINT IDENTITY UNIQUE`, `click_trans_id`, `service_id`, `payment_id`, `account`, `amount numeric(14,0)` soʻm, `status PREPARED|CONFIRMED|CANCELLED`, `click_paydoc_id`, `prepare_time/complete_time/cancel_time`, timestamps; `uq_click_transactions_trans_service (click_trans_id, service_id)`); routes `POST /api/v1/payments/click/prepare`, `POST /api/v1/payments/click/complete` (form-urlencoded, always HTTP 200); `ClickGateway` (`provider="click"`, `available = click_merchant_id and click_service_id and click_secret_key`, `intent_url` = `{click_pay_url}?service_id=&merchant_id=&amount=<soʻm>&transaction_param=<number>&return_url=<R10 url>`); scheduler job `click.timeout` (every 300 s, PREPARED older than 30 min → CANCELLED + `cancel_pending`, `first_run_after(160)`).

Source: `ym:click/*` (errors 115, signature 173, models 90, routes 309, service 499 LOC), `ym:payments/gateways/click.py`, `yupay:apps/scheduler/src/yupay_scheduler/jobs/click_timeout.py`, tests `yupay:apps/api/tests/unit/test_click_{errors,signature,gateway}.py`, `…/integration/test_click_{service,webhook,timeout}.py`. Read `yupay:docs/decisions/0036-click-shop-api.md` and `yupay:docs/runbooks/click-troubleshooting.md` first.

Click-specific deltas:

- **One service** (web): `secret_for_service(service_id)` returns `click_secret_key` only when `service_id == click_service_id`; drop the bot service, `merchant_user_id_*`.
- **Codes:** `not_found` → −5; `paid` (prepare) → −4; `expired`/`reversed` → −9; amount ≠ `payable.amount_uzs` (Decimal of the raw string) → −2; complete on an attempt whose top-up is already paid through another attempt (`AlreadyPaidError`) → −4 and the Click txn becomes CANCELLED (so Click cancels the second charge) — pin `test_a_second_prepare_on_a_paid_topup_is_minus4` (prepare on a `succeeded` top-up) and `test_a_complete_after_the_topup_was_paid_elsewhere_is_minus4`.
- `merchant_trans_id` carries the top-up number (`T…`); `transaction_param` in the checkout URL is the number.
- Keep: replay of prepare on `(click_trans_id, service_id)`, SAVEPOINT race on insert, negative inbound `error` → cancel + −9, non-POST → −8, signatures over raw wire strings, constant-time compare, IDENTITY `merchant_prepare_id`.

- [ ] **Step 1: Port tests (RED), then code (GREEN)** — unit suites first (errors, signature, gateway), then service, webhook, timeout. Add the two −4 tests above and `test_amount_in_soum_not_tiyin` (prepare with `amount = topup×100` → −2).
- [ ] **Step 2: Migration 0008** (`down_revision = "0007_payments_topups"`), models import in `env.py` and scheduler `main.py`; `_EMPTY_IN_ORDER` gets `"click_transactions"` before `"payments"`.
- [ ] **Step 3: Wire** router, gateway registry, slowapi exemption (`click_prepare`, `click_complete`), timeout job; regenerate OpenAPI.
- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit -k click tests/integration -k click --cov=csmarket.modules.click --cov-report=term-missing -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/click): Click Shop API for balance top-ups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Payme (Merchant API, JSON-RPC)

**Files:**

- Create: `apps/api/src/csmarket/modules/payme/{__init__,api,errors,models,service,routes}.py`, `modules/payme/README.md`, `apps/api/src/csmarket/modules/payments/gateways/payme.py`, `apps/api/migrations/versions/0009_payme_transactions.py`, `apps/scheduler/src/csmarket_scheduler/jobs/payme_timeout.py`
- Modify: as Task 5 (registry, router, bootstrap, env.py, conftest, scheduler main/test, import order, OpenAPI)
- Test: `apps/api/tests/unit/{test_payme_errors,test_payme_gateway,test_payme_config}.py`, `apps/api/tests/integration/{test_payme_service,test_payme_merchant,test_payme_models,test_payme_timeout}.py`, `apps/scheduler/tests/test_payme_timeout.py`

**Interfaces:**

- Produces: `PaymeTransaction` (`payme_transactions`: YuPay columns with delta 2 — `payme_id varchar(64) UNIQUE`, `payment_id`, `account`, `amount_tiyin BIGINT`, `state` ∈ {1,2,−1,−2}, `reason`, `create_time/perform_time/cancel_time` BIGINT epoch-ms default 0, `fiscal_data jsonb`, timestamps; `ix_payme_transactions_state_create`); route `POST /api/v1/payments/payme/merchant` (GET → −32300); `PaymeGateway` (`provider="payme"`, `available = payme_merchant_id and (payme_key or payme_test_key)`, `intent_url` = `{payme_checkout_url}/{base64("m=<id>;ac.order=<number>;a=<tiyin>;c=<R10 url>;l=<ru|uz|en>")}`); job `payme.timeout` (every 300 s, state 1 older than 12 h → −1 reason 4 + `cancel_pending`, `first_run_after(180)`).

Source: `ym:payme/*` (errors 247, models 80, routes 238, service 599), `ym:payments/gateways/payme.py`, `yupay:…/jobs/payme_timeout.py`, tests `test_payme_{errors,gateway,config}.py`, `test_payme_{service,merchant,models,timeout}.py`. Read `yupay:docs/decisions/0034-payme-merchant-api.md` and `yupay:docs/runbooks/payme-troubleshooting.md` (sandbox sequences, the 2026-09-29 retry incident) first.

Payme-specific deltas:

- **Account key `order`** (R9): `params.account.order`; `GetStatement` rows carry `account: {order: <number>}`; the checkout param is `ac.order`. A missing/blank account → −31050 with `data: "order"`.
- **Codes:** `not_found` → −31050; `paid`/`expired`/`reversed` → −31051; amount ≠ `amount_uzs × 100` → −31001; a second active txn on the same top-up → −31099 (keep YuPay's account-range rule); `PerformTransaction` on an attempt whose top-up was paid elsewhere (`AlreadyPaidError`) → −31008 and the txn is cancelled (state −1, reason 3? — use YuPay's nearest reason or 5 "unknown"; say which in the README); `CancelTransaction` state 2 with `TopupSpentError` → −31007 (`test_cancel_performed_spent_topup_is_31007`); unspent → state −2, `hooks.reverse`.
- Auth: `Basic Paycom:<key>`, key = `payme_key` or `payme_test_key`, constant-time, non-ASCII fails closed → −32504 at HTTP 200.
- Keep: replay echoes, `SetFiscalData`, `GetStatement`, trilingual error messages (fix any UZ apostrophes to ʻ/ʼ), the retry-after-cancel test (`test_a_new_transaction_after_a_cancelled_one_can_pay`).

- [ ] **Step 1: Port tests (RED), then code (GREEN)**; add `test_amount_in_tiyin` (CheckPerform with `amount = amount_uzs` → −31001; `× 100` → allow), `test_cancel_performed_spent_topup_is_31007`, `test_perform_after_paid_elsewhere_is_31008`.
- [ ] **Step 2: Migration 0009** (`down_revision = "0008_click_transactions"`), env.py, conftest, scheduler main.
- [ ] **Step 3: Wire** router, registry, exemption (`payme_merchant`), timeout job, OpenAPI.
- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit -k payme tests/integration -k payme --cov=csmarket.modules.payme --cov-report=term-missing -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/payme): Payme Merchant API for balance top-ups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Uzum (Merchant API: check / create / confirm / reverse / status)

**Files:**

- Create: `apps/api/src/csmarket/modules/uzum/{__init__,api,errors,models,service,routes}.py`, `modules/uzum/README.md`, `apps/api/src/csmarket/modules/payments/gateways/uzum.py`, `apps/api/migrations/versions/0010_uzum_transactions.py`, `apps/scheduler/src/csmarket_scheduler/jobs/uzum_timeout.py`, `docs/api/uzum.postman_collection.json` (ported, values faked)
- Modify: as Task 5
- Test: `apps/api/tests/unit/{test_uzum_errors,test_uzum_gateway,test_uzum_config}.py`, `apps/api/tests/integration/{test_uzum_service,test_uzum_webhook,test_uzum_timeout}.py`, `apps/scheduler/tests/test_uzum_timeout.py`

**Interfaces:**

- Produces: `UzumTransaction` (`uzum_transactions`: delta 2 — `trans_id varchar(64) UNIQUE`, `payment_id`, `account`, **`amount_tiyin BIGINT` created once** (do not port YuPay's 0030/0031 rename), `status CREATED|CONFIRMED|REVERSED|FAILED`, `service_id`, `create_time` BIGINT ms, `confirm_time/reverse_time` BIGINT null, `payment_source jsonb`, timestamps); routes `POST /api/v1/payments/uzum/{check,create,confirm,reverse,status}` (non-POST → 10003 at 400); `UzumGateway` (`provider="uzum"`, `available = uzum_service_id and ((login and password) or (test_login and test_password))`, `intent_url` = `{uzum_open_service_url}?serviceId=<id>&order=<number>&redirectUrl=<R10 url>` — no amount: Uzum prefills it from `/check`); job `uzum.timeout` (every 300 s, CREATED older than 30 min → FAILED + `cancel_pending`, `first_run_after(200)`).

Source: `ym:uzum/*` (errors 173, models 83, routes 491, service 573), `ym:payments/gateways/uzum.py`, `yupay:…/jobs/uzum_timeout.py`, tests `test_uzum_{errors,gateway,config}.py`, `test_uzum_{service,webhook,timeout}.py`, `yupay:docs/api/uzum.postman_collection.json`. Read `yupay:docs/decisions/0035-uzum-merchant-api.md`, `yupay:docs/runbooks/uzum-troubleshooting.md` first.

Uzum-specific deltas:

- **Account key** (R9): `params.order`, else `params.orderId`, else `params.order_id` (YuPay's `_req_order_id` extended with `order` first); tests for all three spellings.
- **Codes:** `not_found` → 10007; `paid` → 10008; `expired`/`reversed` → 10009; wrong amount (tiyin) → 10011; `/confirm` with `AlreadyPaidError` → 10008 and the txn FAILED; `/reverse` CONFIRMED with `TopupSpentError` → 10017 (`test_reverse_spent_topup_is_10017`); unspent → REVERSED + `hooks.reverse`.
- **Units:** wire `amount` = tiyin on `/create`, `/confirm`, `/reverse`, `/status`; `/check` returns `data.amount.value` in soʻm (string, whole soʻm as a bare integer) — `test_check_returns_soum_value`.
- **HTTP:** 200 on success, **400** on every error; response `timestamp` is our response time (YuPay's 2026-07-25 fix).
- `payment_source` stored as received minus envelope keys; never logged; admin shows it masked (Task 10).
- The Postman collection: port with every credential, phone and id replaced by obvious fakes.

- [ ] **Step 1: Port tests (RED), then code (GREEN)** with the added tests above and the camelCase/snake_case/`order` account tests.
- [ ] **Step 2: Migration 0010** (`down_revision = "0009_payme_transactions"`), env.py, conftest, scheduler main.
- [ ] **Step 3: Wire** router, registry, exemptions (five handlers), timeout job, OpenAPI.
- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit -k uzum tests/integration -k uzum --cov=csmarket.modules.uzum --cov-report=term-missing -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../scheduler && uv run pytest -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/uzum): Uzum Merchant API for balance top-ups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Kassa edge — Caddy allowlist, log hygiene, webhook rejection metric and alert

**Files:**

- Modify: `infra/caddy/Caddyfile.prod`, `apps/api/src/csmarket/core/metrics.py`, `apps/api/src/csmarket/modules/{click,payme,uzum}/routes.py` (count rejections), `infra/prometheus/alerts/api.yml` (or a new `payments.yml`), `docs/architecture/metrics.md` (create if absent)
- Test: `apps/api/tests/unit/test_metrics.py` (extend or create), `apps/api/tests/integration/test_kassa_rejection_metric.py`, `infra` config lint if the repo has one (`make lint` covers promtool/caddy validate? check the Makefile; if not, run `docker run --rm -v $PWD/infra/caddy:/etc/caddy caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile.prod --adapter caddyfile` — the file may reference env vars; set dummy ones)

**Interfaces:**

- Produces: metric `csmarket_kassa_rejections_total{provider="click|payme|uzum", reason="auth|signature|malformed"}` (bounded labels, no person); alert `KassaRejectionsSpike` (`increase(…[15m]) > 20`, severity warning, `runbook:` link to Task 16's `docs/runbooks/kassa-setup.md#rejections`) — spec §12 "webhook signature failures spike".

- [ ] **Step 1: Caddy** — port `yupay:infra/caddy/Caddyfile.prod:227-271`: `@paymeMerchantBlocked { path /api/v1/payments/payme/merchant; not client_ip 185.234.113.0/28 } respond @paymeMerchantBlocked 403` (must be `client_ip`, never `remote_ip` — ADR-0003: the edge rewrites XFF; comment that this doubles as a canary for the edge wiring) and the **commented-out** Uzum stanza with YuPay's warning "do not uncomment with a guessed CIDR". Confirm the access-log filter already drops `Authorization` (M0 Caddy filters headers/query); add `request>headers>Authorization` delete if missing. Validate the Caddyfile.
- [ ] **Step 2: Metric (test first)** — `core/metrics.py` gains the counter with label value whitelists (reject unknown labels → `"other"`); each kassa route increments it on auth failure / bad signature / malformed body (Click −1 sign, −8 malformed; Payme −32504, −32600/−32700; Uzum 10001, 10002/10005). Integration test: three bad Click signatures → counter for `{provider="click",reason="signature"}` = 3 (read via the `/metrics` endpoint text).
- [ ] **Step 3: Alert + metrics doc** — the rule; `docs/architecture/metrics.md` row (name, labels, meaning, alert).
- [ ] **Step 4: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_metrics.py tests/integration/test_kassa_rejection_metric.py -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh && npx prettier --check .
git add -A && git commit -m "feat(infra): Payme IP allowlist, kassa rejection metric and alert

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Admin users API — list, card, ban/unban, balance adjustment (audited)

**Files:**

- Create: `apps/api/src/csmarket/modules/admin/{users_routes,users_schemas,users_service}.py`
- Modify: `apps/api/src/csmarket/modules/wallet/service.py` (+ `admin_adjust`, `entries_for_admin`), `wallet/api.py`, `apps/api/src/csmarket/modules/auth/api.py` (+ `revoke_all_sessions` if no public equivalent exists), `api/v1/router.py`, `tests/unit/test_import_order.py`, `modules/admin/README.md`, `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_admin_users.py`, `apps/api/tests/integration/test_wallet_admin_adjust.py`

**Interfaces:**

- Consumes: `admin.deps.require_admin`, `admin.audit.record`, `core.idempotency` (pattern of `skins/admin_routes.py` from M2), `wallet.api`, `payments.models.WalletTopup`, `users.models.User`, `auth.api`.
- Produces (all under `/api/v1/admin`, `require_admin`):
  - `GET /admin/users?q=&cursor=&limit=` → `{items: [AdminUserRow {id, display_name, avatar_url, steam_id, roles, banned_at, created_at, balance_uzs}], next_cursor}`; `q` matches display name (ILIKE, escaped) or an exact 17-digit Steam ID; keyset on `(created_at DESC, id DESC)`; balance via one aggregate subquery (no N+1 — a query-count test).
  - `GET /admin/users/{id}` → `AdminUserCard {user: {id, steam_id, display_name, avatar_url, email, locale, roles, banned_at, ban_reason, created_at, trade_link_masked, trade_link_verdict, trade_link_reason, trade_link_checked_at}, balance_uzs, entries: [AdminEntryOut {id, kind, amount_uzs, created_at, reference_number, actor, reason}], topups: [{number, amount_uzs, status, provider, created_at, succeeded_at}]}` (last 20 of each). `trade_link_masked` keeps `partner` and shows the token as `••••` + last 2 chars.
  - `POST /admin/users/{id}/ban` body `{reason: 3..500}` + `Idempotency-Key` → `AdminUserCard`; refuses self and other admins (409); sets `banned_at/ban_reason`, revokes every refresh session of the user, audit `users.ban` `{reason}`.
  - `POST /admin/users/{id}/unban` body `{reason: 3..500}` + key → card; clears ban columns; audit `users.unban` `{reason}`.
  - `POST /admin/users/{id}/wallet/adjust` body `{amount_uzs: int (≠ 0, |x| ≤ 100 000 000), reason: 4..500}` + key → card; `wallet.admin_adjust` (credit `D user_wallet / C house_adjustments`, clawback inverse; lock the user account; clawback that would go below zero → `InsufficientBalanceError` 409 `balance_too_low` — R13); ledger key `admin_adjust:<idempotency key>`, `actor = "admin:<admin id>"`, `metadata = {"reason": …}`; audit `wallet.adjust` `{amount_uzs, reason}`.
  - `wallet.service.admin_adjust(db, *, user_id, amount: Decimal, reason, admin_id, idempotency_key) -> WalletTransaction`; `entries_for_admin(db, user_id, *, limit=20)` (includes actor and reason; the customer endpoint never does).

- [ ] **Step 1: Tests first (Review Focus 5)**

`test_wallet_admin_adjust.py` (service level): credit then clawback; `test_clawback_below_zero_is_409` (balance 5 000, clawback 6 000 → `InsufficientBalanceError`, balance unchanged); `test_replayed_adjust_posts_once` (same key twice → one transaction); amount 0 → `ValidationError`.

`test_admin_users.py` (HTTP, `admin_headers`/`customer_headers` fixtures, `payments_factory`): list with search by name and by exact Steam ID; balance column correct; query count for the list is constant across 5 vs 30 users (use the suite's query-counter helper if one exists — grep `count_queries`/`event.listen(...before_cursor_execute` — or add a small one in conftest); card shows masked trade link (`token` absent from the JSON text); ban → audit row + the customer's next `GET /api/v1/me` is 403 account-suspended and their refresh fails; ban self / another admin → 409; replayed ban (same key) → one audit row; unban → audit; adjust credit/clawback with reasons → card balance and entries show `actor`/`reason`; the customer's `GET /api/v1/wallet/entries` for the same entry shows no reason (redaction); a customer calling any admin route → 403.

- [ ] **Step 2: Implement**

Put the routes in the `admin` module (it may import `users`, `wallet`, `payments`, `auth`; none of them import `admin` routes — keep the one-direction rule; check `test_import_order.py`). Follow `skins/admin_routes.py` exactly for idempotency + audit + commit order: change → `audit.record` → `save_replay` → commit. `revoke_all_sessions(db, user_id)` in `auth.api`: mark every live refresh token revoked and blocklist their session ids (reuse the reuse-detection helper from M1 if it has this shape). Regenerate OpenAPI. `admin/README.md`: list the new routes and the audit action names.

- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_admin_users.py tests/integration/test_wallet_admin_adjust.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/admin): users list and card, ban and unban, audited balance adjustment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Admin payments and audit API

**Files:**

- Create: `apps/api/src/csmarket/modules/admin/{payments_routes,payments_schemas,audit_routes}.py`
- Modify: `api/v1/router.py`, `tests/unit/test_import_order.py`, `modules/admin/README.md`, `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_admin_payments.py`, `apps/api/tests/integration/test_admin_audit_routes.py`

**Interfaces:**

- Produces (all `require_admin`):
  - `GET /admin/payments?q=&status=&provider=&purpose=&cursor=&limit=` → `{items: [AdminPaymentRow {id, number, purpose, provider, amount_uzs, status, created_at, succeeded_at, user: {id, display_name}}], next_cursor}`; `q` = a full or partial number (upper-cased, prefix match on `number`); keyset `(created_at DESC, id DESC)`.
  - `GET /admin/payments/{id}` → `AdminPaymentDetail {payment: AdminPaymentRow + provider_ref + metadata, topup: {number, amount_uzs, status, expires_at, succeeded_at} | null, kassa: [KassaTxnOut {provider, external_id, status, amount, amount_unit: "soum"|"tiyin", times: {created, performed, cancelled}, extra: dict[str, str]}]}` — Click/Payme/Uzum rows for this payment; Uzum `payment_source` reduced to `{"source": <paymentSource>, "phone": "+998••••••12"}` (mask all but the last 2 digits); never the full body.
  - `GET /admin/audit?action=&target_type=&target_id=&actor_id=&cursor=&limit=` → `{items: [AuditRow {id, created_at, action, target_type, target_id, actor: {id, display_name}, payload}], next_cursor}`.

- [ ] **Step 1: Tests first** — list filters and number search (`T7K` finds the top-up's attempts), detail with each kassa's rows (seed rows directly with the Task 5–7 models), Uzum phone masked (`"998901234567"` never appears in the response text), audit list filters and paging, customers → 403, unknown id → 404.
- [ ] **Step 2: Implement** in the `admin` module (it imports `click`, `payme`, `uzum`, `payments`; nothing imports it back). Regenerate OpenAPI.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_admin_payments.py tests/integration/test_admin_audit_routes.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/admin): payments search and detail with kassa transactions, audit log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Storefront `/account/balance` — balance, entries, top-up form

**Files:**

- Create: `apps/web/src/lib/{balance,amount-input}.ts` (+ tests), `apps/web/src/app/[locale]/account/balance/page.tsx`, `apps/web/src/components/balance/{BalanceView,TopupForm,EntriesList}.tsx` (+ tests)
- Modify: `apps/web/src/components/account/AccountView.tsx` (link «Баланс»), `packages/i18n/locales/{ru,uz,en}/web.json` (+ `web.balance`)
- Test: `apps/web/src/lib/{balance,amount-input}.test.ts`, `apps/web/src/components/balance/{TopupForm,EntriesList}.test.tsx`

**Interfaces:**

- Consumes: Task 4 routes; `session` (`@/lib/api`), `useAuth`; `formatUzs` from `@csmarket/utils`.
- Produces: `lib/balance.ts`: types `Topup`, `Entry`, `EntriesPage`, `Provider`; `getBalance()`, `getEntries(cursor?)`, `getProviders()` (anonymous), `createTopup({amount_uzs, provider, locale}, idempotencyKey)`, `getTopup(number)`, `devPay(number)`; `TOPUP_MIN = 1000`, `TOPUP_MAX = 10_000_000`, `QUICK_AMOUNTS = [50_000, 100_000, 250_000, 500_000]`; `topupAttemptKey(ref, signature)` (one key per (amount, provider) signature so a retry replays — YuPay's `topUpAttemptKey`). `lib/amount-input.ts`: port `yupay:apps/web/src/lib/amount-input.ts` + test as is (digit grouping, caret).

Copy (`web.balance`, ru; uz/en equivalents in the same commit; «вы»; no service meta; no acquirer internals):

```json
"balance": {
  "title": "Баланс",
  "signedOut": "Войдите через Steam, чтобы открыть баланс.",
  "amount": "На балансе",
  "topUpTitle": "Пополнить",
  "amountLabel": "Сумма",
  "amountRange": "От {min} до {max}",
  "methodLabel": "Способ оплаты",
  "methodTest": "Тестовая оплата",
  "methodNone": "Пополнение сейчас недоступно.",
  "submit": "Пополнить на {amount}",
  "enterAmount": "Введите сумму",
  "badAmount": "Сумма от {min} до {max}, без тийинов.",
  "failed": "Не получилось начать оплату. Попробуйте ещё раз.",
  "historyTitle": "История",
  "historyEmpty": "Пока пусто.",
  "historyMore": "Показать ещё",
  "kind": { "topup": "Пополнение", "topup_reversal": "Пополнение отменено", "admin_adjust": "Корректировка" }
}
```

Provider tiles show the kassa names «Click», «Payme», «Uzum» (brand names, not translated) and «Тестовая оплата» for `mock`.

- [ ] **Step 1: Tests first** — `amount-input` ported tests; `balance.test.ts`: `topupAttemptKey` stable per signature and new after a change; `TopupForm.test.tsx`: quick amount fills the field; 999 shows `badAmount` and does not call `createTopup`; submit calls `createTopup` with an `Idempotency-Key` ≥ 16 chars and then navigates to `/account/balance/topups/<number>?go=1` (mock `useRouter`); no providers → `methodNone`; `EntriesList.test.tsx`: signed amounts (`+50 000 сум`, `−10 000 сум`), kind labels, «Показать ещё» fetches with the cursor.
- [ ] **Step 2: Implement** — the page is a Server Component shell (`robots: noindex`, title `web.balance.title`, `generateMetadata` with the route locale) rendering client `BalanceView` (auth states like `AccountView`: loading / signed out → sign-in link / suspended / signed in). Tokens per M2's table. Account page gets a «Баланс» link.
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/balance): balance page with history and top-up form

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Storefront top-up status page — redirect to the kassa, wait, confirm

**Files:**

- Create: `apps/web/src/app/[locale]/account/balance/topups/[number]/page.tsx`, `apps/web/src/components/balance/TopupStatus.tsx` (+ test), `apps/web/src/lib/kassa-redirect.ts` (+ test)
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (+ `web.balance.topup.*`)
- Test: `apps/web/src/components/balance/TopupStatus.test.tsx`, `apps/web/src/lib/kassa-redirect.test.ts`

**Interfaces:**

- Consumes: `getTopup`, `devPay` (Task 11), `session`.
- Produces: `lib/kassa-redirect.ts`: `shouldAutoOpen(number, search) -> boolean` (true once per tab when `?go=1` — sessionStorage key `csmarket.web.kassa_opened.<number>`, wrapped in try/catch), `markOpened(number)`; the status page.

Behaviour (YuPay's `docs/product/flows/payment-return.md` lesson: on phones the kassa opens the bank app and the tab never comes back, so the page must make sense on its own):

- `pending`: «Ждём оплату» + the amount + button «Перейти к оплате» (`intent_url`); with `?go=1` the page opens `intent_url` once automatically (`window.location.assign`); polls `getTopup` every 3 s for up to 2 min while visible, then stops with «Обновить» link. Mock provider: the button is «Оплатить (тест)» calling `devPay` then refetching.
- `succeeded`: «Баланс пополнен на {amount}» + link «К балансу».
- `expired`: «Время на оплату вышло. Создайте новое пополнение.» + link to `/account/balance`.
- `reversed`: «Пополнение отменено.» + link to `/account/balance`.
- 404 → «Пополнение не найдено.»; signed out → sign-in link (the number alone reveals nothing).

Copy keys under `web.balance.topup`: `waiting`, `pay`, `payTest`, `refresh`, `done`, `toBalance`, `expired`, `reversed`, `notFound` — ru as above, uz/en equivalents.

- [ ] **Step 1: Tests first** — `kassa-redirect` once-per-tab semantics and storage failure tolerance; `TopupStatus` renders each state, auto-opens once with `?go=1` (spy `window.location.assign`), not without it, polling stops after success (fake timers), mock button calls `devPay`.
- [ ] **Step 2: Implement** — page shell `noindex`, client component; poll with `useQuery` `refetchInterval` that returns `false` once terminal or after 40 polls.
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/balance): top-up status page with one-time kassa redirect

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Admin SPA — Users list and user card (ban, unban, adjust)

**Files:**

- Create: `apps/admin/src/features/users/{api.ts, UsersPage.tsx, UserCard.tsx, BanDialog.tsx, AdjustForm.tsx, parseAmount.ts}` (+ `UsersPage.test.tsx`, `UserCard.test.tsx`, `parseAmount.test.ts`)
- Modify: `apps/admin/src/app/router.tsx` (`/users`, `/users/:id`), `apps/admin/src/app/Layout.tsx` (nav «Пользователи»)

**Interfaces:**

- Consumes: Task 9 routes; `session` from `@/lib/api`; `@csmarket/ui`.
- Produces: `parseAmount(input: string) -> number | null` — port `yupay:apps/admin/src/features/wallet/parseAmount.ts` + test (strict: whole soʻm, optional sign, spaces/NBSP grouping; rejects `1e9`, `--5`, decimals); pages per below. Every mutation sends one Idempotency-Key per _confirmed_ submission (a ref regenerated after success — YuPay's `idemKeyRef` pattern), so a double click replays instead of double-posting.

UI (Russian, «вы», short):

- Users: search box «Имя или Steam ID», table (аватар, имя, баланс, роль, «заблокирован» badge, дата), «Показать ещё».
- Card: profile (имя, Steam ID, ссылка на профиль Steam, email, язык, трейд-ссылка masked + вердикт), «Баланс: N сум», history (kind label, сумма со знаком, дата, «кто» и «причина» for adjustments), top-ups (номер → link to `/payments?q=<number>`, сумма, статус), actions: «Заблокировать» / «Разблокировать» (dialog with required reason), «Изменить баланс» (signed amount + required reason + confirm step showing «Начислить 50 000 сум» / «Списать 10 000 сум»), 409 `balance_too_low` → «На балансе меньше, чем вы хотите списать.».

- [ ] **Step 1: Tests first** — `parseAmount` ported; `UsersPage` search calls the API with `q`; `UserCard`: adjust confirm sends signed amount + reason + a ≥ 16-char key, a second click while pending does not send a second request, 409 shows the message; ban requires a reason.
- [ ] **Step 2: Implement**, router + nav.
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/users): users list and card with ban and balance adjustment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Admin SPA — Payments and Audit

**Files:**

- Create: `apps/admin/src/features/payments/{api.ts, PaymentsPage.tsx, PaymentDetail.tsx}` (+ tests), `apps/admin/src/features/audit/{api.ts, AuditPage.tsx}` (+ test)
- Modify: `router.tsx` (`/payments`, `/payments/:id`, `/audit`), `Layout.tsx` (nav «Платежи», «Журнал»)

**Interfaces:**

- Consumes: Task 10 routes.
- Produces: Payments page — search «Номер платежа или пополнения», filters (статус, касса, назначение), table (номер, сумма, касса, статус chip, пользователь → `/users/:id`, создан); detail — payment fields, top-up block, kassa transactions table (касса, внешний id, статус, сумма с единицей «сум»/«тийин», время), masked Uzum phone. Audit page — filters (действие, тип цели, id цели), table (когда, кто, действие, цель → link where it maps to a page, payload as short key: value list).

Action labels: `users.ban` «Блокировка», `users.unban` «Разблокировка», `wallet.adjust` «Изменение баланса», `skins.item.hide` «Скин скрыт», `skins.item.unhide` «Скин показан», `skins.alias.put` «Синоним сохранён», `skins.alias.delete` «Синоним удалён»; unknown → the raw action.

- [ ] **Step 1: Tests first** — search passes `q`; status chip text per status; detail renders kassa rows and never the raw phone; audit labels.
- [ ] **Step 2: Implement**, router + nav.
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/payments): payments search and detail, audit log page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: e2e — top-up through the test kassa, admin adjust and ban

**Files:**

- Create: `e2e/tests/balance.spec.ts`, `e2e/tests/admin-money.spec.ts`
- Modify: `e2e/playwright.config.ts` (anchored `testMatch` for the new specs in `web-chromium` / `admin-chromium`), `e2e/global-setup.ts` (warm `/account/balance`), `e2e/README.md`

**Interfaces:**

- Consumes: dev stack with `make migrate && make seed-skins`, the mock provider (dev only), `devLogin(page, …)` (M1 helper), Tasks 11–14 UI labels.

- [ ] **Step 1: Specs**

```ts
// e2e/tests/balance.spec.ts
import { expect, test } from "@playwright/test";

import { API, devLogin } from "./helpers";

const uniqueSteamId = () => `7656119800${String(Date.now()).slice(-7)}`;

test("top up 50 000 soʻm through the test kassa and see it on the balance", async ({ page }) => {
  await devLogin(page, { steamId: uniqueSteamId(), name: "Buyer" });
  await page.goto("/account/balance");
  await expect(page.getByRole("heading", { name: "Баланс" })).toBeVisible();
  await page.getByLabel("Сумма").fill("50000");
  await page.getByRole("radio", { name: "Тестовая оплата" }).check();
  await page.getByRole("button", { name: /Пополнить на 50\s000/ }).click();
  await expect(page).toHaveURL(/\/account\/balance\/topups\/T[0-9A-Z]{7}/);
  await page.getByRole("button", { name: "Оплатить (тест)" }).click();
  await expect(page.getByText(/Баланс пополнен на 50\s000/)).toBeVisible();
  await page.getByRole("link", { name: "К балансу" }).click();
  await expect(page.getByText(/50\s000 сум/).first()).toBeVisible();
  await expect(page.getByText("Пополнение").first()).toBeVisible();
});

test("an amount below the minimum is refused in the form", async ({ page }) => {
  await devLogin(page, { steamId: uniqueSteamId() });
  await page.goto("/account/balance");
  await page.getByLabel("Сумма").fill("999");
  await page.getByRole("radio", { name: "Тестовая оплата" }).check();
  await page.getByRole("button", { name: /Пополнить/ }).click();
  await expect(page.getByText(/Сумма от 1\s000/)).toBeVisible();
});

test("someone else's top-up number shows not found", async ({ page, request }) => {
  await devLogin(page, { steamId: uniqueSteamId() });
  await page.goto("/account/balance/topups/TZZZZZZZ");
  await expect(page.getByText("Пополнение не найдено.")).toBeVisible();
  expect((await request.get(`${API}/api/v1/wallet/topups/TZZZZZZZ`)).status()).toBe(401);
});
```

```ts
// e2e/tests/admin-money.spec.ts
import { expect, test } from "@playwright/test";

import { API, devLogin } from "./helpers";

test("an admin credits, refuses an over-clawback, bans, and the audit shows it", async ({
  page,
  browser,
}) => {
  // A customer with a known name, signed in on its own context.
  const custId = `7656119801${String(Date.now()).slice(-7)}`;
  const customer = await browser.newPage();
  await devLogin(customer, { steamId: custId, name: `Cust ${custId.slice(-4)}` });
  await customer.goto("/account");

  await devLogin(page, {
    steamId: `7656119802${String(Date.now()).slice(-7)}`,
    name: "Owner",
    admin: true,
  });
  await page.goto("/users");
  await page.getByLabel("Имя или Steam ID").fill(custId);
  await page.getByRole("link", { name: `Cust ${custId.slice(-4)}` }).click();

  await page.getByRole("button", { name: "Изменить баланс" }).click();
  await page.getByLabel("Сумма").fill("25000");
  await page.getByLabel("Причина").fill("Компенсация за ожидание");
  await page.getByRole("button", { name: "Начислить 25 000 сум" }).click();
  await expect(page.getByText(/Баланс: 25\s000 сум/)).toBeVisible();

  await page.getByRole("button", { name: "Изменить баланс" }).click();
  await page.getByLabel("Сумма").fill("-30000");
  await page.getByLabel("Причина").fill("Проверка списания");
  await page.getByRole("button", { name: "Списать 30 000 сум" }).click();
  await expect(page.getByText("На балансе меньше, чем вы хотите списать.")).toBeVisible();

  await page.getByRole("button", { name: "Заблокировать" }).click();
  await page.getByLabel("Причина").fill("Тест блокировки");
  await page.getByRole("button", { name: "Заблокировать", exact: true }).last().click();
  await expect(page.getByText("заблокирован").first()).toBeVisible();

  await customer.reload();
  await expect(customer.getByText("Аккаунт заблокирован.")).toBeVisible();

  await page.goto("/audit");
  await expect(page.getByText("Изменение баланса").first()).toBeVisible();
  await expect(page.getByText("Блокировка").first()).toBeVisible();
  await customer.close();
  void API;
});
```

Align literals to the running pages (labels, headings) without weakening intent; unique Steam IDs per test keep parallel workers apart (M2 lesson: never mutate shared seed state in parallel specs).

- [ ] **Step 2: Run against the dev stack** — `docker compose up -d --build`, `docker compose exec api alembic upgrade head`, `make seed-skins`, readiness waits, `make test-e2e` twice (all M1/M2/M3 specs), `docker compose down` (no `-v`). Never touch other containers.
- [ ] **Step 3: Commit**

```bash
npx prettier --check . && pnpm --filter @csmarket/e2e lint && pnpm --filter @csmarket/e2e typecheck
git add -A && git commit -m "test(e2e): balance top-up through the test kassa, admin adjust, ban and audit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Docs, ADR-0006, kassa runbooks; full verification

**Files:**

- Create: `docs/decisions/0006-wallet-payments-topups.md`, `docs/runbooks/{kassa-setup,click,payme,uzum,wallet}.md`, `docs/product/flows/balance-topup.md`, `docs/architecture/sequence-diagrams/topup.mmd`
- Modify: `apps/api/src/csmarket/modules/{wallet,payments,click,payme,uzum,admin}/README.md` (finish), `docs/architecture/module-map.md`, `docs/architecture/cache-keys.md` (only if a Redis key was added — check), `docs/api/README.md`, `docs/security/pii-handling.md`, `AGENTS.md` (§0 M3 row + status; §10 note: kassa routes exempt from slowapi; §13 nothing new unless a make target was added)

- [ ] **Step 1: Write the docs**

- **ADR-0006** (template `docs/decisions/0000-template.md`): context (spec §15 M3, owner decisions D1–D2); decision = rulings R1–R14, one short paragraph each; consequences (top-ups credited once per top-up; spent top-ups cannot be reversed by a kassa; order numbers never start with `T`; M4 adds `purpose='order'` hooks, the wallet gateway, purchase/refund kinds and the order FK on `payments`); alternatives (YuPay's top-up-as-order; a flat `ledger_entries`; client-supplied return URLs); dependencies added in M3 (expect none — state it).
- **runbooks/kassa-setup.md**: per kassa — what to enter in the cabinet (callback URLs `https://api.csmarket.uz/api/v1/payments/click/{prepare,complete}`, `…/payme/merchant`, `…/uzum/{check,create,confirm,reverse,status}`; account field names `merchant_trans_id` / `order` / `order` (R9); currency soʻm; for Payme the login `Paycom` + key/test key; for Uzum the Basic pair and serviceId; IP allowlists (Payme `185.234.113.0/28` live in Caddy; Uzum pending their IP list)), where each secret goes (`secrets/api.env` keys), sandbox → prod switch, **first real top-up check after deploy (R14)** step by step (top up 1 000 soʻm through each kassa from a real card, see it on the balance and in admin Payments, reverse it from the kassa cabinet where possible and see the balance go back), `#rejections` section for the alert.
- **runbooks/click.md, payme.md, uzum.md**: ported from YuPay's troubleshooting runbooks, trimmed to csmarket (top-ups only; error codes; "customer paid but balance not credited" → check admin Payments → kassa transactions → statuses; timeout sweeps; what never to do — no manual DB credits, use admin adjust with a reason).
- **runbooks/wallet.md**: ledger model in plain words, how to read a user's history in admin, adjust with a reason, why a kassa reversal can be refused (spent top-up), balance never negative.
- **flows/balance-topup.md** + **topup.mmd**: Mermaid sequence — balance page → `POST /wallet/topups` → status page (auto-open once) → kassa → our callbacks (check/prepare/create → pending; perform/complete/confirm → settle → ledger credit) → status page polling → «Баланс пополнен»; expiry and reversal branches.
- **module-map.md**: `wallet`, `payments`, `click`, `payme`, `uzum` built (M3); `admin` aggregates users/payments/audit.
- **api/README.md**: customer wallet/top-up endpoints (Idempotency-Key, limits, 404 for foreign numbers), kassa endpoints and their auth, admin endpoints and audit actions.
- **pii-handling.md**: Uzum `payment_source` holds the payer's phone — stored, never logged, masked in admin; admin reasons are visible to admins only; money log lines carry number and amount, never a user id; trade link masked in the admin card.
- **AGENTS.md**: §0 M3 row → `docs/superpowers/plans/2026-10-01-m3-wallet-payments.md`; status: "M0–M2 merged on local main; M3 on branch `m3-wallet-payments` until the owner says to merge; real-kassa check pending the first deploy".

- [ ] **Step 2: Full gate**

```bash
git status --porcelain
make lint typecheck test
cd apps/api && uv run pytest --cov=csmarket.modules.wallet --cov=csmarket.modules.payments --cov=csmarket.modules.click --cov=csmarket.modules.payme --cov=csmarket.modules.uzum --cov-report=term -q -n auto && cd ../..
cd apps/api && uv run python -m csmarket.scripts.export_openapi /tmp/o.json && cd ../.. && diff -q /tmp/o.json docs/api/openapi.json
docker compose build && docker compose up -d && docker compose exec api alembic upgrade head && make seed-skins
make test-e2e && docker compose down
git status --porcelain
```

Expected: all green; the five money modules ≥ 95 % coverage each (AGENTS §9 — report the numbers; below 95 % is a finding, add tests); no OpenAPI drift.

- [ ] **Step 3: Commit**

```bash
npx prettier --check .
git add -A && git commit -m "docs: ADR-0006 wallet, payments and top-ups; kassa runbooks and flows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

**Spec coverage (§15 M3: "fx, wallet, payments + Click/Payme/Uzum, top-ups; admin users/wallet/payments — a balance is topped up through a real kassa"):** `fx` — built in M2 (owner decision D1 of M2); order snapshots wait for M4 orders. `wallet` (§5 accounts + ledger, ruling R1) → T2; `payments` (§5 columns + FSM, R3–R6) → T3; top-ups (§5 `wallet_topups`, §7.9, min 1 000 + owner max 10 000 000) → T3–T4; Click/Payme/Uzum (§3.2 twins, §13 signatures before parsing, exempt routes) → T5–T8; numbers (§6) → T1; balance page (§10 `/account/balance`) → T11–T12; admin users (card: Steam, trade link + verdict, balance, orders (M4), ban, `wallet.adjust` with reason) → T9, T13; admin payments (search by number, statuses, webhook logs = kassa transaction rows) → T10, T14; audit log (§10 admin, §13 "admin actions audited") → T9, T10, T14; alerts (§12 "webhook signature failures spike") → T8; hypothesis on the ledger (§14) → T2; each gateway success / retryable failure / idempotent re-call (§14) → T5–T7 ported suites; e2e (§14 "buy from balance / via mocked acquirer" are M4; M3 adds top-up via the test kassa) → T15; real-kassa "done when" → R14 + runbook. Not in M3 by ruling R12: pay-from-balance, admin settle, provider kill-switch, admin card refunds.

**Placeholder scan:** no TBD/TODO. Port steps name every YuPay source file, the tests to port and the deltas; new code (numbers, FSM, hooks, top-ups, tests) is written out.

**Type consistency:** `Payable` (T3) used by T4–T7; `ensure_attempt/mark_pending/settle/reverse/cancel_pending` (T3) used by T4–T7 with the same keyword names; `AlreadyPaidError`/`TopupSpentError` mapped per kassa in T5–T7; `credit_topup/reverse_topup` keys `topup:{topup_id}` / `topup_reversal:{topup_id}` (T3) match the wallet README (T2); `admin_adjust` key `admin_adjust:<key>` (T9); `TopupOut`/`EntryOut` (T4) ↔ `lib/balance.ts` types (T11); `AdminUserCard`/`AdminPaymentDetail`/`AuditRow` (T9–T10) ↔ admin `api.ts` types (T13–T14); intent URL R10 path `/account/balance/topups/{number}` = the T12 page route; `topup_expiry_minutes` (T1) used by T4; scheduler first runs 140 (topup expiry), 160 (click), 180 (payme), 200 (uzum) — all ≥ 15 s from 20/60/120/300.

**Review Focus → tests:** 1 → T3 `test_settle_twice_credits_once`, `test_a_second_attempt_on_a_paid_topup_is_refused`; T5 `test_a_second_prepare_on_a_paid_topup_is_minus4`, `test_a_complete_after_the_topup_was_paid_elsewhere_is_minus4`; T6 `test_perform_after_paid_elsewhere_is_31008`; T4 `test_dev_pay_credits_once`. 2 → T3 `test_reverse_refused_when_spent`; T6 `test_cancel_performed_spent_topup_is_31007`; T7 `test_reverse_spent_topup_is_10017`. 3 → T4 `test_expired_topup_is_not_payable`, `test_sweep_keeps_a_topup_with_a_kassa_transaction`. 4 → T5 `test_amount_in_soum_not_tiyin`, T6 `test_amount_in_tiyin`, T7 wrong-amount 10011 + `test_check_returns_soum_value`. 5 → T9 `test_clawback_below_zero_is_409`, `test_replayed_adjust_posts_once`, replayed ban one audit row.
