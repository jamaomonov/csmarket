# USD Wallet (public API, plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a user a second, USD wallet that an admin switches on; the user converts soʻm into
it at the site rate, an admin credits or debits it by hand, and the site and the admin show it.

**Architecture:** The double-entry ledger (`modules/wallet`) gains a currency per account: new
account kinds carry USD in integer milli-USD units (1000 = $1) in the same `Numeric(14,0)`
column, and `service.post` balances debits and credits **per currency**. A conversion is one
transaction with two balanced pairs (UZS and USD) through two house FX accounts. The route
takes the rate from `fx.api.current_usd_uzs` (CBU × 1.01); `wallet` stays domain-pure.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest + testcontainers +
hypothesis; Next.js 15 storefront (next-intl, TanStack Query); Vite admin SPA.

**Spec:** `docs/superpowers/specs/2026-10-09-public-api-design.md` (§2.2, §3, §9, §12 A). Read it
first. AGENTS.md is binding.

## Global Constraints

- USD amounts are integer **milli-USD units** (1000 = $1) inside; on the wire a string with three
  decimals (`"12.345"`). Never floats.
- UZS amounts stay whole soʻm; existing UZS behaviour must not change (every existing wallet
  test keeps passing unchanged unless a step says otherwise).
- Conversion rate = `fx.api.current_usd_uzs(...)` (CBU × (1 + `fx_uplift_pct`), ADR-0011);
  `usd_units = floor(amount_uzs × 1000 / rate)`. No USD → soʻm.
- Only an admin switches the USD wallet on (`users.usd_wallet_enabled`).
- Every state-changing endpoint takes `Idempotency-Key` (16..160 chars).
- ru / uz / en strings for every new user-facing text (`packages/i18n/locales/*/web.json`,
  admin strings where the admin keeps them). Uzbek in Latin with ʻ.
- mypy --strict, ruff, eslint `--max-warnings 0`, prettier **from the repo root only**.
- `wallet` coverage ≥ 95 % (`scripts/check-module-coverage.py`).
- Tests: run only the files you touch (`cd apps/api && uv run pytest <files> -p no:randomly
-n 0`; web: `cd apps/web && npx vitest run <paths>`); full suites run on CI.
- Commit after each task; never push.

## Review Focus

1. A transaction mixing currencies that balances overall but not per currency (e.g. D 1000 UZS /
   C 1000 USD-units) must be refused — Task 1 pins it.
2. A conversion whose result rounds to 0 milli-USD (a tiny soʻm amount) must be refused, not
   booked as a zero leg — Task 3 pins it.
3. The same `Idempotency-Key` sent twice with a **different** amount must be 409
   `idempotency_mismatch`, not a silent replay of the first conversion — Task 3 pins it.
4. Two conversions at once must not overdraw the soʻm balance (lock before the balance check) —
   Task 3 pins it.
5. A user without the USD wallet must not be able to convert, and `GET /wallet` must not show a
   USD card for them — Task 4 pins it.

---

### Task 1: Ledger currency per account

**Files:**

- Create: `apps/api/migrations/versions/0026_wallet_currency.py`
- Modify: `apps/api/src/csmarket/modules/wallet/models.py`
- Modify: `apps/api/src/csmarket/modules/wallet/service.py`
- Modify: `apps/api/src/csmarket/modules/users/models.py` (the switch column)
- Modify: `docs/superpowers/specs/2026-10-09-public-api-design.md` §3 (leg directions, see Ruling)
- Test: `apps/api/tests/unit/test_wallet_currency.py`,
  `apps/api/tests/integration/test_wallet_currency.py`

**Interfaces:**

- Produces: `KIND_CURRENCY: dict[str, Currency]`, `Currency = Literal["UZS", "USD"]` in
  `wallet/service.py`; `WalletAccount.currency: str`; `User.usd_wallet_enabled: bool`; new kinds
  `user_wallet_usd`, `house_payments_received_usd`, `house_adjustments_usd`, `house_fx_uzs`,
  `house_fx_usd`; new tx kinds `fx_convert`, `admin_adjust_usd`.

**Ruling (record in the spec):** spec §3 writes the conversion as "D user_wallet / C house_fx" —
that would _raise_ the soʻm balance. The correct legs are UZS: **C** `user_wallet` / **D**
`house_fx_uzs`; USD: **D** `user_wallet_usd` / **C** `house_fx_usd`. One `house_fx` account
cannot hold two currencies under the `(owner_type, owner_id, kind)` key, so there are two kinds.
Edit §3 to say so.

- [ ] **Step 1: Write the failing unit tests** (`tests/unit/test_wallet_currency.py`)

```python
"""The ledger balances per currency (spec 2026-10-09 §3)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.wallet.service import KIND_CURRENCY, NORMAL_SIDE, Leg, _validate_legs
from hypothesis import given
from hypothesis import strategies as st

UZS = {"a": "UZS", "b": "UZS"}
MIXED = {"a": "UZS", "b": "USD", "c": "UZS", "d": "USD"}


def test_every_kind_has_a_currency_and_a_normal_side() -> None:
    assert set(KIND_CURRENCY) == set(NORMAL_SIDE)
    assert KIND_CURRENCY["user_wallet"] == "UZS"
    assert KIND_CURRENCY["user_wallet_usd"] == "USD"
    assert {KIND_CURRENCY["house_fx_uzs"], KIND_CURRENCY["house_fx_usd"]} == {"UZS", "USD"}


def test_a_pair_per_currency_balances() -> None:
    legs = [
        Leg("a", "C", Decimal(12_651)),
        Leg("c", "D", Decimal(12_651)),
        Leg("b", "D", Decimal(1000)),
        Leg("d", "C", Decimal(1000)),
    ]
    _validate_legs(legs, MIXED)


def test_balanced_overall_but_not_per_currency_is_refused() -> None:
    legs = [Leg("a", "D", Decimal(1000)), Leg("b", "C", Decimal(1000))]
    with pytest.raises(ValidationError, match="per currency"):
        _validate_legs(legs, {"a": "UZS", "b": "USD"})


def test_without_currencies_the_old_single_pool_rule_holds() -> None:
    _validate_legs([Leg("a", "D", Decimal(5)), Leg("b", "C", Decimal(5))])
    with pytest.raises(ValidationError):
        _validate_legs([Leg("a", "D", Decimal(5)), Leg("b", "C", Decimal(4))], UZS)


@given(
    uzs=st.integers(min_value=1, max_value=10**12),
    usd=st.integers(min_value=1, max_value=10**12),
)
def test_any_two_balanced_pairs_pass(uzs: int, usd: int) -> None:
    legs = [
        Leg("a", "C", Decimal(uzs)),
        Leg("c", "D", Decimal(uzs)),
        Leg("b", "D", Decimal(usd)),
        Leg("d", "C", Decimal(usd)),
    ]
    _validate_legs(legs, MIXED)
```

- [ ] **Step 2: Run them — expect FAIL** (`ImportError: KIND_CURRENCY`)

Run: `cd apps/api && uv run pytest tests/unit/test_wallet_currency.py -p no:randomly -n 0`

- [ ] **Step 3: Implement in `service.py`**

Add after `NORMAL_SIDE` (and add the five new kinds to `NORMAL_SIDE` itself):

```python
    # The same roles in milli-USD (1000 = $1), spec 2026-10-09 §3.
    "user_wallet_usd": "D",
    "house_payments_received_usd": "D",
    "house_adjustments_usd": "D",
    # A conversion's counter-accounts: soʻm in (D-normal), dollars out (C-normal).
    "house_fx_uzs": "D",
    "house_fx_usd": "C",
}

Currency = Literal["UZS", "USD"]

#: The currency of each account kind; amounts are whole soʻm or milli-USD units.
KIND_CURRENCY: dict[str, Currency] = {
    kind: ("USD" if kind.endswith("_usd") else "UZS") for kind in NORMAL_SIDE
}
```

Add `"fx_convert"` and `"admin_adjust_usd"` to `TX_KINDS`.

Replace `_validate_legs` with:

```python
def _validate_legs(legs: list[Leg], currencies: Mapping[str, str] | None = None) -> None:
    """At least two legs, each valid, and ``SUM(D) == SUM(C)`` in every currency.

    ``currencies`` maps a leg's account id to its currency; without it all legs are one pool
    (the unit tests' shape). A transaction may carry two currencies only as pairs that each
    balance on their own (a conversion).
    """
    if len(legs) < 2:
        raise ValidationError("a wallet transaction needs at least 2 legs")
    sums: dict[tuple[str, str], Decimal] = {}
    for leg in legs:
        _validate_leg(leg)
        cur = currencies.get(leg.account_id, "UZS") if currencies else "UZS"
        sums[(cur, leg.direction)] = sums.get((cur, leg.direction), Decimal(0)) + leg.amount
    for cur in {c for c, _ in sums}:
        debit, credit = sums.get((cur, "D"), Decimal(0)), sums.get((cur, "C"), Decimal(0))
        if debit != credit:
            raise ValidationError(
                "ledger invariant break: SUM(D) != SUM(C) per currency",
                currency=cur,
                debit=str(debit),
                credit=str(credit),
            )
```

(`from collections.abc import Mapping`.) Change the message of `_validate_leg`'s whole-number
check to `"ledger amounts are whole units (soʻm or milli-USD)"`.

Make `_check_accounts` return `dict[str, str]` (account id → `account.currency`) and in `post`
call `_check_accounts` **before** validation, then `_validate_legs(legs, currencies)`:

```python
    if kind not in TX_KINDS:
        raise ValidationError("unknown wallet transaction kind", kind=kind)
    for leg in legs:
        _validate_leg(leg)
    currencies = await _check_accounts(db, legs)
    _validate_legs(legs, currencies)
```

In `ensure_account`, create with `currency=KIND_CURRENCY[kind]`.

- [ ] **Step 4: Model + migration**

`models.py`: add the five kinds to `ACCOUNT_KINDS`; `CURRENCIES = ("UZS", "USD")`; on
`WalletAccount`:

```python
    #: ``UZS`` (whole soʻm) or ``USD`` (milli-USD units); fixed by the kind.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'UZS'"))
```

and `CheckConstraint(f"currency IN {_in(CURRENCIES)}", name="currency")`. Update the module
docstring ("UZS only" → per-currency). `users/models.py`:

```python
    #: An admin switched the USD wallet on (spec 2026-10-09 §2.2).
    usd_wallet_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
```

Migration `0026_wallet_currency.py` (revises `0025_order_float_seed`, style of 0025): add
`wallet_accounts.currency` `String(3)` not null default `'UZS'`; recreate the CHECKs
`ck_wallet_accounts_kind` (all 10 kinds) and add `ck_wallet_accounts_currency`; add
`users.usd_wallet_enabled` `Boolean` not null default `false`. Downgrade reverses (refuse with a
clear `RuntimeError` if any `*_usd` / `house_fx_*` account exists).

- [ ] **Step 5: Integration test** (`tests/integration/test_wallet_currency.py`)

```python
"""Accounts carry their currency; a cross-currency leg pair is refused at post()."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.wallet.api import Leg, ensure_account, post
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user


async def test_accounts_get_the_currency_of_their_kind(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    uzs = await ensure_account(db_session, owner_type="user", owner_id=user.id, kind="user_wallet")
    usd = await ensure_account(
        db_session, owner_type="user", owner_id=user.id, kind="user_wallet_usd"
    )
    assert (uzs.currency, usd.currency) == ("UZS", "USD")


async def test_post_refuses_a_soum_debit_against_a_dollar_credit(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    uzs = await ensure_account(db_session, owner_type="user", owner_id=user.id, kind="user_wallet")
    usd = await ensure_account(
        db_session, owner_type="user", owner_id=user.id, kind="user_wallet_usd"
    )
    with pytest.raises(ValidationError, match="per currency"):
        await post(
            db_session,
            kind="admin_adjust",
            legs=[Leg(uzs.id, "D", Decimal(1000)), Leg(usd.id, "C", Decimal(1000))],
            idempotency_key="mixed-currency-test-0001",
        )
```

Also add `usd_wallet_enabled` to `tests/integration/test_migrations.py`'s expectations if that
file lists columns (grep it).

- [ ] **Step 6: Run** — `uv run pytest tests/unit/test_wallet_currency.py
tests/integration/test_wallet_currency.py tests/integration/test_wallet_ledger.py
tests/integration/test_wallet_ledger_props.py tests/integration/test_migrations.py -p no:randomly -n 0`
      Expected: PASS. `uv run mypy src/csmarket/modules/wallet` clean.

- [ ] **Step 7: Commit** — `feat(api/wallet): accounts carry a currency, the ledger balances per currency`

---

### Task 2: USD accounts, balances, admin credit / debit

**Files:**

- Modify: `apps/api/src/csmarket/modules/wallet/service.py` (USD account + balance helpers)
- Modify: `apps/api/src/csmarket/modules/wallet/adjust.py` (generalise; `admin_adjust_usd`)
- Modify: `apps/api/src/csmarket/modules/wallet/entries.py` (entries per currency)
- Modify: `apps/api/src/csmarket/modules/wallet/api.py` (export)
- Modify: `apps/api/src/csmarket/core/money.py` (`wire_usd`)
- Test: `apps/api/tests/integration/test_wallet_usd_adjust.py`, `apps/api/tests/unit/test_money_usd.py`

**Interfaces:**

- Consumes: Task 1 kinds and `KIND_CURRENCY`.
- Produces:
  - `user_usd_account(db, user_id: str, *, lock: bool = False) -> WalletAccount`
  - `user_usd_balance(db, user_id: str) -> Decimal` (milli-USD units; 0 without an account)
  - `admin_adjust_usd(db, *, user_id, amount: Decimal, reason, admin_id, idempotency_key) -> WalletTransaction`
    (units; `ADMIN_ADJUST_USD_MAX = Decimal(100_000_000)` = $100 000)
  - `entries_for_user(db, user_id, *, cursor, limit, entry_type, currency: Currency = "UZS")`,
    `entries_for_admin(db, user_id, *, limit, currency: Currency = "UZS")`
  - `core.money.wire_usd(units: Decimal | int) -> str` — `12345 → "12.345"`, `-500 → "-0.500"`

- [ ] **Step 1: Failing tests**

`tests/unit/test_money_usd.py`:

```python
from decimal import Decimal

from csmarket.core.money import wire_usd


def test_wire_usd_three_decimals() -> None:
    assert wire_usd(12_345) == "12.345"
    assert wire_usd(Decimal(1000)) == "1.000"
    assert wire_usd(5) == "0.005"
    assert wire_usd(0) == "0.000"
    assert wire_usd(-500) == "-0.500"
```

`tests/integration/test_wallet_usd_adjust.py` — mirror `test_wallet_admin_adjust.py`:

```python
"""``admin_adjust_usd``: credit, clawback, never below zero, one post per key; the soʻm wallet
is untouched."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust_usd,
    entries_for_admin,
    user_balance,
    user_usd_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

ADMIN_ID = "00000000-0000-4000-8000-000000000001"


async def _adjust(db: AsyncSession, user_id: str, units: int, key: str) -> None:
    await admin_adjust_usd(
        db, user_id=user_id, amount=Decimal(units), reason="yupay prepay",
        admin_id=ADMIN_ID, idempotency_key=key,
    )


async def test_credit_then_clawback_in_dollars(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 250_000, "usd-adjust-credit-0001")
    await _adjust(db_session, user.id, -50_000, "usd-adjust-claw-00001")
    await db_session.commit()
    assert await user_usd_balance(db_session, user.id) == Decimal(200_000)
    assert await user_balance(db_session, user.id) == Decimal(0)
    lines = await entries_for_admin(db_session, user.id, limit=10, currency="USD")
    assert [(e.kind, e.amount) for e in lines] == [
        ("admin_adjust_usd", Decimal(-50_000)),
        ("admin_adjust_usd", Decimal(250_000)),
    ]


async def test_clawback_below_zero_is_refused(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(InsufficientBalanceError):
        await _adjust(db_session, user.id, -1, "usd-adjust-claw-00002")


async def test_a_key_reused_for_another_amount_is_409(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 1000, "usd-adjust-same-key-01")
    with pytest.raises(ConflictError):
        await _adjust(db_session, user.id, 2000, "usd-adjust-same-key-01")
```

- [ ] **Step 2: Run — expect FAIL** (import errors).

- [ ] **Step 3: Implement**

`core/money.py`:

```python
def wire_usd(units: Decimal | int) -> str:
    """Milli-USD units as a dollar string with three decimals: ``12345`` → ``"12.345"``."""
    value = (Decimal(units) / 1000).quantize(Decimal("0.001"))
    return format(value, "f")
```

`service.py`: generalise `user_account` into a private `_user_wallet(db, user_id, kind, *, lock)`
and keep `user_account(...)` as `return await _user_wallet(db, user_id, "user_wallet", lock=lock)`;
add `user_usd_account` (kind `user_wallet_usd`) and `user_usd_balance` (as `user_balance`, kind
`user_wallet_usd`).

`adjust.py`: move the body of `admin_adjust` into
`_adjust(db, *, user_id, amount, reason, admin_id, idempotency_key, wallet_kind, house_kind,
tx_kind, key_prefix, maximum)`; `admin_adjust` calls it with
(`user_wallet`, `house_adjustments`, `admin_adjust`, `admin_adjust:`, `ADMIN_ADJUST_MAX`) — its
behaviour and messages unchanged; `admin_adjust_usd` with (`user_wallet_usd`,
`house_adjustments_usd`, `admin_adjust_usd`, `admin_adjust_usd:`, `ADMIN_ADJUST_USD_MAX`).
`_same_adjustment` compares `txn.kind` with the passed `tx_kind`.

`entries.py`: `_user_wallet_id(db, user_id, kind="user_wallet")`; `entries_for_user` /
`entries_for_admin` take `currency: Currency = "UZS"` and pass
`"user_wallet_usd" if currency == "USD" else "user_wallet"`. Export `user_usd_account`,
`user_usd_balance`, `admin_adjust_usd`, `ADMIN_ADJUST_USD_MAX`, `KIND_CURRENCY`, `Currency` from
`api.py`.

- [ ] **Step 4: Run** the two new files + `tests/integration/test_wallet_admin_adjust.py` +
      `tests/integration/test_wallet_routes.py`. Expected: PASS.

- [ ] **Step 5: Commit** — `feat(api/wallet): the USD wallet's account, balance and admin adjustments`

---

### Task 3: Conversion soʻm → USD (service)

**Files:**

- Create: `apps/api/src/csmarket/modules/wallet/convert.py`
- Modify: `apps/api/src/csmarket/modules/wallet/api.py`
- Test: `apps/api/tests/integration/test_wallet_convert.py`

**Interfaces:**

- Consumes: Task 1–2 (`user_account`, `user_usd_account`, `ensure_account`, `post`, `balance`).
- Produces:

```python
@dataclass(frozen=True)
class Conversion:
    transaction_id: str
    amount_uzs: Decimal      # whole soʻm taken
    usd_units: Decimal       # milli-USD credited
    rate: Decimal            # soʻm per dollar used

def usd_units_for(amount_uzs: Decimal, rate: Decimal) -> Decimal: ...
async def convert_to_usd(
    db: AsyncSession, *, user_id: str, amount_uzs: Decimal, rate: Decimal,
    snapshot_id: str, idempotency_key: str,
) -> Conversion: ...
```

- [ ] **Step 1: Failing tests** (`tests/integration/test_wallet_convert.py`)

```python
"""Converting soʻm into the USD wallet (spec 2026-10-09 §3)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust,
    convert_to_usd,
    usd_units_for,
    user_balance,
    user_usd_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_user

RATE = Decimal("12777.01")  # CBU 12650.5 × 1.01
ADMIN = "00000000-0000-4000-8000-000000000001"


def test_units_round_down_to_a_tenth_of_a_cent() -> None:
    # 100 000 / 12 777.01 = 7.82656… $ → 7 826 units
    assert usd_units_for(Decimal(100_000), RATE) == Decimal(7826)
    assert usd_units_for(Decimal(12), RATE) == Decimal(0)


async def _funded(db: AsyncSession, soum: int) -> str:
    user = await make_user(db)
    await admin_adjust(
        db, user_id=user.id, amount=Decimal(soum), reason="seed", admin_id=ADMIN,
        idempotency_key=f"seed-{user.id}",
    )
    await db.commit()
    return user.id


async def _convert(db: AsyncSession, user_id: str, soum: int, key: str):  # type: ignore[no-untyped-def]
    return await convert_to_usd(
        db, user_id=user_id, amount_uzs=Decimal(soum), rate=RATE,
        snapshot_id="00000000-0000-4000-8000-0000000000f1", idempotency_key=key,
    )


async def test_soum_out_dollars_in(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 150_000)
    conv = await _convert(db_session, uid, 100_000, "convert-key-000000001")
    await db_session.commit()
    assert (conv.amount_uzs, conv.usd_units, conv.rate) == (Decimal(100_000), Decimal(7826), RATE)
    assert await user_balance(db_session, uid) == Decimal(50_000)
    assert await user_usd_balance(db_session, uid) == Decimal(7826)


async def test_replay_returns_the_same_conversion(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 150_000)
    first = await _convert(db_session, uid, 100_000, "convert-key-000000002")
    again = await _convert(db_session, uid, 100_000, "convert-key-000000002")
    assert again.transaction_id == first.transaction_id
    assert await user_balance(db_session, uid) == Decimal(50_000)


async def test_same_key_other_amount_is_409(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 150_000)
    await _convert(db_session, uid, 100_000, "convert-key-000000003")
    with pytest.raises(ConflictError, match="Idempotency-Key"):
        await _convert(db_session, uid, 20_000, "convert-key-000000003")


async def test_more_than_the_balance_is_refused(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 50_000)
    with pytest.raises(InsufficientBalanceError):
        await _convert(db_session, uid, 50_001, "convert-key-000000004")


async def test_a_sum_under_one_unit_is_refused(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 50_000)
    with pytest.raises(ValidationError, match="too small"):
        await _convert(db_session, uid, 12, "convert-key-000000005")


async def test_two_at_once_never_overdraw(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    uid = await _funded(db_session, 100_000)

    async def one(key: str) -> bool:
        async with session_factory() as db:
            try:
                await _convert(db, uid, 70_000, key)
                await db.commit()
                return True
            except InsufficientBalanceError:
                return False

    results = await asyncio.gather(one("convert-race-0000001"), one("convert-race-0000002"))
    assert sorted(results) == [False, True]
    assert await user_balance(db_session, uid) == Decimal(30_000)
```

(If `session_factory` is not the fixture name in `tests/integration/conftest.py`, use the one the
existing concurrency tests use — grep `asyncio.gather` under `tests/integration`.)

- [ ] **Step 2: Run — expect FAIL** (import error).

- [ ] **Step 3: Implement `wallet/convert.py`**

```python
"""Soʻm → USD: one transaction, two balanced pairs (spec 2026-10-09 §3).

UZS: C ``user_wallet`` / D ``house_fx_uzs``; USD: D ``user_wallet_usd`` / C ``house_fx_usd``.
The rate comes from the caller (``fx.api.current_usd_uzs``): ``wallet`` imports no ``fx``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.wallet.models import WalletTransaction
from csmarket.modules.wallet.service import (
    InsufficientBalanceError,
    Leg,
    Reference,
    _transaction_by_key,
    balance,
    ensure_account,
    post,
    user_account,
    user_usd_account,
)

#: Largest single conversion, whole soʻm.
CONVERT_MAX_UZS = Decimal(100_000_000)


@dataclass(frozen=True)
class Conversion:
    """A booked conversion."""

    transaction_id: str
    amount_uzs: Decimal
    usd_units: Decimal
    rate: Decimal


def usd_units_for(amount_uzs: Decimal, rate: Decimal) -> Decimal:
    """Milli-USD bought by ``amount_uzs`` at ``rate`` soʻm per dollar, rounded down."""
    return (amount_uzs * 1000 / rate).to_integral_value(rounding=ROUND_FLOOR)


def _of(txn: WalletTransaction) -> Conversion:
    meta = txn.extra_metadata
    return Conversion(
        transaction_id=txn.id,
        amount_uzs=Decimal(meta["amount_uzs"]),
        usd_units=Decimal(meta["usd_units"]),
        rate=Decimal(meta["rate"]),
    )


def _same(txn: WalletTransaction, user_id: str, amount_uzs: Decimal) -> Conversion:
    meta = txn.extra_metadata
    if (
        txn.kind != "fx_convert"
        or meta.get("user_id") != user_id
        or Decimal(meta.get("amount_uzs", "-1")) != amount_uzs
    ):
        raise ConflictError(
            "this Idempotency-Key was used for another conversion", code="idempotency_mismatch"
        )
    return _of(txn)


async def convert_to_usd(
    db: AsyncSession,
    *,
    user_id: str,
    amount_uzs: Decimal,
    rate: Decimal,
    snapshot_id: str,
    idempotency_key: str,
) -> Conversion:
    """Take ``amount_uzs`` from the soʻm wallet and credit the dollars it buys at ``rate``.

    The soʻm wallet is locked ``FOR UPDATE`` before the key lookup and the balance check, so two
    conversions cannot both pass the check. A replay of the same key and amount returns the
    booked conversion; the same key with another amount or user is 409. Flushes, never commits.

    Raises:
        ValidationError: ``code="convert_amount"`` — not a positive whole soʻm within
            ``CONVERT_MAX_UZS``, or it buys less than one milli-USD ("too small").
        InsufficientBalanceError: ``code="balance_too_low"``.
        ConflictError: ``code="idempotency_mismatch"``.
    """
    if (
        not amount_uzs.is_finite()
        or amount_uzs <= 0
        or amount_uzs != amount_uzs.to_integral_value()
        or amount_uzs > CONVERT_MAX_UZS
    ):
        raise ValidationError("amount must be a positive whole soʻm", code="convert_amount")
    key = f"fx_convert:{idempotency_key}"
    wallet = await user_account(db, user_id, lock=True)
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return _same(existing, user_id, amount_uzs)
    units = usd_units_for(amount_uzs, rate)
    if units < 1:
        raise ValidationError("the amount is too small to convert", code="convert_amount")
    if await balance(db, wallet.id) < amount_uzs:
        raise InsufficientBalanceError("the balance does not cover it", code="balance_too_low")
    usd = await user_usd_account(db, user_id)
    fx_uzs = await ensure_account(db, owner_type="house", owner_id="house", kind="house_fx_uzs")
    fx_usd = await ensure_account(db, owner_type="house", owner_id="house", kind="house_fx_usd")
    txn = await post(
        db,
        kind="fx_convert",
        legs=[
            Leg(wallet.id, "C", amount_uzs),
            Leg(fx_uzs.id, "D", amount_uzs),
            Leg(usd.id, "D", units),
            Leg(fx_usd.id, "C", units),
        ],
        idempotency_key=key,
        reference=Reference(type="fx_snapshot", id=snapshot_id),
        actor=f"user:{user_id}",
        metadata={
            "user_id": user_id,
            "amount_uzs": str(amount_uzs),
            "usd_units": str(units),
            "rate": str(rate),
        },
    )
    return _same(txn, user_id, amount_uzs)
```

Export `Conversion`, `convert_to_usd`, `usd_units_for`, `CONVERT_MAX_UZS` from `api.py`.
`user_id` in metadata is an internal uuid (not PII). Check `entries._NUMBERED` ignores the
`fx_snapshot` reference type (it does: only topup / order / sale are numbered).

- [ ] **Step 4: Run** — `uv run pytest tests/integration/test_wallet_convert.py -p no:randomly -n 0`.
      Expected: PASS.

- [ ] **Step 5: Commit** — `feat(api/wallet): convert soʻm into the USD wallet`

---

### Task 4: Customer API — `GET /wallet` USD block, `POST /wallet/convert`, USD history

**Files:**

- Modify: `apps/api/src/csmarket/modules/wallet/routes.py`, `schemas.py`
- Test: `apps/api/tests/integration/test_wallet_usd_routes.py`

**Interfaces:**

- Consumes: Tasks 1–3; `fx.api.current_usd_uzs(db, redis, max_age_days=settings.fx_max_age_days)`
  (returns `UsdUzs | None` with `.rate`, `.snapshot_id`); `core.idempotency.require_idempotency_key`;
  `get_redis`, `get_settings` as `orders/routes.py` uses them.
- Produces (wire):
  - `BalanceOut` gains `usd: UsdWalletOut | None`; `UsdWalletOut {balance_usd: str, rate_uzs: str | None}`
    (`rate_uzs` = the conversion rate now, soʻm per dollar with 2 decimals; `null` without a rate).
    `usd` is `null` unless `user.usd_wallet_enabled`.
  - `POST /wallet/convert {amount_uzs: int (1000..100 000 000)}` + `Idempotency-Key` →
    `ConvertOut {amount_uzs: str, amount_usd: str, rate_uzs: str, balance_uzs: str, balance_usd: str}`
    (201; a replay 200). Errors: 403 `usd_wallet_disabled` (`ForbiddenError`), 409
    `balance_too_low`, 422 `convert_amount`, 503 `rate_unavailable`.
  - `GET /wallet/entries?currency=usd` — USD lines, `EntryOut` gains `currency: "UZS" | "USD"` and
    `amount` stays signed (`amount_uzs` keeps its name for UZS lines; add `amount_usd: str | None`
    for USD lines, `amount_uzs` `"0"` there — **Ruling:** keep `amount_uzs` required so the
    existing client does not break; USD lines fill `amount_usd`).
  - `EntryOut.kind` Literal gains `fx_convert`, `admin_adjust_usd`.

- [ ] **Step 1: Failing tests** — in `tests/integration/test_wallet_usd_routes.py`, using the
      fixtures of `test_wallet_routes.py` (copy its client / auth-header setup and the way it seeds an
      FX snapshot — grep `FxSnapshot` in `tests/integration`):

```python
async def test_balance_has_no_usd_block_until_an_admin_switches_it_on(...) -> None:
    body = (await client.get("/api/v1/wallet", headers=h)).json()
    assert body["usd"] is None


async def test_convert_moves_soum_into_dollars(...) -> None:
    # user.usd_wallet_enabled = True; balance 150 000 soʻm; FX snapshot 12650.5, uplift 1 %
    r = await client.post(
        "/api/v1/wallet/convert", json={"amount_uzs": 100_000},
        headers={**h, "Idempotency-Key": "web-convert-000000000001"},
    )
    assert r.status_code == 201
    assert r.json() == {
        "amount_uzs": "100000", "amount_usd": "7.826", "rate_uzs": "12777.01",
        "balance_uzs": "50000", "balance_usd": "7.826",
    }
    again = await client.post(... same key and body ...)
    assert again.status_code == 200 and again.json() == r.json()
    usd = (await client.get("/api/v1/wallet", headers=h)).json()["usd"]
    assert usd == {"balance_usd": "7.826", "rate_uzs": "12777.01"}
    lines = (await client.get("/api/v1/wallet/entries?currency=usd", headers=h)).json()["items"]
    assert [(e["kind"], e["amount_usd"]) for e in lines] == [("fx_convert", "+7.826")]


async def test_convert_without_the_usd_wallet_is_403(...) -> None:
    assert r.status_code == 403 and r.json()["code"] == "usd_wallet_disabled"


async def test_convert_without_a_rate_is_503(...) -> None: ...      # no snapshot seeded
async def test_convert_more_than_the_balance_is_409(...) -> None: ...  # code balance_too_low
async def test_convert_needs_an_idempotency_key(...) -> None: ...   # 422/400 as other routes
```

Write each body fully, following `test_wallet_routes.py`'s style (exact client fixture names
there).

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — in `routes.py`:

```python
@router.post(
    "/convert", response_model=ConvertOut, status_code=201, summary="Convert soʻm into dollars"
)
async def convert(
    body: ConvertIn,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConvertOut:
    """Soʻm → the USD wallet at the site rate (CBU × 1.01). Needs the USD wallet switched on.

    A replayed key with the same amount answers 200 with the same conversion.
    """
    key = require_idempotency_key(idempotency_key)
    if not user.usd_wallet_enabled:
        raise ForbiddenError("the USD wallet is not switched on", code="usd_wallet_disabled")
    settings = get_settings()
    rate = await current_usd_uzs(db, get_redis(), max_age_days=settings.fx_max_age_days)
    if rate is None:
        raise UpstreamUnavailableError("no soʻm rate", code="rate_unavailable")
    before = await _key_used(db, key)  # True if fx_convert:<key> already exists
    conv = await convert_to_usd(
        db, user_id=user.id, amount_uzs=Decimal(body.amount_uzs), rate=rate.rate,
        snapshot_id=rate.snapshot_id, idempotency_key=f"{user.id}:{key}",
    )
    await db.commit()
    if before:
        response.status_code = 200
    return ConvertOut.of(conv, uzs=await user_balance(db, user.id),
                         usd=await user_usd_balance(db, user.id))
```

(`ConvertIn` with `amount_uzs: Annotated[int, Field(strict=True, ge=1000, le=100_000_000)]`,
`model_config = ConfigDict(extra="forbid")`. Check how `RateUnavailableError` is defined in
`orders/checkout.py` and reuse it if it lives in a shared place; it must answer 503 with
`code="rate_unavailable"`. Namespacing the ledger key with the user id keeps two users' keys
apart. `_key_used` is a small helper over `WalletTransaction.idempotency_key`; put it in
`convert.py` as `conversion_booked(db, key) -> bool` and export it.)

`get_balance` returns `BalanceOut.of(uzs, usd=...)` where `usd` is built only when
`user.usd_wallet_enabled` (rate from `current_usd_uzs`, `None` tolerated). `get_entries` takes
`currency: Literal["uzs", "usd"] = "uzs"`.

- [ ] **Step 4: Run** — new file + `tests/integration/test_wallet_routes.py`. Expected: PASS.
      `make gen-api` (from the repo root) and commit `docs/api/openapi.json`.

- [ ] **Step 5: Commit** — `feat(api/wallet): the USD block on /wallet, conversion and USD history`

---

### Task 5: Admin — switch the USD wallet, credit / debit it

**Files:**

- Modify: `apps/api/src/csmarket/modules/admin/users_routes.py`, `users_service.py`,
  `users_schemas.py`
- Modify: `apps/admin/src/features/users/UserCard.tsx`, `AdjustForm.tsx`, `api.ts`, `labels.ts`
  (+ their tests)
- Test: `apps/api/tests/integration/test_admin_users_usd.py`

**Interfaces:**

- Consumes: `admin_adjust_usd`, `user_usd_balance`, `entries_for_admin(..., currency="USD")`.
- Produces (wire):
  - `AdminUserCard` gains `usd_wallet_enabled: bool`, `balance_usd: str`, `usd_entries: list[AdminEntryOut]`
    (latest 20; `AdminEntryOut` amounts for USD lines in dollars — add `currency` to it).
  - `PUT /admin/users/{id}/usd-wallet {enabled: bool, reason}` + key → `AdminUserCard`; audited
    `wallet.usd_switch` `{enabled, reason}`. Switching off with a non-zero USD balance is allowed
    (the money stays; conversion and API purchases stop) — say so in the docstring.
  - `POST /admin/users/{id}/wallet/adjust-usd {amount_usd: str (e.g. "250.000", non-zero,
|x| ≤ 100000, at most 3 decimals), reason}` + key → `AdminUserCard`; audited
    `wallet.adjust_usd` `{amount_usd, reason}`; 409 `balance_too_low` on a clawback below zero.

- [ ] **Step 1: Failing tests** (`test_admin_users_usd.py`, fixtures as `test_admin_users.py`):
      switch on → card `usd_wallet_enabled` true and audit row `wallet.usd_switch`; credit
      `"250.000"` → `balance_usd == "250.000"`, `usd_entries[0].kind == "admin_adjust_usd"`; clawback
      `"-300.000"` → 409 `balance_too_low`; `"1.2345"` → 422; replay with the same key → same card;
      a non-admin → 403.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** following `adjust_balance` / `svc.adjust` exactly (replay scope
      `admin.users.adjust_usd`, `admin.users.usd_switch`); parse `amount_usd` with a Pydantic
      validator into units (`Decimal(s) * 1000`, must be integral). `user_card` fills the new fields.

- [ ] **Step 4: Admin SPA** — `UserCard.tsx`: a «USD-кошелёк» block: a switch (with a reason
      prompt, like the ban dialog), the USD balance, the last USD lines; `AdjustForm.tsx`: a currency
      toggle (soʻm / USD) posting to the right endpoint; `labels.ts`: `fx_convert` «Перевод в USD»,
      `admin_adjust_usd` «Корректировка USD». Update `UserCard.test.tsx` / `fixtures.tsx` for the new
      fields; add a test that the USD block shows and the switch calls `PUT …/usd-wallet`.

- [ ] **Step 5: Run** — the API test file, `cd apps/admin && npx vitest run src/features/users`,
      eslint, tsc. `make gen-api`.

- [ ] **Step 6: Commit** — `feat(admin/users): switch the USD wallet and adjust it`

---

### Task 6: Storefront — the USD card and the conversion

**Files:**

- Create: `apps/web/src/components/balance/UsdWalletCard.tsx` (+ `.test.tsx`)
- Modify: `apps/web/src/components/balance/BalanceView.tsx`, `EntriesList.tsx` (labels),
  `apps/web/src/lib/balance.ts`
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json`

**Interfaces:**

- Consumes (wire, Task 4): `GET /wallet` `usd: {balance_usd, rate_uzs} | null`;
  `POST /wallet/convert`.
- Produces: `lib/balance.ts` — `UsdWallet` type, `convertToUsd(amountUzs: number, key: string): Promise<ConvertOut>`,
  `EntryKind` gains `fx_convert`, `admin_adjust_usd`.

- [ ] **Step 1: Failing test** (`UsdWalletCard.test.tsx`): with `usd = {balance_usd: "7.826",
rate_uzs: "12777.01"}` it shows «$7.826»; typing `100000` shows «≈ $7.826 по курсу 12 777,01»;
      submitting calls `convertToUsd(100000, <key ≥ 16 chars>)` once and then re-reads the balance
      (`BALANCE_KEY` invalidated); a 409 `balance_too_low` shows «Не хватает денег на балансе»; with
      `rate_uzs: null` the form is disabled with «Курс сейчас недоступен».

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**
  - `UsdWalletCard` (client component): title «USD-кошелёк», the balance in dollars
    (`$` + `balance_usd`), a one-line hint «Для покупок через API», an amount input in soʻm with
    the live preview (`floor(amount*1000/rate)/1000`, display only — the server decides), a
    «Перевести» button; one idempotency key per submitted form (`crypto.randomUUID()`), reset after
    success.
  - `BalanceView`: render `<UsdWalletCard>` under the soʻm card when `balance.data.usd` is not null.
  - `EntriesList`: labels for `fx_convert` («Перевод в USD») and `admin_adjust_usd` (not shown on
    the soʻm history, but typed).
  - i18n (all three): `web.balance.usd.{title, hint, convertLabel, convertSubmit, preview,
rateUnavailable, tooLow, failed, done}` and `web.balance.kind.fx_convert`,
    `web.balance.kind.admin_adjust_usd`. Uzbek: «USD hamyon», «Balansdan oʻtkazish» …

- [ ] **Step 4: Run** — `npx vitest run src/components/balance`, eslint, tsc; prettier from the
      repo root.

- [ ] **Step 5: Commit** — `feat(web/balance): the USD wallet card and conversion from soʻm`

---

### Task 7: Docs

**Files:**

- Create: `docs/decisions/0017-public-api-and-usd-wallet.md` (from `0000-template.md`)
- Modify: `apps/api/src/csmarket/modules/wallet/README.md`, `docs/api/README.md`,
  `docs/product/flows/balance-topup.md`, `docs/architecture/module-map.md` (if it lists wallet
  kinds), `AGENTS.md` §0 (one line: public API spec + plan A in progress), `docs/tech-debt.md`
  if anything was deferred.
- Create: `docs/runbooks/public-api.md` with the first section «USD-кошелёк»: switching it on,
  crediting YuPay by hand, reading `house_fx_*` (what was converted), what to do with a balance
  left when switching off.

- [ ] **Step 1:** Write ADR-0017: context (brief 2026-10-09), decisions §2 of the spec, the
      per-currency ledger, two house FX accounts, consequences (USD reports, no reverse conversion).
- [ ] **Step 2:** Update the docs listed; `docs/api/README.md`: `/wallet` `usd`, `/wallet/convert`
      (auth, Idempotency-Key, errors), `/wallet/entries?currency=usd`, the two admin endpoints.
- [ ] **Step 3:** `npx prettier --write` the changed docs from the repo root; commit
      `docs: ADR-0017, the USD wallet in the wallet README, API notes and runbook`.

---

## Self-review notes

- Spec §3 coverage: currency (T1), kinds (T1), per-currency post (T1), tx kinds (T1), conversion
  rule and refusals (T3–T4), admin credit/debit (T2, T5), `GET /wallet` usd block (T4), history
  with currency (T2, T4). §9 admin switch + adjust (T5). §12 A site card (T6). Docs (T7).
- The public API itself, keys, orders in USD, webhooks: plans B and C.
