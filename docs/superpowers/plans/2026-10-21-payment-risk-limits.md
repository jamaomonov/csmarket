# Payment Risk Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Money that arrives through a kassa above a per-kassa or per-user window limit is held
(not credited, no skin bought) until an admin releases it or records it returned to the card.

**Architecture:** A new module `risk` owns three tables (`kassa_review_limits`,
`user_risk_policies`, `payment_holds`) and a pure read verdict. `payments.hooks.settle` — the
one place every kassa's money lands — asks the verdict under a per-user advisory lock and, on a
hold, puts the top-up or order into a new `held` status instead of crediting / marking paid.
`payments/holds.py` owns the admin decisions (release, returned) and the kassa's own reversal of
a held payment. The admin gets a limits block, a holds page and a user risk block; the
storefront shows «Оплата получена, проверяем платёж».

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest + testcontainers;
Next.js 15 + next-intl (web), Vite + React 19 + TanStack Query (admin).

**Spec:** `docs/superpowers/specs/2026-10-21-payment-risk-limits-design.md`

## Global Constraints

- Owner rulings (spec): over the limit = **held**, never refused; seed Payme, Click, Uzum, P2P at
  **2 000 000 soʻm / 24 h**, on; the user limit counts kassa money over a window, only for a
  user the admin sets it on; **trusted bypasses both**; a failed check **holds**
  (`check_failed`); no new-account / night / country rules; one buyer = one account (no IP).
- Equality passes: `sum <= limit` passes.
- Money is `Decimal`, whole soʻm, `Numeric(14, 0)`; wire money via `core.money.wire_uzs`.
- Never log PII: log order / top-up numbers, providers and amounts only — never a user id
  together with a Steam id, never IP.
- Every state-changing admin route takes `Idempotency-Key` (`required_key`) and replays with
  `replayed` / `remember`; every admin write records an audit row with `record(...)`.
- Constraint names in models and migrations are bare suffixes (`name="status"`), never
  `ck_table_x` (`core/db.py` naming convention).
- Source under `apps/*/src` must not contain `yupay`, `supplier`, `merchant…`, `sku` (the
  `check-no-yupay` guard). YuPay may be named in docs and tests only.
- All buyer-facing strings in ru / uz / en in the same commit; copy: short, outcome-only, no
  reason, no limit, no kassa internals, «вы».
- Python: mypy --strict, Google docstrings, files ≤ 400 LOC, functions ≤ 50 LOC.
- TS: strict, no `any`, exhaustive switches end in `assertNever`.
- `risk` joins the 95 % coverage list.
- Conventional Commits, scope `api/risk`, `api/payments`, `web/balance`, `admin/payments` etc.;
  trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit locally, never push.
- The owner runs full suites on CI; locally run the task's own tests (`uv run pytest <files>`
  from `apps/api`, `pnpm --filter <app> test <file>`).

## Review Focus

1. **A retried kassa callback for a held payment** — Payme `PerformTransaction` repeated, Click
   complete repeated, P2P notification re-delivered: must answer success again, write no second
   hold, credit nothing. (Task 3 test `test_retried_settle_of_held_payment_is_noop`.)
2. **A held top-up or order paid a second time** through another kassa: refused as already paid
   (`payable` reason `paid`). (Task 3 test `test_held_topup_is_not_payable_again`.)
3. **The admin's «Зачислить пользователю» for an unmatched P2P transfer** goes through `settle`
   and must not be held. (Task 3 test `test_credit_received_transfer_is_never_held`.)
4. **Release of an order whose lot sold meanwhile** — must go `paid` and let the worker's normal
   failure path refund to balance; never stay `held`. (Task 5 test
   `test_release_order_marks_paid_and_notifies`.)
5. **Two admins decide the same hold at once** — one wins, the other gets 409 `hold_decided`, no
   double credit. (Task 5 test `test_second_decision_is_refused`.)

---

## File Structure

**Create (API):**

- `apps/api/src/csmarket/modules/risk/__init__.py` — empty docstring.
- `apps/api/src/csmarket/modules/risk/models.py` — `KassaReviewLimit`, `UserRiskPolicy`,
  `PaymentHold`, status tuples.
- `apps/api/src/csmarket/modules/risk/rule.py` — `Verdict`, `verdict(db, payment)`,
  `money_in(db, user_id, hours, provider)`.
- `apps/api/src/csmarket/modules/risk/policy.py` — read / save user policy, `ensure_kassa_allowed`.
- `apps/api/src/csmarket/modules/risk/limits.py` — read / save kassa limits (If-Match).
- `apps/api/src/csmarket/modules/risk/schemas.py` — admin wire models.
- `apps/api/src/csmarket/modules/risk/admin_routes.py` — review-limits and user risk routes.
- `apps/api/src/csmarket/modules/risk/api.py` — the interface other modules import.
- `apps/api/src/csmarket/modules/risk/README.md`
- `apps/api/src/csmarket/modules/payments/holds.py` — hold writes (`hold`), decisions
  (`release`, `mark_returned`), `reverse_held`, list query.
- `apps/api/src/csmarket/modules/payments/holds_routes.py` — `/admin/payments/holds`.
- `apps/api/migrations/versions/0039_payment_risk.py`
- `apps/scheduler/src/csmarket_scheduler/jobs/payment_holds.py` — sets the gauge every 60 s.
- Tests: `apps/api/tests/unit/test_risk_models.py`,
  `apps/api/tests/integration/risk_factory.py`,
  `apps/api/tests/integration/test_risk_rule.py`,
  `apps/api/tests/integration/test_payment_holds_settle.py`,
  `apps/api/tests/integration/test_payment_holds_kassas.py`,
  `apps/api/tests/integration/test_payment_holds_decide.py`,
  `apps/api/tests/integration/test_risk_admin.py`,
  `apps/api/tests/integration/test_kassa_blocked.py`,
  `apps/scheduler/tests/test_payment_holds_job.py`.

**Modify (API):** `payments/models.py` (TOPUP_STATUSES), `orders/models.py` (ORDER_STATUSES,
`ON_REVIEW`), `orders/fsm.py`, `orders/schemas.py` (`OrderStatusOut`),
`admin/payments_schemas.py`, `admin/users_schemas.py`, `payments/schemas.py`,
`payments/payable.py`, `payments/hooks.py`, `payments/topups.py`, `orders/paying.py`,
`core/errors.py`, `core/metrics.py`, `admin/dashboard_schemas.py`, `admin/dashboard_routes.py`,
`api/v1/router.py`, `migrations/env.py`, scheduler `main.py`, worker `consumer.py` model imports,
`tests/unit/test_orders_fsm.py`, `scripts/check-module-coverage.py`.

**Modify (web):** `apps/web/src/lib/balance.ts`, `components/balance/TopupStatus.tsx`,
`lib/orders.ts`, `lib/trade-status.ts`, `components/order/OrderView.tsx`, the top-up / pay error
map, `packages/i18n/locales/{ru,uz,en}/web.json`.

**Modify / create (admin):** `features/payments/api.ts`, `features/payments/FeeSettingsPage.tsx`
(+ `ReviewLimitsBlock.tsx`), `features/payments/HoldsPage.tsx` (new), `features/users/RiskBlock.tsx`
(new), `features/users/UserCard.tsx`, `features/users/api.ts`, `features/users/labels.ts`,
`features/users/TopupStatusChip.tsx`, `features/orders/kinds.ts`, `features/orders/labels.ts`,
`features/payments/api.ts` TopupStatus, `features/dashboard/api.ts`, `app/Layout.tsx`,
`app/router.tsx`.

**Docs:** `docs/decisions/0022-payment-risk-holds.md`, `docs/architecture/module-map.md`,
`docs/architecture/sequence-diagrams/payment-hold.mmd`, `docs/runbooks/payment-held-for-review.md`,
`docs/api/README.md`, `docs/product/flows/payment-hold.md`, `docs/architecture/metrics.md`,
`AGENTS.md` §0 status line, `docs/api/openapi.json` + `packages/api-client` (`make gen-api`).

---

### Task 1: Tables, statuses and the order FSM

**Files:**

- Create: `apps/api/src/csmarket/modules/risk/__init__.py`, `risk/models.py`,
  `apps/api/migrations/versions/0039_payment_risk.py`, `apps/api/tests/unit/test_risk_models.py`
- Modify: `payments/models.py:43`, `orders/models.py:43-58`, `orders/fsm.py:21-40`,
  `orders/schemas.py:13-15`, `admin/payments_schemas.py:69,77-80`, `admin/users_schemas.py:159`,
  `payments/schemas.py:70`, `apps/api/migrations/env.py`, scheduler `main.py` and worker
  `consumer.py` model-import blocks, `apps/api/tests/unit/test_orders_fsm.py:73`

**Interfaces:**

- Produces: `risk.models.KassaReviewLimit`, `UserRiskPolicy`, `PaymentHold`; `HOLD_REASONS =
("kassa_limit", "user_limit", "check_failed")`; `HOLD_DECISIONS = ("released", "returned",
"reversed_by_kassa")`; `HoldReason`, `HoldDecision` Literals; `TOPUP_STATUSES` gains `held`,
  `rejected`; `ORDER_STATUSES` gains `held`; `orders.models.ON_REVIEW = frozenset({"held"})`;
  order FSM `pending→held`, `held→paid|cancelled`.

- [ ] **Step 1: Write the failing unit tests**

`apps/api/tests/unit/test_risk_models.py`:

```python
"""The risk tables and the new statuses (spec 2026-10-21-payment-risk-limits)."""

from csmarket.modules.orders.fsm import TRANSITIONS
from csmarket.modules.orders.models import ON_REVIEW, ORDER_STATUSES
from csmarket.modules.payments.models import TOPUP_STATUSES
from csmarket.modules.risk.models import HOLD_DECISIONS, HOLD_REASONS, PaymentHold


def test_new_statuses_exist() -> None:
    assert "held" in TOPUP_STATUSES and "rejected" in TOPUP_STATUSES
    assert "held" in ORDER_STATUSES
    assert ON_REVIEW == frozenset({"held"})


def test_order_fsm_holds_and_decides() -> None:
    assert "held" in TRANSITIONS["pending"]
    assert TRANSITIONS["held"] == frozenset({"paid", "cancelled"})


def test_hold_vocabulary() -> None:
    assert HOLD_REASONS == ("kassa_limit", "user_limit", "check_failed")
    assert HOLD_DECISIONS == ("released", "returned", "reversed_by_kassa")
    assert PaymentHold.__tablename__ == "payment_holds"
```

In `apps/api/tests/unit/test_orders_fsm.py:73` change the partition assertion to:

```python
    assert {"pending"} | ON_REVIEW | IN_FLIGHT | TERMINAL == set(ORDER_STATUSES)
```

(and add `ON_REVIEW` to that file's import from `csmarket.modules.orders.models`). Reason for the
change, for the commit body: `held` is a fourth class — paid money, nothing bought yet.

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/api && uv run pytest tests/unit/test_risk_models.py tests/unit/test_orders_fsm.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.risk` / `ImportError: ON_REVIEW`.

- [ ] **Step 3: Implement the statuses and the FSM**

`payments/models.py:43`:

```python
#: ``held``: a kassa paid it, the risk rule holds it for an admin (spec 2026-10-21);
#: ``rejected``: the admin returned that money to the card, nothing was credited.
TOPUP_STATUSES = ("pending", "succeeded", "expired", "reversed", "held", "rejected")
```

`orders/models.py` — add `"held"` after `"pending"` in `ORDER_STATUSES`, and below `IN_FLIGHT`:

```python
#: Paid through a kassa, held by the risk rule until an admin decides (spec 2026-10-21):
#: not ``pending`` (no second payment, no expiry), not in flight (nothing is bought).
ON_REVIEW: frozenset[str] = frozenset({"held"})
```

`orders/fsm.py` `TRANSITIONS`:

```python
    "pending": frozenset({"paid", "held", "cancelled"}),
    "held": frozenset({"paid", "cancelled"}),
```

`orders/schemas.py:13-15`, `admin/payments_schemas.py:77-80`: add `"held"` to the order Literal.
`payments/schemas.py:70`, `admin/payments_schemas.py:69`, `admin/users_schemas.py:159`: add
`"held", "rejected"` to the top-up Literal.

- [ ] **Step 4: Create the risk models**

`risk/__init__.py`:

```python
"""Payment risk limits: per-kassa and per-user window limits and the holds they raise."""
```

`risk/models.py`:

```python
"""The risk tables (spec 2026-10-21-payment-risk-limits).

- :class:`KassaReviewLimit` — one row per kassa: above ``max_amount_uzs`` within
  ``window_hours`` a user's payment is held.
- :class:`UserRiskPolicy` — one row per user the admin configured: trusted, blocked, own limit.
- :class:`PaymentHold` — one row per held payment and the decision taken on it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

# Registers ``payments``, the target of ``payment_holds.payment_id``.
from csmarket.modules.payments import models as _payments_models  # noqa: F401

HOLD_REASONS = ("kassa_limit", "user_limit", "check_failed")
HOLD_DECISIONS = ("released", "returned", "reversed_by_kassa")
HOLD_KINDS = ("topup", "order")
HoldReason = Literal["kassa_limit", "user_limit", "check_failed"]
HoldDecision = Literal["released", "returned", "reversed_by_kassa"]
HoldKind = Literal["topup", "order"]
#: Window bounds in hours, both tables.
MIN_WINDOW_HOURS, MAX_WINDOW_HOURS = 1, 720


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_TS = DateTime(timezone=True)
_NOW = text("CURRENT_TIMESTAMP")
_WINDOW = f"window_hours BETWEEN {MIN_WINDOW_HOURS} AND {MAX_WINDOW_HOURS}"


class KassaReviewLimit(Base):
    """A kassa's limit: a user's money through it within the window, above which it is held."""

    __tablename__ = "kassa_review_limits"

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="24")
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=_NOW)

    __table_args__ = (
        CheckConstraint("max_amount_uzs >= 1", name="max_positive"),
        CheckConstraint(_WINDOW, name="window"),
    )


class UserRiskPolicy(Base):
    """What the admin set on one user; no row = no policy."""

    __tablename__ = "user_risk_policies"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    kassa_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: The user's own limit over every kassa; ``NULL`` = none.
    max_amount_uzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 0), nullable=True)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="24")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=_NOW)

    __table_args__ = (
        CheckConstraint("max_amount_uzs IS NULL OR max_amount_uzs >= 1", name="max_positive"),
        CheckConstraint(_WINDOW, name="window"),
    )


class PaymentHold(Base):
    """A kassa payment the rule held, and the decision taken on it (``NULL`` = open)."""

    __tablename__ = "payment_holds"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id"), nullable=False, unique=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The window sum including this payment, and the limit it broke (``NULL`` on check_failed).
    window_sum_uzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 0), nullable=True)
    limit_uzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 0), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=_NOW)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN {_in(HOLD_KINDS)}", name="kind"),
        CheckConstraint(f"reason IN {_in(HOLD_REASONS)}", name="reason"),
        CheckConstraint(
            f"decision IS NULL OR decision IN {_in(HOLD_DECISIONS)}", name="decision"
        ),
        CheckConstraint("(decision IS NULL) = (decided_at IS NULL)", name="decided_pair"),
        Index("ix_payment_holds_open", text("created_at DESC"),
              postgresql_where=text("decision IS NULL")),
        Index("ix_payment_holds_decided", text("decided_at DESC"),
              postgresql_where=text("decision IS NOT NULL")),
        Index("ix_payment_holds_user", "user_id"),
    )
```

Add `from csmarket.modules.risk import models as _risk_models  # noqa: F401` to the model-import
blocks of `apps/api/migrations/env.py`, `apps/scheduler/src/csmarket_scheduler/main.py` and
`apps/worker/src/csmarket_worker/consumer.py` (alphabetical, after `public_api`).

- [ ] **Step 5: Write the migration**

`apps/api/migrations/versions/0039_payment_risk.py`:

```python
"""Payment risk limits: kassa limits, user policies, holds; held / rejected statuses.

Revision ID: 0039_payment_risk
Revises: 0038_p2p
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_payment_risk"
down_revision: str | None = "0038_p2p"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")
_WINDOW = "window_hours BETWEEN 1 AND 720"

_TOPUP_OLD = "status IN ('pending', 'succeeded', 'expired', 'reversed')"
_TOPUP_NEW = "status IN ('pending', 'succeeded', 'expired', 'reversed', 'held', 'rejected')"
_ORDER_OLD = (
    "status IN ('pending', 'paid', 'buying', 'trade_sent', 'delivered', 'cancelled', "
    "'failed', 'returned')"
)
_ORDER_NEW = (
    "status IN ('pending', 'held', 'paid', 'buying', 'trade_sent', 'delivered', 'cancelled', "
    "'failed', 'returned')"
)
#: Owner ruling 2 (spec 2026-10-21): every kassa on, 2 000 000 soʻm per 24 h.
_SEED = ("payme", "click", "uzum", "p2p")


def upgrade() -> None:
    op.create_table(
        "kassa_review_limits",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("updated_by", _UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("max_amount_uzs >= 1", name="max_positive"),
        sa.CheckConstraint(_WINDOW, name="window"),
    )
    op.create_table(
        "user_risk_policies",
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("kassa_blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_amount_uzs", sa.Numeric(14, 0), nullable=True),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", _UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("max_amount_uzs IS NULL OR max_amount_uzs >= 1", name="max_positive"),
        sa.CheckConstraint(_WINDOW, name="window"),
    )
    op.create_table(
        "payment_holds",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("payment_id", _UUID, sa.ForeignKey("payments.id"), nullable=False, unique=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("window_sum_uzs", sa.Numeric(14, 0), nullable=True),
        sa.Column("limit_uzs", sa.Numeric(14, 0), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("decided_by", _UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", _TS, nullable=True),
        sa.CheckConstraint("kind IN ('topup', 'order')", name="kind"),
        sa.CheckConstraint(
            "reason IN ('kassa_limit', 'user_limit', 'check_failed')", name="reason"
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('released', 'returned', 'reversed_by_kassa')",
            name="decision",
        ),
        sa.CheckConstraint("(decision IS NULL) = (decided_at IS NULL)", name="decided_pair"),
    )
    op.create_index(
        "ix_payment_holds_open", "payment_holds", [sa.text("created_at DESC")],
        postgresql_where=sa.text("decision IS NULL"),
    )
    op.create_index(
        "ix_payment_holds_decided", "payment_holds", [sa.text("decided_at DESC")],
        postgresql_where=sa.text("decision IS NOT NULL"),
    )
    op.create_index("ix_payment_holds_user", "payment_holds", ["user_id"])
    # The window sum: a user's succeeded payments, per kassa, newest first.
    op.create_index(
        "ix_payments_user_provider_succeeded", "payments",
        ["user_id", "provider", sa.text("succeeded_at DESC")],
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.drop_constraint("status", "wallet_topups", type_="check")
    op.create_check_constraint("status", "wallet_topups", _TOPUP_NEW)
    op.drop_constraint("status", "orders", type_="check")
    op.create_check_constraint("status", "orders", _ORDER_NEW)
    for provider in _SEED:
        op.execute(
            "INSERT INTO kassa_review_limits (provider, enabled, max_amount_uzs, window_hours) "
            f"VALUES ('{provider}', true, 2000000, 24)"
        )


def downgrade() -> None:
    op.drop_constraint("status", "orders", type_="check")
    op.create_check_constraint("status", "orders", _ORDER_OLD)
    op.drop_constraint("status", "wallet_topups", type_="check")
    op.create_check_constraint("status", "wallet_topups", _TOPUP_OLD)
    op.drop_index("ix_payments_user_provider_succeeded", table_name="payments")
    op.drop_table("payment_holds")
    op.drop_table("user_risk_policies")
    op.drop_table("kassa_review_limits")
```

Also add the same partial index to `Payment.__table_args__` in `payments/models.py`:

```python
        Index(
            "ix_payments_user_provider_succeeded",
            "user_id",
            "provider",
            text("succeeded_at DESC"),
            postgresql_where=text("status = 'succeeded'"),
        ),
```

- [ ] **Step 6: Run the tests and the migration check**

Run: `cd apps/api && uv run pytest tests/unit/test_risk_models.py tests/unit/test_orders_fsm.py tests/integration/test_migrations.py -q`
Expected: PASS (if `test_migrations.py` does not exist, run any integration test — the session
fixture upgrades to head and fails on a broken migration).

- [ ] **Step 7: Commit**

```bash
git add apps/api apps/scheduler/src apps/worker/src
git commit -m "feat(api/risk): kassa limits, user policies, holds and the held statuses

The orders FSM test now partitions statuses into pending, on review, in flight and
terminal: held is paid money with nothing bought yet.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The verdict

**Files:**

- Create: `apps/api/src/csmarket/modules/risk/rule.py`, `risk/api.py`,
  `apps/api/tests/integration/risk_factory.py`, `apps/api/tests/integration/test_risk_rule.py`

**Interfaces:**

- Consumes: Task 1 models.
- Produces:
  - `class Verdict(BaseModel, frozen)`: `hold: bool`, `reason: HoldReason | None`,
    `window_sum_uzs: Decimal | None`, `limit_uzs: Decimal | None`.
  - `async def verdict(db: AsyncSession, payment: Payment) -> Verdict` — takes the user's
    advisory lock, never raises (an error → `check_failed`).
  - `async def money_in(db, *, user_id: str, hours: int, provider: str | None = None,
exclude_payment_id: str | None = None) -> Decimal`.
  - `risk.api` re-exports `Verdict, verdict, money_in, PaymentHold, KassaReviewLimit,
UserRiskPolicy, HoldReason, HoldDecision, HoldKind`.
  - Test factory `risk_factory.py`: `set_kassa_limit(db, provider, amount, *, hours=24,
enabled=True)`, `set_policy(db, user_id, **fields)`, `succeeded_payment(db, user, *,
provider="payme", amount=Decimal(...), hours_ago=0.0) -> Payment`.

- [ ] **Step 1: Write the factory and failing tests**

`apps/api/tests/integration/risk_factory.py`:

```python
"""Builders for the risk tests: limits, policies and past kassa payments."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.modules.payments.api import Payment
from csmarket.modules.risk.models import KassaReviewLimit, UserRiskPolicy
from csmarket.modules.users.api import User
from tests.integration.payments_factory import make_topup


async def set_kassa_limit(
    db: AsyncSession, provider: str, amount: int, *, hours: int = 24, enabled: bool = True
) -> None:
    """Replace ``provider``'s limit row and commit."""
    await db.execute(delete(KassaReviewLimit).where(KassaReviewLimit.provider == provider))
    db.add(KassaReviewLimit(provider=provider, enabled=enabled,
                            max_amount_uzs=Decimal(amount), window_hours=hours))
    await db.commit()


async def clear_kassa_limits(db: AsyncSession) -> None:
    """Drop every seeded limit so a test starts unlimited."""
    await db.execute(delete(KassaReviewLimit))
    await db.commit()


async def set_policy(db: AsyncSession, user_id: str, **fields: Any) -> None:
    """Replace the user's policy row and commit."""
    await db.execute(delete(UserRiskPolicy).where(UserRiskPolicy.user_id == user_id))
    db.add(UserRiskPolicy(user_id=user_id, **fields))
    await db.commit()


async def succeeded_payment(
    db: AsyncSession, user: User, *, provider: str = "payme",
    amount: int = 500_000, hours_ago: float = 0.0, status: str = "succeeded",
) -> Payment:
    """A past kassa payment of ``user`` that settled ``hours_ago`` (a top-up's attempt)."""
    topup = await make_topup(db, user=user, amount=Decimal(amount), status="succeeded")
    at = now() - timedelta(hours=hours_ago)
    payment = Payment(
        number=topup.number, purpose="topup", topup_id=topup.id, user_id=user.id,
        provider=provider, amount_uzs=Decimal(amount), fee_pct=Decimal(0), fee_uzs=Decimal(0),
        status=status, succeeded_at=at, created_at=at, updated_at=at,
    )
    db.add(payment)
    await db.commit()
    return payment
```

(Match `Payment`'s required columns to `payments/models.py:95-175` — if a column such as
`extra_metadata` has no server default, pass `extra_metadata={}`.)

`apps/api/tests/integration/test_risk_rule.py`:

```python
"""The risk verdict (spec 2026-10-21-payment-risk-limits, «The rule»)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from csmarket.modules.payments.api import Payment
from csmarket.modules.risk.api import verdict
from tests.integration.payments_factory import make_user
from tests.integration.risk_factory import (
    clear_kassa_limits, set_kassa_limit, set_policy, succeeded_payment,
)

pytestmark = pytest.mark.asyncio


async def _new(db: AsyncSession, user_id: str, amount: int, provider: str = "payme") -> Payment:
    """An unsettled attempt (the one being checked)."""
    user = await db.get_one(__import__("csmarket.modules.users.api", fromlist=["User"]).User, user_id)
    p = await succeeded_payment(db, user, provider=provider, amount=amount, status="pending")
    return p


async def test_under_and_equal_pass(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=600_000)
    current = await _new(db_session, user.id, 400_000)
    v = await verdict(db_session, current)
    assert v.hold is False


async def test_split_payments_over_the_window_are_held(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    for _ in range(3):
        await succeeded_payment(db_session, user, amount=300_000, hours_ago=2)
    current = await _new(db_session, user.id, 200_000)
    v = await verdict(db_session, current)
    assert (v.hold, v.reason) == (True, "kassa_limit")
    assert v.window_sum_uzs == Decimal(1_100_000) and v.limit_uzs == Decimal(1_000_000)


async def test_outside_window_and_other_kassa_do_not_count(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=900_000, hours_ago=25)
    await succeeded_payment(db_session, user, provider="click", amount=900_000)
    current = await _new(db_session, user.id, 900_000)
    assert (await verdict(db_session, current)).hold is False


async def test_refunded_does_not_count(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=900_000, status="refunded")
    current = await _new(db_session, user.id, 900_000)
    assert (await verdict(db_session, current)).hold is False


async def test_disabled_or_missing_limit_passes(db_session: AsyncSession) -> None:
    await clear_kassa_limits(db_session)
    await set_kassa_limit(db_session, "click", 1, enabled=False)
    user = await make_user(db_session)
    assert (await verdict(db_session, await _new(db_session, user.id, 5_000_000))).hold is False
    assert (await verdict(db_session, await _new(db_session, user.id, 5_000_000, "click"))).hold is False


async def test_user_limit_spans_kassas(db_session: AsyncSession) -> None:
    await clear_kassa_limits(db_session)
    user = await make_user(db_session)
    await set_policy(db_session, user.id, max_amount_uzs=Decimal(1_000_000), window_hours=48)
    await succeeded_payment(db_session, user, provider="click", amount=700_000, hours_ago=30)
    v = await verdict(db_session, await _new(db_session, user.id, 400_000, "payme"))
    assert (v.hold, v.reason, v.limit_uzs) == (True, "user_limit", Decimal(1_000_000))


async def test_trusted_bypasses_both(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    user = await make_user(db_session)
    await set_policy(db_session, user.id, trusted=True, max_amount_uzs=Decimal(1))
    assert (await verdict(db_session, await _new(db_session, user.id, 5_000_000))).hold is False


async def test_an_error_holds_and_leaves_the_transaction_usable(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    current = await _new(db_session, user.id, 1)
    with patch("csmarket.modules.risk.rule._kassa_limit", side_effect=RuntimeError("boom")):
        v = await verdict(db_session, current)
    assert (v.hold, v.reason, v.window_sum_uzs) == (True, "check_failed", None)
    await db_session.refresh(current)  # the session still works


async def test_two_settles_at_once_are_serialised(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as db:
        await set_kassa_limit(db, "payme", 1_000_000)
        user = await make_user(db)
        a = await _new(db, user.id, 600_000)
        b = await _new(db, user.id, 600_000)

    async def _check(pid: str) -> bool:
        async with factory() as db:
            p = await db.get_one(Payment, pid)
            v = await verdict(db, p)
            if not v.hold:  # what settle does on a pass: the money now counts
                p.status = "succeeded"
                p.succeeded_at = __import__("csmarket.core.clock", fromlist=["now"]).now()
            await db.commit()
            return v.hold

    held = await asyncio.gather(_check(a.id), _check(b.id))
    assert sorted(held) == [False, True]
```

(Replace the two `__import__` shortcuts with ordinary top-of-file imports of `User` and `now`
when writing the file — they are spelled inline here only to keep each test self-describing.)

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && uv run pytest tests/integration/test_risk_rule.py -q`
Expected: FAIL — `ImportError: cannot import name 'verdict' from 'csmarket.modules.risk.api'`.

- [ ] **Step 3: Implement `risk/rule.py`**

```python
"""The risk verdict: does a kassa payment pass or wait for an admin (spec 2026-10-21).

Asked by ``payments.hooks.settle`` before money is credited or an order is paid. A user's
settles are serialised by a transaction-scoped advisory lock, so two kassas paying at once
cannot both slip under a limit. Fail-closed (owner ruling 5): any error is a hold.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.payments.models import Payment
from csmarket.modules.risk.models import HoldReason, KassaReviewLimit, UserRiskPolicy

log = get_logger("csmarket.risk.rule")


class Verdict(BaseModel):
    """Pass, or hold with the reason, the window sum and the limit it broke."""

    model_config = ConfigDict(frozen=True)

    hold: bool
    reason: HoldReason | None = None
    window_sum_uzs: Decimal | None = None
    limit_uzs: Decimal | None = None


PASS = Verdict(hold=False)


async def lock_user(db: AsyncSession, user_id: str) -> None:
    """Serialise this user's settles until the transaction ends."""
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"risk:user:{user_id}"))))


async def money_in(
    db: AsyncSession, *, user_id: str, hours: int, provider: str | None = None,
    exclude_payment_id: str | None = None,
) -> Decimal:
    """The user's kassa money that stayed with us in the last ``hours`` (held included)."""
    q = select(func.coalesce(func.sum(Payment.amount_uzs), 0)).where(
        Payment.user_id == user_id,
        Payment.status == "succeeded",
        Payment.succeeded_at >= now() - timedelta(hours=hours),
    )
    if provider is not None:
        q = q.where(Payment.provider == provider)
    if exclude_payment_id is not None:
        q = q.where(Payment.id != exclude_payment_id)
    return Decimal((await db.scalar(q)) or 0)


async def _kassa_limit(db: AsyncSession, payment: Payment) -> Verdict:
    row = await db.get(KassaReviewLimit, payment.provider)
    if row is None or not row.enabled:
        return PASS
    total = payment.amount_uzs + await money_in(
        db, user_id=payment.user_id, hours=row.window_hours, provider=payment.provider,
        exclude_payment_id=payment.id,
    )
    if total <= row.max_amount_uzs:
        return PASS
    return Verdict(hold=True, reason="kassa_limit", window_sum_uzs=total,
                   limit_uzs=row.max_amount_uzs)


async def _user_limit(db: AsyncSession, payment: Payment, policy: UserRiskPolicy) -> Verdict:
    if policy.max_amount_uzs is None:
        return PASS
    total = payment.amount_uzs + await money_in(
        db, user_id=payment.user_id, hours=policy.window_hours, exclude_payment_id=payment.id
    )
    if total <= policy.max_amount_uzs:
        return PASS
    return Verdict(hold=True, reason="user_limit", window_sum_uzs=total,
                   limit_uzs=policy.max_amount_uzs)


async def _judge(db: AsyncSession, payment: Payment) -> Verdict:
    policy = await db.get(UserRiskPolicy, payment.user_id)
    if policy is not None and policy.trusted:
        return PASS
    kassa = await _kassa_limit(db, payment)
    if kassa.hold or policy is None:
        return kassa
    return await _user_limit(db, payment, policy)


async def verdict(db: AsyncSession, payment: Payment) -> Verdict:
    """Pass or hold ``payment`` (not yet ``succeeded``); never raises.

    Takes the user's advisory lock first; the reads run in a savepoint so a failed query
    leaves the caller's transaction usable, and any error is a ``check_failed`` hold.
    """
    await lock_user(db, payment.user_id)
    try:
        async with db.begin_nested():
            return await _judge(db, payment)
    except Exception as exc:  # noqa: BLE001 -- fail-closed by owner ruling 5
        log.warning("payments.risk.check_failed", number=payment.number,
                    provider=payment.provider, error=type(exc).__name__)
        return Verdict(hold=True, reason="check_failed")
```

`risk/api.py`:

```python
"""What other modules may import from ``risk``."""

from csmarket.modules.risk.models import (
    HoldDecision, HoldKind, HoldReason, KassaReviewLimit, PaymentHold, UserRiskPolicy,
)
from csmarket.modules.risk.rule import Verdict, money_in, verdict

__all__ = [
    "HoldDecision", "HoldKind", "HoldReason", "KassaReviewLimit", "PaymentHold",
    "UserRiskPolicy", "Verdict", "money_in", "verdict",
]
```

(`ruff format` will expand the import lists.)

- [ ] **Step 4: Run to verify they pass**

Run: `cd apps/api && uv run pytest tests/integration/test_risk_rule.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/csmarket/modules/risk apps/api/tests/integration/risk_factory.py apps/api/tests/integration/test_risk_rule.py
git commit -m "feat(api/risk): the per-kassa and per-user window verdict, fail-closed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Hold on settle

**Files:**

- Create: `apps/api/src/csmarket/modules/payments/holds.py`,
  `apps/api/tests/integration/test_payment_holds_settle.py`
- Modify: `payments/hooks.py:261-330`, `payments/payable.py:25-28`, `payments/topups.py:255-280`,
  `payme/service.py:91-99`, `click/service.py:71-79`, `uzum/service.py:87-95` (only if their
  reason maps are exhaustive `dict[Reason, …]` — add nothing if they key on the existing
  reasons, since `held` / `rejected` map to the existing reason `paid`)

**Interfaces:**

- Consumes: `risk.api.verdict`, `Verdict`, `PaymentHold`.
- Produces:
  - `settle(db, *, payment, event_id, check_risk: bool = True) -> None` — on a hold the attempt
    goes `succeeded`, the owner goes `held`, a `PaymentHold` row is written.
  - `payments.holds.hold(db, *, payment: Payment, owner: WalletTopup | Order, verdict: Verdict) -> PaymentHold`.
  - payable `_REFUSED` gains `"held": "paid", "rejected": "paid"`.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/integration/test_payment_holds_settle.py`:

```python
"""settle holds money over a limit (spec 2026-10-21, «Hold»)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.payments.api import (
    AlreadyPaidError, credit_received_transfer, ensure_attempt, resolve, settle,
)
from csmarket.modules.risk.api import PaymentHold
from csmarket.modules.wallet.api import balance_uzs
from tests.integration.orders_factory import listen_orders, make_order
from tests.integration.payments_factory import make_topup, make_user
from tests.integration.risk_factory import set_kassa_limit

pytestmark = pytest.mark.asyncio


async def _topup_attempt(db: AsyncSession, amount: int, provider: str = "payme"):
    user = await make_user(db)
    t = await make_topup(db, user=user, amount=Decimal(amount))
    p = await ensure_attempt(db, payable=await resolve(db, t.number, lock=True), provider=provider)
    await db.commit()
    return user, t, p


async def test_topup_over_limit_is_held_not_credited(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user, t, p = await _topup_attempt(db_session, 1_500_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await db_session.refresh(t)
    assert (t.status, p.status) == ("held", "succeeded")
    assert await balance_uzs(db_session, user_id=user.id) == Decimal(0)
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    assert hold is not None and (hold.kind, hold.reason, hold.decision) == ("topup", "kassa_limit", None)
    assert hold.window_sum_uzs == Decimal(1_500_000)


async def test_topup_under_limit_credits_as_before(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user, t, p = await _topup_attempt(db_session, 1_000_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await db_session.refresh(t)
    assert t.status == "succeeded"
    assert await balance_uzs(db_session, user_id=user.id) == Decimal(1_000_000)


async def test_order_over_limit_is_held_without_notify(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    order = await make_order(db_session)
    p = await ensure_attempt(db_session, payable=await resolve(db_session, order.number, lock=True),
                             provider="payme")
    await db_session.commit()
    async with listen_orders() as heard:
        await settle(db_session, payment=p, event_id="e1")
        await db_session.commit()
    await db_session.refresh(order)
    assert (order.status, order.paid_with, order.paid_at) == ("held", "payme", None)
    assert heard == []


async def test_retried_settle_of_held_payment_is_noop(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    _, t, p = await _topup_attempt(db_session, 50_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    n = await db_session.scalar(select(func.count()).select_from(PaymentHold)
                                .where(PaymentHold.payment_id == p.id))
    assert n == 1


async def test_held_topup_is_not_payable_again(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    _, t, p = await _topup_attempt(db_session, 50_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    payable = await resolve(db_session, t.number)
    assert payable.reason == "paid"
    with pytest.raises(AlreadyPaidError):
        await ensure_attempt(db_session, payable=payable, provider="click")


async def test_credit_received_transfer_is_never_held(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "p2p", 1)
    user = await make_user(db_session)
    topup = await credit_received_transfer(
        db_session, user_id=user.id, amount_uzs=Decimal(3_000_000), provider="p2p",
        event_id="hand-1",
    )
    await db_session.commit()
    assert topup.status == "succeeded"
```

(Check `credit_received_transfer`'s real keyword names at `payments/topups.py:254` and the
wallet balance reader's name in `wallet/api.py` — use those exactly; `listen_orders()` yields
the list of heard order numbers per `orders_factory.py`.)

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_settle.py -q`
Expected: FAIL — top-up status `succeeded` instead of `held` (no rule yet).

- [ ] **Step 3: Implement `payments/holds.py` (the write half)**

```python
"""Held kassa payments (spec 2026-10-21-payment-risk-limits).

:func:`hold` is called by ``hooks.settle`` when the risk verdict holds: the attempt is already
``succeeded`` (the kassa has the money), the owner goes ``held`` and a ``payment_holds`` row
records why. Decisions — release, returned, a kassa's own reversal — live below.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.logging import get_logger
from csmarket.modules.orders.api import Order, move_order
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.risk.api import PaymentHold, Verdict

log = get_logger("csmarket.payments.holds")


async def hold(
    db: AsyncSession, *, payment: Payment, owner: WalletTopup | Order, verdict: Verdict
) -> PaymentHold:
    """Put ``owner`` on review for ``payment`` (already ``succeeded``) and record why."""
    if isinstance(owner, Order):
        move_order(owner, "held")
        owner.paid_with = payment.provider
        kind = "order"
    else:
        owner.status = "held"
        owner.payment_id = payment.id
        owner.succeeded_at = payment.succeeded_at
        kind = "topup"
    assert verdict.reason is not None  # a hold always has one
    row = PaymentHold(
        payment_id=payment.id, user_id=payment.user_id, kind=kind, provider=payment.provider,
        amount_uzs=payment.amount_uzs, reason=verdict.reason,
        window_sum_uzs=verdict.window_sum_uzs, limit_uzs=verdict.limit_uzs,
    )
    db.add(row)
    await db.flush()
    log.warning("payments.hold.created", number=payment.number, kind=kind,
                provider=payment.provider, amount=str(payment.amount_uzs), reason=verdict.reason)
    return row
```

`orders.api` must export the order FSM's `move` as `move_order` — add
`from csmarket.modules.orders.fsm import move as move_order` and `"move_order"` to `__all__` in
`orders/api.py` if no such export exists yet (check first: `grep -n "fsm" orders/api.py`).

- [ ] **Step 4: Wire it into `settle`**

In `payments/hooks.py` add imports `from csmarket.modules.payments import holds` and
`from csmarket.modules.risk.api import verdict as risk_verdict`, and change `settle`:

```python
async def settle(
    db: AsyncSession, *, payment: Payment, event_id: str, check_risk: bool = True
) -> None:
    """...existing docstring...

    Before paying, the risk verdict may hold the money (spec 2026-10-21): the attempt goes
    ``succeeded`` (the kassa is answered as paid), the owner ``held``, nothing is credited and
    no ``NOTIFY``. ``check_risk=False`` is the admin's own credit of a received transfer.
    """
    owner = await _lock_owner_then_payment(db, payment)
    if payment.status == "succeeded":
        return
    _refuse_second_payment(owner, payment)
    verdict = await risk_verdict(db, payment) if check_risk else None
    move(payment, "succeeded")
    payment.extra_metadata = {**payment.extra_metadata, "settle_event_id": event_id}
    if verdict is not None and verdict.hold:
        await holds.hold(db, payment=payment, owner=owner, verdict=verdict)
        return
    if isinstance(owner, Order):
        await _pay_order(db, payment=payment, order=owner)
        return
    await _credit(db, payment=payment, topup=owner)
```

Split the old bodies into three helpers (each keeps its existing log lines verbatim):

```python
def _refuse_second_payment(owner: Owner, payment: Payment) -> None:
    """Raise :class:`AlreadyPaidError` when the owner was already paid or put on review."""
    if isinstance(owner, Order):
        if owner.status == "pending":
            return
        log.warning("payments.order.second_payment_refused", number=owner.number,
                    provider=payment.provider, status=owner.status)
        if owner.status == "cancelled":
            raise AlreadyPaidError("order cancelled", code="cancelled")
        raise AlreadyPaidError("order already paid")
    if owner.status in _CREDITED:
        log.warning("payments.topup.second_payment_refused", number=owner.number,
                    provider=payment.provider)
        raise AlreadyPaidError("top-up already paid")


async def _pay_order(db: AsyncSession, *, payment: Payment, order: Order) -> None:
    await mark_paid(db, order, provider=payment.provider)
    log.info("payments.order.paid", number=order.number, provider=payment.provider,
             amount=str(payment.amount_uzs))


async def _credit(db: AsyncSession, *, payment: Payment, topup: WalletTopup) -> None:
    topup.status = "succeeded"
    topup.payment_id = payment.id
    topup.succeeded_at = payment.succeeded_at
    await credit_topup(db, user_id=topup.user_id, topup_id=topup.id, amount=topup.amount_uzs,
                       provider=payment.provider)
    await db.flush()
    log.info("payments.topup.credited", number=topup.number, provider=payment.provider,
             amount=str(topup.amount_uzs))
```

and `_CREDITED = frozenset({"succeeded", "reversed", "held", "rejected"})`. Delete
`_settle_order` (its body now lives in `_refuse_second_payment` + `_pay_order`); update the
README table row for `settle` in `payments/README.md:118` to mention the hold.

In `payments/topups.py` `credit_received_transfer` change the `settle(...)` call to
`settle(db, payment=payment, event_id=event_id, check_risk=False)`.

In `payments/payable.py:28`:

```python
_REFUSED: dict[str, Reason] = {
    "succeeded": "paid", "held": "paid", "rejected": "paid",
    "expired": "expired", "reversed": "reversed",
}
```

- [ ] **Step 5: Run the new and the old settle tests**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_settle.py tests/integration/test_payment_hooks.py tests/integration/test_payment_hooks_orders.py -q`
Expected: all pass. If an old test now holds because the seeded 2 000 000 limit is exceeded by
its amounts, call `clear_kassa_limits(db_session)` at its start and say so in the commit body.

- [ ] **Step 6: Commit**

```bash
git add apps/api
git commit -m "feat(api/payments): settle holds money over a risk limit instead of crediting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Every kassa end to end, and a kassa reversing a held payment

**Files:**

- Create: `apps/api/tests/integration/test_payment_holds_kassas.py`
- Modify: `payments/hooks.py` `reverse` (lines 333-378), `payments/holds.py` (add `close`,
  `reverse_held`)

**Interfaces:**

- Consumes: Task 3 `hold`.
- Produces: `holds.close(db, *, hold: PaymentHold, decision: HoldDecision, admin_id: str | None) -> None`;
  `holds.reverse_held(db, *, payment: Payment, owner: WalletTopup | Order, event_id: str) -> None`;
  `holds.open_hold_for(db, payment_id: str, *, lock: bool = False) -> PaymentHold | None`.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/integration/test_payment_holds_kassas.py` — one test per kassa driving the real
webhook / service entry point with an amount over a 1-soʻm limit, reusing each existing suite's
helpers (copy the request-building helpers from `test_click_webhook.py`,
`test_payme_service.py`, `test_uzum_webhook.py` and the P2P intake test):

```python
"""Each kassa's money path holds over the limit and answers the kassa as paid."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.payments.api import Payment, WalletTopup, ensure_attempt, resolve, reverse, settle
from csmarket.modules.risk.api import PaymentHold
from csmarket.modules.wallet.api import balance_uzs
from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_topup, make_user
from tests.integration.risk_factory import set_kassa_limit

pytestmark = pytest.mark.asyncio


async def test_payme_perform_over_limit_answers_performed_and_holds(...) -> None:
    """Payme PerformTransaction → state 2 in the answer; top-up held; balance 0."""
    # Arrange with the helpers of test_payme_service.py (CreateTransaction, then Perform).
    # Assert: answer["result"]["state"] == 2; topup.status == "held"; balance 0;
    # one PaymentHold with kind "topup".


async def test_click_complete_over_limit_answers_success_and_holds(...) -> None:
    """Click prepare + complete → error 0; top-up held."""


async def test_uzum_confirm_over_limit_answers_confirmed_and_holds(...) -> None:
    """Uzum check + create + confirm → status CONFIRMED; top-up held."""


async def test_p2p_matched_transfer_over_limit_is_held(...) -> None:
    """A parsed HUMO credit matching an open request settles into held, not credited."""


async def test_kassa_reversal_of_held_topup_debits_nothing(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    user = await make_user(db_session)
    t = await make_topup(db_session, user=user, amount=Decimal(50_000))
    p = await ensure_attempt(db_session, payable=await resolve(db_session, t.number, lock=True),
                             provider="payme")
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await db_session.refresh(t)
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    assert (t.status, p.status) == ("reversed", "refunded")
    assert hold is not None and hold.decision == "reversed_by_kassa" and hold.decided_by is None
    assert await balance_uzs(db_session, user_id=user.id) == Decimal(0)


async def test_kassa_reversal_of_held_order_cancels_it(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    order = await make_order(db_session)
    p = await ensure_attempt(db_session, payable=await resolve(db_session, order.number, lock=True),
                             provider="payme")
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await db_session.refresh(order)
    assert (order.status, p.status) == ("cancelled", "refunded")
```

Fill the four kassa tests' bodies from their source suites — the arrange code there is what
creates a valid signed request; the assertions are the ones written in each docstring. Payme's
`CancelTransaction` of a held top-up must answer success (state −2) — add that assertion to the
Payme test by cancelling after perform.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_kassas.py -q`
Expected: the four kassa tests PASS already (Task 3 did the work — that is the point of these
tests: pinning each entry point); the two reversal tests FAIL (`OrderReversalRefusedError` /
`InsufficientBalanceError`-path debit).

- [ ] **Step 3: Implement the reversal**

In `payments/holds.py` add:

```python
from sqlalchemy import select

from csmarket.core.clock import now
from csmarket.modules.payments.fsm import move as move_payment
from csmarket.modules.risk.api import HoldDecision


async def open_hold_for(db: AsyncSession, payment_id: str, *, lock: bool = False) -> PaymentHold | None:
    """The undecided hold of ``payment_id``, if any."""
    q = select(PaymentHold).where(PaymentHold.payment_id == payment_id,
                                  PaymentHold.decision.is_(None))
    if lock:
        q = q.with_for_update()
    return (await db.execute(q)).scalar_one_or_none()


def close(hold_row: PaymentHold, *, decision: HoldDecision, admin_id: str | None) -> None:
    """Record the decision on an open hold."""
    hold_row.decision = decision
    hold_row.decided_by = admin_id
    hold_row.decided_at = now()


async def reverse_held(
    db: AsyncSession, *, payment: Payment, owner: WalletTopup | Order, event_id: str
) -> None:
    """The kassa took back a held payment: nothing was credited or bought, nothing to claw back."""
    row = await open_hold_for(db, payment.id, lock=True)
    move_payment(payment, "refunded")
    payment.extra_metadata = {**payment.extra_metadata, "reverse_event_id": event_id}
    if isinstance(owner, Order):
        move_order(owner, "cancelled")
    else:
        owner.status = "reversed"
    if row is not None:
        close(row, decision="reversed_by_kassa", admin_id=None)
    await db.flush()
    log.warning("payments.hold.reversed_by_kassa", number=payment.number, provider=payment.provider)
```

In `payments/hooks.py` `reverse`, right after `owner = await _lock_owner_then_payment(db, payment)`
and the `payment.status == "refunded"` early return (move that check above the order refusal):

```python
    if payment.status == "refunded":
        return
    if owner.status == "held":
        await holds.reverse_held(db, payment=payment, owner=owner, event_id=event_id)
        return
    if isinstance(owner, Order):
        ...existing refusal (R7)...
```

Update `reverse`'s docstring: «A held payment (spec 2026-10-21) is the one exception to R7:
nothing was bought, so the order is cancelled and nothing is debited.»

- [ ] **Step 4: Run**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_kassas.py tests/integration/test_payment_hooks.py tests/integration/test_payment_hooks_orders.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat(api/payments): a kassa may cancel a held payment; pin each kassa's hold path

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Admin decisions and the holds list

**Files:**

- Modify: `payments/holds.py` (add `release`, `mark_returned`, `list_holds`, `HoldOut`, `HoldPage`)
- Create: `payments/holds_routes.py`, `apps/api/tests/integration/test_payment_holds_decide.py`
- Modify: `api/v1/router.py` (include before `admin_payments_router`)

**Interfaces:**

- Consumes: Tasks 3–4.
- Produces (wire):
  - `HoldOut`: `id, number, kind, provider, amount_uzs: str, reason, window_sum_uzs: str | None,
limit_uzs: str | None, user: HoldUserOut{id, display_name}, created_at, decision,
decided_by: HoldUserOut | None, decided_at`.
  - `HoldPage`: `items: list[HoldOut], next_cursor: str | None`.
  - `GET /api/v1/admin/payments/holds?state=open|decided&cursor=` → `HoldPage`.
  - `POST /api/v1/admin/payments/holds/{hold_id}/release` → `HoldOut` (idem key).
  - `POST /api/v1/admin/payments/holds/{hold_id}/returned` → `HoldOut` (idem key).
  - Errors: 404 `hold_not_found`, 409 `hold_decided`.
  - Audit actions `payments.hold.release`, `payments.hold.returned`, target_type `payment_hold`.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/integration/test_payment_holds_decide.py`:

```python
"""The admin releases a hold or records the money returned (spec 2026-10-21)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.payments.api import ensure_attempt, resolve, settle
from csmarket.modules.risk.api import PaymentHold
from csmarket.modules.wallet.api import balance_uzs
from tests.integration.orders_factory import listen_orders, make_order
from tests.integration.payments_factory import make_topup, make_user
from tests.integration.risk_factory import set_kassa_limit

pytestmark = pytest.mark.asyncio
Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/payments/holds"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-hold-{uuid.uuid4()}"}


async def _held_topup(db: AsyncSession, amount: int = 50_000):
    await set_kassa_limit(db, "payme", 1)
    user = await make_user(db)
    t = await make_topup(db, user=user, amount=Decimal(amount))
    p = await ensure_attempt(db, payable=await resolve(db, t.number, lock=True), provider="payme")
    await db.commit()
    await settle(db, payment=p, event_id="e1")
    await db.commit()
    hold = await db.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    assert hold is not None
    return user, t, p, hold


async def test_list_open_holds(integration_client: AsyncClient, admin_headers: Headers,
                               db_session: AsyncSession) -> None:
    _, t, _, hold = await _held_topup(db_session)
    r = await integration_client.get(f"{BASE}?state=open", headers=await admin_headers())
    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if i["id"] == hold.id)
    assert (item["number"], item["kind"], item["reason"], item["amount_uzs"]) == (
        t.number, "topup", "kassa_limit", "50000")


async def test_release_topup_credits_and_audits(integration_client: AsyncClient,
                                                admin_headers: Headers,
                                                db_session: AsyncSession) -> None:
    user, t, _, hold = await _held_topup(db_session)
    r = await integration_client.post(f"{BASE}/{hold.id}/release",
                                      headers={**await admin_headers(), **_key()})
    assert r.status_code == 200 and r.json()["decision"] == "released"
    await db_session.refresh(t)
    assert t.status == "succeeded"
    assert await balance_uzs(db_session, user_id=user.id) == Decimal(50_000)
    audit = await db_session.scalar(select(AdminAuditLog)
                                    .where(AdminAuditLog.action == "payments.hold.release"))
    assert audit is not None


async def test_release_order_marks_paid_and_notifies(integration_client: AsyncClient,
                                                     admin_headers: Headers,
                                                     db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    order = await make_order(db_session)
    p = await ensure_attempt(db_session, payable=await resolve(db_session, order.number, lock=True),
                             provider="payme")
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    async with listen_orders() as heard:
        r = await integration_client.post(f"{BASE}/{hold.id}/release",
                                          headers={**await admin_headers(), **_key()})
    assert r.status_code == 200
    await db_session.refresh(order)
    assert order.status == "paid" and order.paid_at is not None
    assert heard == [order.number]


async def test_returned_topup_credits_nothing(integration_client: AsyncClient,
                                             admin_headers: Headers,
                                             db_session: AsyncSession) -> None:
    user, t, p, hold = await _held_topup(db_session)
    r = await integration_client.post(f"{BASE}/{hold.id}/returned",
                                      headers={**await admin_headers(), **_key()})
    assert r.status_code == 200 and r.json()["decision"] == "returned"
    await db_session.refresh(t)
    await db_session.refresh(p)
    assert (t.status, p.status) == ("rejected", "refunded")
    assert await balance_uzs(db_session, user_id=user.id) == Decimal(0)


async def test_returned_order_is_cancelled_with_its_kassa(integration_client: AsyncClient,
                                                         admin_headers: Headers,
                                                         db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    order = await make_order(db_session)
    p = await ensure_attempt(db_session, payable=await resolve(db_session, order.number, lock=True),
                             provider="payme")
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    r = await integration_client.post(f"{BASE}/{hold.id}/returned",
                                      headers={**await admin_headers(), **_key()})
    assert r.status_code == 200
    await db_session.refresh(order)
    assert (order.status, order.paid_with, order.paid_at) == ("cancelled", "payme", None)


async def test_second_decision_is_refused(integration_client: AsyncClient,
                                          admin_headers: Headers,
                                          db_session: AsyncSession) -> None:
    user, _, _, hold = await _held_topup(db_session)
    h = await admin_headers()
    assert (await integration_client.post(f"{BASE}/{hold.id}/release",
                                          headers={**h, **_key()})).status_code == 200
    r = await integration_client.post(f"{BASE}/{hold.id}/returned", headers={**h, **_key()})
    assert r.status_code == 409 and r.json()["code"] == "hold_decided"
    assert await balance_uzs(db_session, user_id=user.id) == Decimal(50_000)


async def test_replay_returns_the_same_answer(integration_client: AsyncClient,
                                              admin_headers: Headers,
                                              db_session: AsyncSession) -> None:
    _, _, _, hold = await _held_topup(db_session)
    h = {**await admin_headers(), **_key()}
    a = await integration_client.post(f"{BASE}/{hold.id}/release", headers=h)
    b = await integration_client.post(f"{BASE}/{hold.id}/release", headers=h)
    assert a.json() == b.json()


async def test_unknown_hold_is_404(integration_client: AsyncClient, admin_headers: Headers) -> None:
    r = await integration_client.post(f"{BASE}/{uuid.uuid4()}/release",
                                      headers={**await admin_headers(), **_key()})
    assert r.status_code == 404


async def test_customer_cannot_list(integration_client: AsyncClient,
                                    customer_headers: Headers) -> None:
    r = await integration_client.get(BASE, headers=await customer_headers())
    assert r.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_decide.py -q`
Expected: FAIL — 404 on every route (not mounted).

- [ ] **Step 3: Implement the decisions and the list in `payments/holds.py`**

```python
from datetime import datetime

from pydantic import BaseModel

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.api import record
from csmarket.modules.orders.api import mark_paid
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import credit_topup

PAGE = 50


class HoldUserOut(BaseModel):
    """A user as the holds page names them."""

    id: str
    display_name: str | None


class HoldOut(BaseModel):
    """One held payment and its decision."""

    id: str
    number: str
    kind: str
    provider: str
    amount_uzs: str
    reason: str
    window_sum_uzs: str | None
    limit_uzs: str | None
    user: HoldUserOut
    created_at: datetime
    decision: str | None
    decided_by: HoldUserOut | None
    decided_at: datetime | None


class HoldPage(BaseModel):
    """A page of holds, newest first."""

    items: list[HoldOut]
    next_cursor: str | None


async def _view(db: AsyncSession, row: PaymentHold) -> HoldOut:
    payment = await db.get_one(Payment, row.payment_id)
    user = await db.get_one(User, row.user_id)
    admin = await db.get(User, row.decided_by) if row.decided_by else None
    money = lambda v: wire_uzs(v) if v is not None else None  # noqa: E731
    return HoldOut(
        id=row.id, number=payment.number, kind=row.kind, provider=row.provider,
        amount_uzs=wire_uzs(row.amount_uzs), reason=row.reason,
        window_sum_uzs=money(row.window_sum_uzs), limit_uzs=money(row.limit_uzs),
        user=HoldUserOut(id=user.id, display_name=user.display_name),
        created_at=row.created_at, decision=row.decision,
        decided_by=HoldUserOut(id=admin.id, display_name=admin.display_name) if admin else None,
        decided_at=row.decided_at,
    )


async def list_holds(db: AsyncSession, *, state: str, cursor: str | None) -> HoldPage:
    """Open holds by ``created_at`` or decided ones by ``decided_at``, newest first."""
    at = PaymentHold.created_at if state == "open" else PaymentHold.decided_at
    q = select(PaymentHold).where(
        PaymentHold.decision.is_(None) if state == "open" else PaymentHold.decision.is_not(None)
    )
    if cursor is not None:
        c_at, c_id = decode_cursor(cursor)
        q = q.where((at < c_at) | ((at == c_at) & (PaymentHold.id < c_id)))
    rows = list((await db.execute(q.order_by(at.desc(), PaymentHold.id.desc())
                                  .limit(PAGE + 1))).scalars())
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    last = rows[-1] if more else None
    nxt = encode_cursor(getattr(last, "created_at" if state == "open" else "decided_at"), last.id) if last else None
    return HoldPage(items=[await _view(db, r) for r in rows], next_cursor=nxt)


async def _decidable(db: AsyncSession, hold_id: str) -> tuple[PaymentHold, Payment]:
    """Lock the owner, the payment and the hold (hooks' lock order) or refuse."""
    row = await db.get(PaymentHold, hold_id)
    if row is None:
        raise NotFoundError("no such hold", code="hold_not_found")
    payment = await db.get_one(Payment, row.payment_id)
    from csmarket.modules.payments.hooks import lock_owner_then_payment  # noqa: PLC0415 -- cycle
    owner = await lock_owner_then_payment(db, payment)
    await db.refresh(row, with_for_update=True)
    if row.decision is not None:
        raise ConflictError("the hold was already decided", code="hold_decided")
    return row, payment, owner  # type: ignore[return-value]  # see note below


async def release(db: AsyncSession, *, hold_id: str, admin_id: str) -> HoldOut:
    """«Пропустить»: credit the top-up or pay the order; audited."""
    row, payment, owner = await _decidable(db, hold_id)
    if isinstance(owner, Order):
        await mark_paid(db, owner, provider=payment.provider)
    else:
        owner.status = "succeeded"
        await credit_topup(db, user_id=owner.user_id, topup_id=owner.id,
                           amount=owner.amount_uzs, provider=payment.provider)
    close(row, decision="released", admin_id=admin_id)
    await record(db, actor_id=admin_id, action="payments.hold.release", target_type="payment_hold",
                 target_id=row.id, payload={"number": payment.number, "provider": row.provider,
                                            "amount_uzs": wire_uzs(row.amount_uzs)})
    await db.flush()
    log.info("payments.hold.released", number=payment.number, provider=row.provider)
    return await _view(db, row)


async def mark_returned(db: AsyncSession, *, hold_id: str, admin_id: str) -> HoldOut:
    """«Вернул на карту»: the admin returned the money in the kassa; nothing is credited."""
    row, payment, owner = await _decidable(db, hold_id)
    move_payment(payment, "refunded")
    if isinstance(owner, Order):
        move_order(owner, "cancelled")
    else:
        owner.status = "rejected"
    close(row, decision="returned", admin_id=admin_id)
    await record(db, actor_id=admin_id, action="payments.hold.returned", target_type="payment_hold",
                 target_id=row.id, payload={"number": payment.number, "provider": row.provider,
                                            "amount_uzs": wire_uzs(row.amount_uzs)})
    await db.flush()
    log.info("payments.hold.returned", number=payment.number, provider=row.provider)
    return await _view(db, row)
```

Type `_decidable` properly as `-> tuple[PaymentHold, Payment, WalletTopup | Order]` (drop the
`type: ignore`). Rename `hooks._lock_owner_then_payment` to the public
`lock_owner_then_payment` (keep a module-private alias is not needed — update its callers in
`hooks.py`). The local import breaks the `hooks → holds → hooks` import cycle; ruff's
`PLC0415` suppression names the reason.

- [ ] **Step 4: Routes**

`payments/holds_routes.py`:

```python
"""«На проверке»: the admin's list of held kassa payments and the two decisions."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.payments.holds import HoldOut, HoldPage, list_holds, mark_returned, release
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/payments/holds", tags=["admin"],
                   dependencies=[Depends(require_admin)])
Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@router.get("", response_model=HoldPage, summary="Held kassa payments")
async def get_holds(
    db: Db,
    state: Annotated[Literal["open", "decided"], Query()] = "open",
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> HoldPage:
    return await list_holds(db, state=state, cursor=cursor)


async def _decide(db: AsyncSession, *, scope: str, key: str, hold_id: str, admin: User,
                  act: str) -> HoldOut:
    request = {"hold_id": hold_id}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return HoldOut.model_validate(hit)
    fn = release if act == "release" else mark_returned
    out = await fn(db, hold_id=hold_id, admin_id=admin.id)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.post("/{hold_id}/release", response_model=HoldOut,
             responses={404: {"description": "`hold_not_found`"},
                        409: {"description": "`hold_decided` or `idempotency_mismatch`"}},
             summary="Release a held payment")
async def post_release(hold_id: str, admin: Admin, db: Db, key: Key) -> HoldOut:
    return await _decide(db, scope="admin.payments.hold.release", key=key, hold_id=hold_id,
                         admin=admin, act="release")


@router.post("/{hold_id}/returned", response_model=HoldOut,
             responses={404: {"description": "`hold_not_found`"},
                        409: {"description": "`hold_decided` or `idempotency_mismatch`"}},
             summary="Record a held payment returned to the card")
async def post_returned(hold_id: str, admin: Admin, db: Db, key: Key) -> HoldOut:
    return await _decide(db, scope="admin.payments.hold.returned", key=key, hold_id=hold_id,
                         admin=admin, act="returned")
```

Validate `hold_id` as a UUID before querying (copy `admin/users_service.get_user`'s check;
a malformed id → 404 `hold_not_found`).

`api/v1/router.py`: import `from csmarket.modules.payments.holds_routes import router as
payment_holds_router` and include it next to `payment_settings_router`, **before**
`admin_payments_router` (its `/{payment_id}` would otherwise read `holds`).

- [ ] **Step 5: Run**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_decide.py -q`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/api
git commit -m "feat(api/payments): the admin releases a hold or records it returned to the card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Kassa limits and the user policy in the admin API; the kassa block

**Files:**

- Create: `risk/limits.py`, `risk/policy.py`, `risk/schemas.py`, `risk/admin_routes.py`,
  `apps/api/tests/integration/test_risk_admin.py`, `apps/api/tests/integration/test_kassa_blocked.py`
- Modify: `core/errors.py` (add `KassaBlockedError`), `payments/topups.py` `create_topup`,
  `orders/paying.py` `pay_order`, `risk/api.py`, `api/v1/router.py`

**Interfaces:**

- Produces (wire):
  - `KassaLimitIn{provider: Literal["payme","click","uzum","p2p"], enabled: bool,
max_amount_uzs: int (1..1_000_000_000), window_hours: int (1..720)}`;
    `ReviewLimitsIn{limits: list[KassaLimitIn]}` (each provider at most once).
  - `KassaLimitOut{provider, enabled, max_amount_uzs: str, window_hours}`;
    `ReviewLimitsOut{limits: list[KassaLimitOut], updated_at: datetime | None,
updated_by: SettingsAuthorOut | None}` — `updated_at` is the newest row's, the `If-Match`
    version.
  - `GET/PUT /api/v1/admin/payments/review-limits` (PUT: idem key + `If-Match`; 409
    `settings_stale`); audit `payments.review_limits.update` with a field diff.
  - `RiskPolicyIn{trusted: bool, kassa_blocked: bool, max_amount_uzs: int | None
(1..1_000_000_000), window_hours: int (1..720), note: str | None (≤ 500)}`.
  - `RiskPolicyOut{...RiskPolicyIn fields with max_amount_uzs: str | None, updated_at,
updated_by, money_in_24h_uzs: str, money_in_7d_uzs: str, open_holds: int}`.
  - `GET/PUT /api/v1/admin/users/{user_id}/risk` (PUT: idem key); audit `users.risk.update`.
  - `risk.api.ensure_kassa_allowed(db, user_id: str) -> None` raises `KassaBlockedError`
    (403, `code="kassa_payment_blocked"`, `type_uri="https://csmarket.uz/errors/kassa-payment-blocked"`,
    `report = False`).

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/integration/test_risk_admin.py` — cover: GET review-limits returns the four
seeded rows at `"2000000"` / 24 / enabled (assert after re-running the seed — call
`set_kassa_limit` for each to restore if an earlier test cleared them); PUT changes Click to
`500000` / 12 / disabled and writes `payments.review_limits.update` audit with
`"max_amount_uzs": "2000000 -> 500000"`; PUT with a stale `If-Match` → 409 `settings_stale`;
PUT with a duplicate provider → 422; GET user risk for a user without a row → defaults
(`trusted false`, `kassa_blocked false`, `max_amount_uzs null`, `window_hours 24`) and
`money_in_24h_uzs` equal to a `succeeded_payment` made 2 h ago; PUT user risk sets all fields
and audits `users.risk.update`; a customer gets 403 on both.

```python
"""Admin API for kassa limits and a user's risk policy (spec 2026-10-21, «Admin»)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.admin.models import AdminAuditLog
from tests.integration.payments_factory import make_user
from tests.integration.risk_factory import set_kassa_limit, succeeded_payment

pytestmark = pytest.mark.asyncio
Headers = Callable[[], Awaitable[dict[str, str]]]
LIMITS = "/api/v1/admin/payments/review-limits"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-risk-{uuid.uuid4()}"}


async def _seed(db: AsyncSession) -> None:
    for p in ("payme", "click", "uzum", "p2p"):
        await set_kassa_limit(db, p, 2_000_000)


async def test_read_seeded_limits(integration_client: AsyncClient, admin_headers: Headers,
                                  db_session: AsyncSession) -> None:
    await _seed(db_session)
    r = await integration_client.get(LIMITS, headers=await admin_headers())
    assert r.status_code == 200
    got = {x["provider"]: x for x in r.json()["limits"]}
    assert set(got) == {"payme", "click", "uzum", "p2p"}
    assert got["click"] == {"provider": "click", "enabled": True,
                            "max_amount_uzs": "2000000", "window_hours": 24}


async def test_save_limits_audits_the_change(integration_client: AsyncClient,
                                             admin_headers: Headers,
                                             db_session: AsyncSession) -> None:
    await _seed(db_session)
    h = await admin_headers()
    version = (await integration_client.get(LIMITS, headers=h)).json()["updated_at"]
    body = {"limits": [{"provider": "click", "enabled": False, "max_amount_uzs": 500000,
                        "window_hours": 12}]}
    r = await integration_client.put(LIMITS, json=body,
                                     headers={**h, **_key(), "If-Match": version or "none"})
    assert r.status_code == 200
    click = next(x for x in r.json()["limits"] if x["provider"] == "click")
    assert click == {"provider": "click", "enabled": False, "max_amount_uzs": "500000",
                     "window_hours": 12}
    audit = await db_session.scalar(select(AdminAuditLog).where(
        AdminAuditLog.action == "payments.review_limits.update").order_by(
        AdminAuditLog.created_at.desc()))
    assert audit is not None and audit.payload["click.max_amount_uzs"] == "2000000 -> 500000"


async def test_stale_version_is_refused(integration_client: AsyncClient,
                                        admin_headers: Headers, db_session: AsyncSession) -> None:
    await _seed(db_session)
    body = {"limits": [{"provider": "payme", "enabled": True, "max_amount_uzs": 1,
                        "window_hours": 1}]}
    r = await integration_client.put(LIMITS, json=body, headers={
        **await admin_headers(), **_key(), "If-Match": "2000-01-01T00:00:00+00:00"})
    assert r.status_code == 409 and r.json()["code"] == "settings_stale"


async def test_duplicate_provider_is_422(integration_client: AsyncClient,
                                         admin_headers: Headers) -> None:
    row = {"provider": "payme", "enabled": True, "max_amount_uzs": 1, "window_hours": 1}
    r = await integration_client.put(LIMITS, json={"limits": [row, row]},
                                     headers={**await admin_headers(), **_key(), "If-Match": "none"})
    assert r.status_code == 422


async def test_user_policy_defaults_and_money_in(integration_client: AsyncClient,
                                                 admin_headers: Headers,
                                                 db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=300_000, hours_ago=2)
    r = await integration_client.get(f"/api/v1/admin/users/{user.id}/risk",
                                     headers=await admin_headers())
    body = r.json()
    assert (body["trusted"], body["kassa_blocked"], body["max_amount_uzs"],
            body["window_hours"]) == (False, False, None, 24)
    assert body["money_in_24h_uzs"] == "300000" and body["open_holds"] == 0


async def test_user_policy_save_audits(integration_client: AsyncClient,
                                       admin_headers: Headers, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    body = {"trusted": False, "kassa_blocked": True, "max_amount_uzs": 1_000_000,
            "window_hours": 72, "note": "chargeback 2026-10-21"}
    r = await integration_client.put(f"/api/v1/admin/users/{user.id}/risk", json=body,
                                     headers={**await admin_headers(), **_key()})
    assert r.status_code == 200
    assert (r.json()["kassa_blocked"], r.json()["max_amount_uzs"]) == (True, "1000000")
    audit = await db_session.scalar(select(AdminAuditLog).where(
        AdminAuditLog.action == "users.risk.update", AdminAuditLog.target_id == user.id))
    assert audit is not None


async def test_customer_is_refused(integration_client: AsyncClient,
                                   customer_headers: Headers) -> None:
    assert (await integration_client.get(LIMITS, headers=await customer_headers())).status_code == 403
```

`apps/api/tests/integration/test_kassa_blocked.py`: a blocked user gets 403
`kassa_payment_blocked` from `POST /api/v1/wallet/topups` with provider `payme` and with
`p2p`, and from paying an order with `payme` (use the order pay route the existing
`test_payments_orders_payme.py` uses); paying the same order from the balance
(`provider: "wallet"`, with a funded balance) still succeeds; an unblocked user is unaffected.
Use `dev_login_headers(c, steam_id=user.steam_id, admin=False)` to act as that user (see
`conftest.py:347`).

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && uv run pytest tests/integration/test_risk_admin.py tests/integration/test_kassa_blocked.py -q`
Expected: FAIL — 404 (routes absent) / top-ups not refused.

- [ ] **Step 3: Implement `risk/schemas.py`, `risk/limits.py`, `risk/policy.py`**

`risk/schemas.py`:

```python
"""Admin wire models for kassa limits and a user's risk policy."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Kassa = Literal["payme", "click", "uzum", "p2p"]
Amount = Annotated[int, Field(ge=1, le=1_000_000_000)]
Window = Annotated[int, Field(ge=1, le=720)]


class AuthorOut(BaseModel):
    """Who saved."""

    id: str
    display_name: str | None


class KassaLimitIn(BaseModel):
    """One kassa's limit as the admin saves it."""

    model_config = ConfigDict(extra="forbid")
    provider: Kassa
    enabled: bool
    max_amount_uzs: Amount
    window_hours: Window


class ReviewLimitsIn(BaseModel):
    """The kassas to save; one row per kassa at most."""

    model_config = ConfigDict(extra="forbid")
    limits: Annotated[list[KassaLimitIn], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def _unique(self) -> ReviewLimitsIn:
        names = [x.provider for x in self.limits]
        if len(names) != len(set(names)):
            raise ValueError("each kassa at most once")
        return self


class KassaLimitOut(BaseModel):
    """One kassa's limit."""

    provider: str
    enabled: bool
    max_amount_uzs: str
    window_hours: int


class ReviewLimitsOut(BaseModel):
    """Every kassa's limit; ``updated_at`` is the version for ``If-Match``."""

    limits: list[KassaLimitOut]
    updated_at: datetime | None
    updated_by: AuthorOut | None


class RiskPolicyIn(BaseModel):
    """A user's policy as the admin saves it."""

    model_config = ConfigDict(extra="forbid")
    trusted: bool
    kassa_blocked: bool
    max_amount_uzs: Amount | None
    window_hours: Window = 24
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class RiskPolicyOut(BaseModel):
    """A user's policy and their recent kassa money, for the user card."""

    trusted: bool
    kassa_blocked: bool
    max_amount_uzs: str | None
    window_hours: int
    note: str | None
    updated_at: datetime | None
    updated_by: AuthorOut | None
    money_in_24h_uzs: str
    money_in_7d_uzs: str
    open_holds: int
```

`risk/limits.py`:

```python
"""Kassa limits: the admin's read and audited save (``If-Match`` like «Настройки оплаты»)."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, ValidationError
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.api import AuditPayload, record
from csmarket.modules.risk.models import KassaReviewLimit
from csmarket.modules.risk.schemas import AuthorOut, KassaLimitOut, ReviewLimitsIn, ReviewLimitsOut
from csmarket.modules.users.api import User


async def _version(db: AsyncSession) -> datetime | None:
    return await db.scalar(select(func.max(KassaReviewLimit.updated_at)))


async def limits_view(db: AsyncSession) -> ReviewLimitsOut:
    """Every kassa's limit, the newest save and its author."""
    rows = list((await db.execute(select(KassaReviewLimit)
                                  .order_by(KassaReviewLimit.provider))).scalars())
    newest = max(rows, key=lambda r: r.updated_at, default=None)
    author = None
    if newest is not None and newest.updated_by is not None:
        user = await db.get(User, newest.updated_by)
        if user is not None:
            author = AuthorOut(id=user.id, display_name=user.display_name)
    return ReviewLimitsOut(
        limits=[KassaLimitOut(provider=r.provider, enabled=r.enabled,
                              max_amount_uzs=wire_uzs(r.max_amount_uzs),
                              window_hours=r.window_hours) for r in rows],
        updated_at=newest.updated_at if newest else None, updated_by=author,
    )


def _stale(at: datetime | None, expected: str) -> bool:
    seen = expected.strip().strip('"')
    if seen.lower() == "none":
        return at is not None
    try:
        return at is None or at != datetime.fromisoformat(seen)
    except ValueError as exc:
        raise ValidationError("If-Match is not a version", code="if_match") from exc


def _plain(row: KassaReviewLimit | None) -> dict[str, object]:
    if row is None:
        return {}
    return {"enabled": row.enabled, "max_amount_uzs": wire_uzs(row.max_amount_uzs),
            "window_hours": row.window_hours}


async def save_limits(
    db: AsyncSession, *, body: ReviewLimitsIn, admin_id: str, expected: str | None
) -> None:
    """Upsert the given kassas' limits; refuse a stale tab; audit the changed fields."""
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext("risk:kassa_limits"))))
    if expected is not None and _stale(await _version(db), expected):
        raise ConflictError("the limits were saved by someone else", code="settings_stale")
    diff: AuditPayload = {}
    stamp = now()
    for item in body.limits:
        row = await db.get(KassaReviewLimit, item.provider, with_for_update=True)
        before = _plain(row)
        if row is None:
            row = KassaReviewLimit(provider=item.provider)
            db.add(row)
        row.enabled = item.enabled
        row.max_amount_uzs = Decimal(item.max_amount_uzs)
        row.window_hours = item.window_hours
        row.updated_by = admin_id
        row.updated_at = stamp
        for field, value in _plain(row).items():
            if before.get(field) != value:
                diff[f"{item.provider}.{field}"] = (
                    f"{json.dumps(before.get(field))} -> {json.dumps(value)}".replace('"', "")
                )
    await db.flush()
    await record(db, actor_id=admin_id, action="payments.review_limits.update",
                 target_type="kassa_review_limits", target_id="all",
                 payload=diff or {"unchanged": "true"})
```

`risk/policy.py`:

```python
"""A user's risk policy: the admin's read and save, and the kassa block at payment start."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import KassaBlockedError
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.api import record
from csmarket.modules.risk.models import PaymentHold, UserRiskPolicy
from csmarket.modules.risk.rule import money_in
from csmarket.modules.risk.schemas import AuthorOut, RiskPolicyIn, RiskPolicyOut
from csmarket.modules.users.api import User


async def ensure_kassa_allowed(db: AsyncSession, user_id: str) -> None:
    """Refuse to start a kassa payment for a user the admin blocked.

    Raises:
        KassaBlockedError: the user's policy has ``kassa_blocked``.
    """
    blocked = await db.scalar(select(UserRiskPolicy.kassa_blocked)
                              .where(UserRiskPolicy.user_id == user_id))
    if blocked:
        raise KassaBlockedError("kassa payments are blocked for this account",
                                code="kassa_payment_blocked")


async def policy_view(db: AsyncSession, user_id: str) -> RiskPolicyOut:
    """The policy (defaults when none) and the user's recent kassa money."""
    row = await db.get(UserRiskPolicy, user_id, populate_existing=True)
    author = None
    if row is not None and row.updated_by is not None:
        admin = await db.get(User, row.updated_by)
        if admin is not None:
            author = AuthorOut(id=admin.id, display_name=admin.display_name)
    holds = await db.scalar(select(func.count()).select_from(PaymentHold).where(
        PaymentHold.user_id == user_id, PaymentHold.decision.is_(None)))
    return RiskPolicyOut(
        trusted=row.trusted if row else False,
        kassa_blocked=row.kassa_blocked if row else False,
        max_amount_uzs=wire_uzs(row.max_amount_uzs) if row and row.max_amount_uzs else None,
        window_hours=row.window_hours if row else 24,
        note=row.note if row else None,
        updated_at=row.updated_at if row else None, updated_by=author,
        money_in_24h_uzs=wire_uzs(await money_in(db, user_id=user_id, hours=24)),
        money_in_7d_uzs=wire_uzs(await money_in(db, user_id=user_id, hours=24 * 7)),
        open_holds=int(holds or 0),
    )


async def save_policy(db: AsyncSession, *, user_id: str, body: RiskPolicyIn, admin_id: str) -> None:
    """Upsert the user's policy and audit it (the note is the admin's reason)."""
    row = await db.get(UserRiskPolicy, user_id, with_for_update=True)
    if row is None:
        row = UserRiskPolicy(user_id=user_id)
        db.add(row)
    row.trusted = body.trusted
    row.kassa_blocked = body.kassa_blocked
    row.max_amount_uzs = Decimal(body.max_amount_uzs) if body.max_amount_uzs else None
    row.window_hours = body.window_hours
    row.note = body.note
    row.updated_by = admin_id
    row.updated_at = now()
    await db.flush()
    await record(db, actor_id=admin_id, action="users.risk.update", target_type="user",
                 target_id=user_id, payload={
                     "trusted": body.trusted, "kassa_blocked": body.kassa_blocked,
                     "max_amount_uzs": str(body.max_amount_uzs) if body.max_amount_uzs else None,
                     "window_hours": body.window_hours, "note": body.note,
                 })
```

`core/errors.py`, after `AccountSuspendedError`:

```python
class KassaBlockedError(AppError):
    """The admin blocked kassa payments for this account; the balance still pays."""

    status_code = 403
    type_uri = "https://csmarket.uz/errors/kassa-payment-blocked"
    title = "Kassa payments blocked"
    report = False
```

- [ ] **Step 4: Routes and the block**

`risk/admin_routes.py`:

```python
"""Admin routes: kassa limits («Лимит без проверки») and a user's risk policy."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import NotFoundError
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.risk.limits import limits_view, save_limits
from csmarket.modules.risk.policy import policy_view, save_policy
from csmarket.modules.risk.schemas import RiskPolicyIn, RiskPolicyOut, ReviewLimitsIn, ReviewLimitsOut
from csmarket.modules.users.api import User

limits_router = APIRouter(prefix="/admin/payments/review-limits", tags=["admin"],
                          dependencies=[Depends(require_admin)])
policy_router = APIRouter(prefix="/admin/users", tags=["admin"],
                          dependencies=[Depends(require_admin)])
Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@limits_router.get("", response_model=ReviewLimitsOut, summary="The kassa limits")
async def get_limits(db: Db) -> ReviewLimitsOut:
    return await limits_view(db)


@limits_router.put("", response_model=ReviewLimitsOut,
                   responses={409: {"description": "`settings_stale` or `idempotency_mismatch`"}},
                   summary="Save the kassa limits")
async def put_limits(
    body: ReviewLimitsIn, admin: Admin, db: Db, key: Key,
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=64)] = None,
) -> ReviewLimitsOut:
    scope, request = "admin.payments.review_limits", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return ReviewLimitsOut.model_validate(hit)
    await save_limits(db, body=body, admin_id=admin.id, expected=if_match)
    out = await limits_view(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


async def _user(db: AsyncSession, user_id: str) -> User:
    from csmarket.modules.admin.users_service import get_user  # noqa: PLC0415 -- admin imports risk
    found: User = await get_user(db, user_id)
    if found is None:
        raise NotFoundError("no such user")
    return found


@policy_router.get("/{user_id}/risk", response_model=RiskPolicyOut, summary="A user's risk policy")
async def get_policy(user_id: str, db: Db) -> RiskPolicyOut:
    user = await _user(db, user_id)
    return await policy_view(db, user.id)


@policy_router.put("/{user_id}/risk", response_model=RiskPolicyOut, summary="Save a user's risk policy")
async def put_policy(user_id: str, body: RiskPolicyIn, admin: Admin, db: Db, key: Key) -> RiskPolicyOut:
    user = await _user(db, user_id)
    scope, request = "admin.users.risk", {"user_id": user.id, **body.model_dump(mode="json")}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return RiskPolicyOut.model_validate(hit)
    await save_policy(db, user_id=user.id, body=body, admin_id=admin.id)
    out = await policy_view(db, user.id)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out
```

(If `admin.users_service` does not import `risk`, import `get_user` at the top and drop the
local-import comment.)

`api/v1/router.py`: include `limits_router` before `admin_payments_router` (with the holds
router), and `policy_router` after `admin_users_router` (paths do not clash:
`/{user_id}/risk` is two segments).

Add `ensure_kassa_allowed` to `risk/api.py`. Call it:

- `payments/topups.py` `create_topup`: after the idempotent replay lookup and before
  `kassa_for_new_topup(provider)` — `await ensure_kassa_allowed(db, user_id)`.
- `orders/paying.py` `pay_order`: in the non-`WALLET` branch, before `_open_in_kassa(...)`.

Map `kassa_payment_blocked` in the storefront error text — Task 9.

- [ ] **Step 5: Run**

Run: `cd apps/api && uv run pytest tests/integration/test_risk_admin.py tests/integration/test_kassa_blocked.py tests/integration/test_payment_holds_decide.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api
git commit -m "feat(api/risk): admin kassa limits, a user's risk policy and the kassa block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Gauge, scheduler job, alert, dashboard counter

**Files:**

- Modify: `core/metrics.py`, `admin/dashboard_schemas.py`, `admin/dashboard_routes.py`,
  `apps/scheduler/src/csmarket_scheduler/main.py`, `infra/prometheus/alerts/payments.yml`
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/payment_holds.py`,
  `apps/scheduler/tests/test_payment_holds_job.py`, add a payments.holds counter function
- Test: extend `test_payment_holds_decide.py` with a dashboard assertion

**Interfaces:**

- Produces: `PAYMENT_HOLDS_OPEN` Gauge `csmarket_payment_holds_open{reason}`;
  `set_payment_holds_open(reason: HoldReason, count: int) -> None`;
  `payments.holds.open_counts(db) -> dict[HoldReason, int]` (every reason present, 0 default);
  `DashboardOut.holds_open: int`.

- [ ] **Step 1: Failing tests**

Add to `test_payment_holds_decide.py`:

```python
async def test_open_counts_and_dashboard(integration_client: AsyncClient, admin_headers: Headers,
                                         db_session: AsyncSession) -> None:
    from csmarket.modules.payments.holds import open_counts
    await _held_topup(db_session)
    counts = await open_counts(db_session)
    assert counts["kassa_limit"] >= 1 and counts["check_failed"] == 0
    r = await integration_client.get("/api/v1/admin/dashboard?days=1", headers=await admin_headers())
    assert r.json()["holds_open"] >= 1
```

(Use the dashboard URL and query the existing dashboard tests use.)

`apps/scheduler/tests/test_payment_holds_job.py` — copy the shape of the existing job test
(e.g. `test_orders_health*.py`): patch `get_session_factory` and `open_counts` to return
`{"kassa_limit": 2, "user_limit": 0, "check_failed": 1}`, run `run()`, assert the gauge's
samples (`REGISTRY.get_sample_value("csmarket_payment_holds_open", {"reason": "kassa_limit"}) == 2`);
a raising `open_counts` is logged, not raised.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_holds_decide.py::test_open_counts_and_dashboard -q && cd ../scheduler && uv run pytest tests/test_payment_holds_job.py -q`
Expected: FAIL — `ImportError: open_counts`.

- [ ] **Step 3: Implement**

`payments/holds.py`:

```python
from sqlalchemy import func
from typing import get_args
from csmarket.modules.risk.api import HoldReason


async def open_counts(db: AsyncSession) -> dict[HoldReason, int]:
    """How many holds are open, by reason (every reason present)."""
    rows = await db.execute(select(PaymentHold.reason, func.count())
                            .where(PaymentHold.decision.is_(None)).group_by(PaymentHold.reason))
    found = {r: n for r, n in rows.all()}
    return {r: int(found.get(r, 0)) for r in get_args(HoldReason)}
```

Export `open_counts` from `payments/api.py`.

`core/metrics.py` (beside `SALE_ATTENTION_OPEN`):

```python
PAYMENT_HOLDS_OPEN = Gauge(
    "csmarket_payment_holds_open",
    "Kassa payments held for an admin, by reason (alert: PaymentHeldForReview; set by the "
    "scheduler's payment_holds job).",
    ("reason",),
)


def set_payment_holds_open(reason: str, count: int) -> None:
    """Set how many held payments are open for ``reason``. Never raises."""
    try:
        PAYMENT_HOLDS_OPEN.labels(reason=reason).set(count)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning("metrics.set_failed", metric="csmarket_payment_holds_open",
                    error=type(exc).__name__)
```

`apps/scheduler/src/csmarket_scheduler/jobs/payment_holds.py` (copy `topup_expiry.py`'s shape):

```python
"""Export the open payment holds as a gauge every minute (alert PaymentHeldForReview)."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_payment_holds_open
from csmarket.modules.payments.api import open_counts
from csmarket_scheduler.startup import first_run_after

JOB_ID = "payment_holds"
log = get_logger("csmarket.scheduler.payment_holds")


async def run() -> None:
    """Count open holds and set the gauge; a failure is logged."""
    try:
        async with get_session_factory()() as db:
            counts = await open_counts(db)
        for reason, n in counts.items():
            set_payment_holds_open(reason, n)
    except Exception:  # noqa: BLE001 -- a job never crashes the scheduler
        log.exception("scheduler.payment_holds.crashed")


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 60 s, first run after 50 s."""
    scheduler.add_job(run, trigger="interval", seconds=60, id=JOB_ID,
                      next_run_time=first_run_after(50), replace_existing=True,
                      coalesce=True, max_instances=1)
```

Pick a `first_run_after` offset ≥ 15 s apart from the other jobs' (check `main.py`); register
it in `build_scheduler`.

`infra/prometheus/alerts/payments.yml` — add:

```yaml
- alert: PaymentHeldForReview
  expr: max by (reason) (csmarket_payment_holds_open{job="scheduler"}) > 0
  for: 1m
  labels: { severity: page }
  annotations:
    summary: '{{ $value | printf "%.0f" }} kassa payment(s) held for review ({{ $labels.reason }})'
    description: >
      Money arrived through a kassa above a risk limit and waits for an admin:
      «На проверке» in the admin — release it or return it to the card.
    runbook: "https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/payment-held-for-review.md"
```

Run `promtool check rules infra/prometheus/alerts/payments.yml` if available (or the repo's
alert-lint target).

`admin/dashboard_schemas.py`: add `holds_open: int = 0` to `DashboardOut` and pass it through
`of(...)`; `admin/dashboard_routes.py`: `holds_open=sum((await open_counts(db)).values())`.

- [ ] **Step 4: Run**

Run the two commands of Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api apps/scheduler infra/prometheus
git commit -m "feat(api/payments): the open holds gauge, its alert and the dashboard counter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: OpenAPI and the generated client

- [ ] **Step 1:** Run `make gen-api`. Expected: `docs/api/openapi.json` and `packages/api-client`
      change (new routes, `held` / `rejected` in the status enums).
- [ ] **Step 2:** Run `pnpm -w typecheck` (or `make typecheck`). Expected: TS errors only in the
      exhaustive switches listed in Tasks 9–10 (that is their RED); Python mypy clean.
- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.json packages/api-client
git commit -m "docs(api): regenerate OpenAPI for payment holds and risk limits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Storefront — «Оплата получена, проверяем платёж»

**Files:**

- Modify: `apps/web/src/lib/balance.ts:22`, `components/balance/TopupStatus.tsx`,
  `lib/orders.ts:16`, `lib/trade-status.ts`, `components/order/OrderView.tsx:210-243`, the
  top-up and order-pay error-code → message maps (find with
  `grep -rn "provider_maintenance" apps/web/src`), `packages/i18n/locales/{ru,uz,en}/web.json`
- Test: `components/balance/TopupStatus.test.tsx`, `components/order/OrderView.test.tsx`
  (extend the existing ones; create beside the component if absent)

- [ ] **Step 1: Failing tests**

```tsx
// TopupStatus.test.tsx — add
it("shows a held top-up as being checked, without the kassa link", () => {
  renderTopup({ ...TOPUP, status: "held", intent_url: null });
  expect(screen.getByText("Оплата получена, проверяем платёж.")).toBeInTheDocument();
});
it("shows a rejected top-up as returned to the card", () => {
  renderTopup({ ...TOPUP, status: "rejected", intent_url: null });
  expect(screen.getByText("Платёж отменён, деньги возвращены на карту.")).toBeInTheDocument();
});

// OrderView.test.tsx — add
it("shows a held order as being checked and no trade card", () => {
  renderOrder({ ...ORDER, status: "held", paid_with: "payme", paid_at: null, trade: null });
  expect(screen.getByText("Оплата получена, проверяем платёж.")).toBeInTheDocument();
  expect(screen.queryByTestId("trade-countdown")).toBeNull();
});
it("shows a cancelled order paid by a kassa as returned to the card", () => {
  renderOrder({ ...ORDER, status: "cancelled", paid_with: "payme", paid_at: null });
  expect(screen.getByText("Платёж отменён, деньги возвращены на карту.")).toBeInTheDocument();
});
```

(Use the existing render helpers / fixtures in those test files; if the countdown has no test
id, assert the absence of the countdown's text instead.)

Run: `pnpm --filter @csmarket/web test TopupStatus OrderView` — Expected: FAIL (types and texts).

- [ ] **Step 2: i18n** — in all three `web.json`:

| key                                                                                | ru                                                                  | uz                                                                 | en                                                                      |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `web.balance.topup.held`                                                           | Оплата получена, проверяем платёж.                                  | Toʻlov qabul qilindi, tekshiryapmiz.                               | Payment received, we are checking it.                                   |
| `web.balance.topup.rejected`                                                       | Платёж отменён, деньги возвращены на карту.                         | Toʻlov bekor qilindi, pul kartaga qaytarildi.                      | Payment cancelled, the money is back on your card.                      |
| `web.orders.held`                                                                  | Оплата получена, проверяем платёж.                                  | Toʻlov qabul qilindi, tekshiryapmiz.                               | Payment received, we are checking it.                                   |
| `web.orders.returnedToCard`                                                        | Платёж отменён, деньги возвращены на карту.                         | Toʻlov bekor qilindi, pul kartaga qaytarildi.                      | Payment cancelled, the money is back on your card.                      |
| `web.orders.status.held`                                                           | На проверке                                                         | Tekshiruvda                                                        | Under review                                                            |
| error `kassa_payment_blocked` (in the namespace the other payment error codes use) | Оплата картой недоступна для вашего аккаунта. Напишите в поддержку. | Hisobingiz uchun karta orqali toʻlov mavjud emas. Yordamga yozing. | Card payment is not available for your account. Please contact support. |

- [ ] **Step 3: Code**

- `lib/balance.ts`: `export type TopupStatus = "pending" | "succeeded" | "expired" | "reversed" | "held" | "rejected";`
- `TopupStatus.tsx`: `type View = … | "held" | "rejected"`; `viewOf` returns `topup.status`
  for them; `isOpen` treats `held` as open (keeps polling); in the main switch:
  `case "held": return <Outcome view="held" title={t("topup.held")} />;`
  `case "rejected": return <Outcome view="rejected" title={t("topup.rejected")} />;`; icon switch:
  `held` → the same icon as `checking`, `rejected` → the same as `reversed`.
- `lib/orders.ts`: add `"held"` to `OrderStatus`. `lib/order-poll.ts`: leave `held` out of
  TERMINAL (polling continues until the decision).
- `lib/trade-status.ts` `orderBadge`: `case "held": return { tone: "wait", key: "orders.status.held" };`
- `OrderView.tsx` `OrderBody`:

```tsx
      case "held":
        return <p className="text-lg font-semibold">{t("held")}</p>;
      case "cancelled":
        return (
          <p className="text-lg font-semibold">
            {t(order.paid_at !== null ? "cancelled" : order.paid_with !== null ? "returnedToCard" : "expired")}
          </p>
        );
```

- Error map: add `kassa_payment_blocked` → the new key, wherever `provider_maintenance` is mapped.

- [ ] **Step 4: Run** `pnpm --filter @csmarket/web test TopupStatus OrderView && pnpm --filter @csmarket/web typecheck && pnpm --filter @csmarket/i18n test` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web packages/i18n
git commit -m "feat(web/balance): a held payment reads «Оплата получена, проверяем платёж»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Admin — limits block, «На проверке», user risk block

**Files:**

- Create: `apps/admin/src/features/payments/ReviewLimitsBlock.tsx` (+ `.test.tsx`),
  `features/payments/HoldsPage.tsx` (+ `.test.tsx`), `features/users/RiskBlock.tsx` (+ `.test.tsx`)
- Modify: `features/payments/api.ts`, `features/payments/FeeSettingsPage.tsx`,
  `features/users/api.ts`, `features/users/UserCard.tsx`, `features/users/labels.ts:54-63`,
  `features/users/TopupStatusChip.tsx`, `features/orders/kinds.ts`, `features/orders/labels.ts`,
  `features/dashboard/api.ts`, `app/Layout.tsx`, `app/router.tsx`

**Interfaces:**

- Consumes: the wire models of Tasks 5–7.

- [ ] **Step 1: Labels for the new statuses (fixes the TS errors from Task 8)**

- `users/labels.ts` `TOPUP_STATUSES`: `held: "на проверке"`, `rejected: "возвращено на карту"`.
- `users/TopupStatusChip.tsx` TONES: `held: "progress"`, `rejected: "muted"`.
- `orders/kinds.ts`: add `"held"` after `"pending"`; `orders/labels.ts`: `STATUS_LABELS.held =
"На проверке"`, `STATUS_TONE.held = "progress"`.
- `payments/api.ts` and `users/api.ts` `TopupStatus` unions: add `"held" | "rejected"`.
- Add `HOLD_REASON_LABELS` to `payments/labels.ts`: `kassa_limit: "Лимит кассы"`,
  `user_limit: "Лимит пользователя"`, `check_failed: "Проверка не сработала"`; and
  `HOLD_DECISION_LABELS`: `released: "Пропущен"`, `returned: "Возвращён на карту"`,
  `reversed_by_kassa: "Отменён кассой"`.

- [ ] **Step 2: API client functions** (`features/payments/api.ts`):

```ts
export interface KassaLimit {
  provider: string;
  enabled: boolean;
  max_amount_uzs: string;
  window_hours: number;
}
export interface ReviewLimitsOut {
  limits: KassaLimit[];
  updated_at: string | null;
  updated_by: { id: string; display_name: string | null } | null;
}
export interface KassaLimitIn {
  provider: string;
  enabled: boolean;
  max_amount_uzs: number;
  window_hours: number;
}
export type HoldReason = "kassa_limit" | "user_limit" | "check_failed";
export type HoldDecision = "released" | "returned" | "reversed_by_kassa";
export interface HoldUser {
  id: string;
  display_name: string | null;
}
export interface Hold {
  id: string;
  number: string;
  kind: "topup" | "order";
  provider: string;
  amount_uzs: string;
  reason: HoldReason;
  window_sum_uzs: string | null;
  limit_uzs: string | null;
  user: HoldUser;
  created_at: string;
  decision: HoldDecision | null;
  decided_by: HoldUser | null;
  decided_at: string | null;
}
export interface HoldPage {
  items: Hold[];
  next_cursor: string | null;
}

export const getReviewLimits = (): Promise<ReviewLimitsOut> =>
  session.apiGet<ReviewLimitsOut>(`${BASE}/review-limits`);
export function saveReviewLimits(
  limits: KassaLimitIn[],
  version: string | null,
  key: string,
): Promise<ReviewLimitsOut> {
  return session.api<ReviewLimitsOut>(`${BASE}/review-limits`, {
    method: "PUT",
    body: { limits },
    idempotencyKey: key,
    headers: { "If-Match": version ?? "none" },
  });
}
export const getHolds = (state: "open" | "decided", cursor: string | null): Promise<HoldPage> =>
  session.apiGet<HoldPage>(
    `${BASE}/holds?state=${state}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
export const decideHold = (id: string, act: "release" | "returned", key: string): Promise<Hold> =>
  session.apiPost<Hold>(
    `${BASE}/holds/${encodeURIComponent(id)}/${act}`,
    {},
    { idempotencyKey: key },
  );
```

`features/users/api.ts`:

```ts
export interface RiskPolicy {
  trusted: boolean;
  kassa_blocked: boolean;
  max_amount_uzs: string | null;
  window_hours: number;
  note: string | null;
  updated_at: string | null;
  updated_by: { id: string; display_name: string | null } | null;
  money_in_24h_uzs: string;
  money_in_7d_uzs: string;
  open_holds: number;
}
export interface RiskPolicyIn {
  trusted: boolean;
  kassa_blocked: boolean;
  max_amount_uzs: number | null;
  window_hours: number;
  note: string | null;
}
export const getRisk = (id: string): Promise<RiskPolicy> =>
  session.apiGet<RiskPolicy>(`${BASE}/${encodeURIComponent(id)}/risk`);
export const saveRisk = (id: string, body: RiskPolicyIn, key: string): Promise<RiskPolicy> =>
  session.apiPut<RiskPolicy>(`${BASE}/${encodeURIComponent(id)}/risk`, body, {
    idempotencyKey: key,
  });
```

- [ ] **Step 3: Failing component tests**

- `ReviewLimitsBlock.test.tsx`: renders four rows from a mocked `getReviewLimits` (Payme, Click,
  Uzum, «Перевод на карту (P2P)»); changing Click's sum to 500000 and pressing «Сохранить»
  calls `saveReviewLimits` with `[{provider:"click", enabled:true, max_amount_uzs:500000,
window_hours:24}, …]` and the version; a 409 `settings_stale` shows the stale text.
- `HoldsPage.test.tsx`: lists a mocked open hold (number, «Лимит кассы», «1 500 000 сум»,
  the user's name linking to `/users/<id>`); «Пропустить» → confirm dialog → `decideHold(id,
"release", key)` → the row leaves the open list; «Вернул на карту» likewise with
  `"returned"`; the «Решённые» tab calls `getHolds("decided", null)`.
- `RiskBlock.test.tsx`: shows «Внесено через кассы: 24 ч … / 7 дней …»; toggling «Запретить
  оплату кассой», typing a limit and a note, pressing «Сохранить» calls `saveRisk` with
  `{trusted:false, kassa_blocked:true, max_amount_uzs:1000000, window_hours:24, note:"…"}`; an
  empty limit field sends `max_amount_uzs: null`.

Mock the api modules with `vi.mock("./api", …)` as `FeeSettingsPage.test.tsx` does.
Run: `pnpm --filter @csmarket/admin test ReviewLimitsBlock HoldsPage RiskBlock` — Expected: FAIL (files absent).

- [ ] **Step 4: Components**

`ReviewLimitsBlock.tsx` — a `<section className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4">`
titled «Лимит без проверки», subtitle «Сколько один пользователь может провести через кассу
за окно. Свыше — платёж ждёт решения в «На проверке».», one row per kassa from `SWITCHED`'s
names: a checkbox «Включён», `NumberField` «Сумма, сум», `NumberField` «Окно, ч»; draft state,
`useIdempotencyKey("admin-review-limits")`, mutation as in `FeeSettingsPage`
(`saveReviewLimits(rows, version, key.keyFor(JSON.stringify(rows)))`, `onSuccess` resets the
key and sets the query data), `SavedNotice`, errors through `errorText`. Render it in
`FeeSettingsPage.tsx` below the fee sections.

`HoldsPage.tsx` — `PageHeader` «На проверке»; `Tabs` (segmented) «Открытые» / «Решённые»;
`useInfiniteQuery` on `["admin","payments","holds",state]` with `getHolds(state, cursor)`; a
table: number (link to `/payments` search by number), kind («Пополнение» / «Заказ»), kassa,
amount, reason label, «за окно: {window_sum} из {limit}», user link, created_at; for open rows
two buttons, each opening a confirm dialog («Пропустить платёж {number}? Пополнение будет
зачислено / заказ уйдёт в покупку.» and «Вы вернули {amount} на карту в кабинете кассы? На
баланс ничего не зачислится.»), with `useIdempotencyKey(`admin-hold-${act}`)`; on success
invalidate both lists and the dashboard query (`DASHBOARD_KEY`). Decided rows show the
decision label, who and when.

`RiskBlock.tsx` — a self-fetching `<Section title="Риск">` on `["admin","users","risk",id]`
showing the two money-in figures and open holds, checkboxes «Доверенный (без лимитов)» and
«Запретить оплату кассой», `NumberField` «Личный лимит, сум» (empty = нет), «Окно, ч», a
textarea «Заметка», «Сохранить» with `useIdempotencyKey("admin-user-risk")`. Put it in
`UserCard.tsx` `Overview` `side`, after `<UsdBlock/>`.

Router: `{ path: "/payment-holds", element: <HoldsPage /> }` (a top-level path avoids the
`/payments/:id` clash). Layout: `NAV` entry `{ to: "/payment-holds", label: "На проверке",
counter: "holds" }`; `type Counter = … | "holds"`; `COUNTER_LABEL.holds = "Платежи на проверке"`;
`useCounters` returns `holds: query.data?.holds_open ?? 0`. `dashboard/api.ts`
`DashboardOut`: `holds_open?: number`.

- [ ] **Step 5: Run** `pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin typecheck && pnpm --filter @csmarket/admin lint` — Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/admin
git commit -m "feat(admin/payments): kassa limits, «На проверке» and a user's risk block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Docs, coverage gate, AGENTS.md

**Files:**

- Create: `docs/decisions/0022-payment-risk-holds.md`, `apps/api/src/csmarket/modules/risk/README.md`,
  `docs/architecture/sequence-diagrams/payment-hold.mmd`, `docs/runbooks/payment-held-for-review.md`,
  `docs/product/flows/payment-hold.md`
- Modify: `docs/architecture/module-map.md`, `docs/api/README.md`, `docs/architecture/metrics.md`,
  `apps/api/src/csmarket/modules/payments/README.md`, `scripts/check-module-coverage.py`
  (+ its unit test if it pins the list), `AGENTS.md` §0 (one status bullet) and §9 (the 95 % list)

- [ ] **Step 1:** ADR-0022 from `docs/decisions/0000-template.md`: context (kassa freezes from
      carding; YuPay `4f4f13b4`), decision (verdict in `settle` under a per-user advisory lock;
      `held` / `rejected` statuses; fail-closed; R7 exception for a held order; admin's returned =
      manual return in the kassa cabinet, never to balance), consequences (a held order's lot may
      sell — release goes through the normal failure refund; limits count the attempt's base
      amount, not the fee; IP not used), alternatives (refuse before paying — rejected by the
      owner; fail-open — rejected).
- [ ] **Step 2:** Runbook `payment-held-for-review.md`: what the alert means; open «На
      проверке»; look at the user card «Риск» (money in, other holds, orders, Steam profile age);
      release; or return — per kassa: Payme cabinet → transaction → cancel; Click cabinet → refund;
      Uzum cabinet → reverse; P2P → transfer back from the card by the sender's card number in the
      HUMO notification — then press «Вернул на карту»; a kassa cancelling on its own closes the
      hold by itself; `check_failed` means look at the API logs (`payments.risk.check_failed`).
      How to change limits (Настройки → Оплата → «Лимит без проверки»), how to trust / block a user.
- [ ] **Step 3:** Sequence diagram `payment-hold.mmd` (kassa → settle → verdict → hold →
      admin → release / returned), product flow `payment-hold.md` (what the buyer sees), module
      README (owns the three tables, `verdict`, `ensure_kassa_allowed`, the admin routes; who calls
      it), module-map row, `docs/api/README.md` (the five admin routes, idempotency, `If-Match`,
      the 403 `kassa_payment_blocked`), metrics row for `csmarket_payment_holds_open`, payments
      README (`settle` hold, `holds.py`, `check_risk`).
- [ ] **Step 4:** Add `"risk",` to `MODULES` in `scripts/check-module-coverage.py`; update
      `AGENTS.md` §9's list and add one §0 bullet: «**Payment risk limits** (spec
      `2026-10-21-payment-risk-limits-design.md`, ADR-0022, runbook `payment-held-for-review.md`):
      money over a kassa or user window limit is held for an admin — built on local `main`, not
      deployed.»
- [ ] **Step 5:** Run `make lint typecheck` and `cd apps/api && uv run pytest tests/integration/test_risk_rule.py tests/integration/test_payment_holds_*.py tests/integration/test_risk_admin.py tests/integration/test_kassa_blocked.py tests/unit/test_risk_models.py tests/unit/test_check_module_coverage.py -q`,
      then `npx prettier --check .` from the repo root. Expected: clean, all pass.
- [ ] **Step 6: Commit**

```bash
git add docs scripts AGENTS.md apps/api/src/csmarket/modules/risk/README.md apps/api/src/csmarket/modules/payments/README.md
git commit -m "docs(api/risk): ADR-0022, runbook, flows and the 95 % gate for payment holds

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec coverage: rule (T2), hold on settle for every kassa (T3–4), R7 exception (T4), admin
  decisions and list (T5), kassa limits + user policy + block (T6), alert + counter (T7),
  buyer copy (T9), admin UI (T10), docs + ADR + coverage (T11). Seed 2 000 000 / 24 h (T1).
- `credit_received_transfer` bypass: T3 `check_risk=False` + test.
- Name clash `_HELD` avoided: the new set is `ON_REVIEW`; topups' `_HELD` untouched.
- Route order: holds and review-limits routers before `admin_payments_router` (T5, T6);
  admin SPA uses `/payment-holds` to dodge `/payments/:id`.
