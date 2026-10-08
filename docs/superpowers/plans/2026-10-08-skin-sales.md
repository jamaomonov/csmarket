# Selling Skins to Us (Skinslink Deposits) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user sees their tradable CS2 inventory priced in soʻm, picks items, chooses the balance or a card, gets one Steam trade offer from a Skinslink bot, and is paid exactly once — on the balance or by an admin to a card — only after Skinslink reports the deposit `completed`.

**Architecture:** A new module `modules/sales/` owns the sale-settings document, the pricing, the saved cards (encrypted with `core.crypto`), the inventory read (Redis 5-minute snapshot per user, a breaker), sale creation (`POST /sell`: store, commit, then one `create-deposit` call), the status machine (`status.apply_deposit`, the only place a sale moves), payout requests, the check queue (`sale_checks`, drained by the worker), the poll, the letters and the admin API. `skinslink` gains the three deposit calls (`skinslink/deposits.py`) and routes the signed deposit webhook to a sale check; `wallet` gains the `house_skin_buys` account and two idempotent credits; `realtime` gains a `sale.updated` nudge; `notifications` gains three sale letters. Everything ships behind `CSMARKET_SALES_ENABLED=false` and the admin's «Выкуп включён».

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, httpx + respx, Redis, Postgres queue (`FOR UPDATE SKIP LOCKED` + `NOTIFY`), APScheduler, PyNaCl (`core.crypto`), Next.js 15 storefront (TanStack Query, next-intl), Vite admin SPA (React 19, TanStack Query, Vitest).

**Spec:** `docs/superpowers/specs/2026-10-08-skin-sales-design.md`. Skinslink's deposit API as saved on 2026-10-08 (`inventory`, `create-deposit`, `deposit/status`, webhooks, errors). Precedent for shape and style: `docs/superpowers/plans/2026-10-07-lisskins-buy-source.md` and the purchase code in `apps/api/src/csmarket/modules/skinslink/` and `apps/api/src/csmarket/modules/orders/skinslink_*.py`.

## Global Constraints

- **Kill switches:** `CSMARKET_SALES_ENABLED` (default `false`) **and** `sale_settings.enabled` (default `false`) must both be on, with both Skinslink credentials set (`Settings.sales_active`), else `GET /sell/inventory` and `POST /sell` answer 409 `sales_disabled` and `GET /sell/config` says `enabled: false`. With them off, open sales still settle: the poll and the worker run while `CSMARKET_SKINSLINK_API_KEY` is set, and the webhook answers while Skinslink buying or sales are active.
- **Money:** `Decimal` throughout; USD to 6 places (`numeric(14,6)`), soʻm whole (`numeric(14,0)`); every soʻm figure is **rounded down to 100**; the payout is fixed when the sale is created and is what the cart showed (`expected_payout_uzs`).
- **Rate:** the raw CBU rate — `fx.current_usd_uzs(..., uplift_pct=Decimal(0))` — × `(1 − rate_cut_pct / 100)`, quantised down to 4 places. The 1 % sell uplift (ADR-0011) is never applied.
- **Pricing:** `price_uzs = floor100((usd − bracket_margin(usd, margin)) × rate)`; the minimum is on the **sum** of the chosen items' Skinslink USD prices (`≥ min_sum_usd`, default 1); balance payout `floor100(Σ × (1 + balance_bonus_pct/100))`; card payout `floor100(Σ × (1 − card_fee_pct[type]/100))` and `≥ card_min_uzs` (default 30 000); `min_prices` = each item's price × 0.99, rounded **down** to 0.001 $.
- **Ledger:** no posting before `completed`. A balance sale: D `user_wallet` / C `house_skin_buys`, key `sale:{sale_id}`. A rejected card payout: the same legs for `items_uzs` (the amount before the card fee), key `payout_return:{request_id}`. A card payout an admin marks paid books nothing (the money left our bank by hand).
- **Webhook:** `sign = base64(sha256(str(trade_id) + secret))` is verified before anything else is read; the body is then never trusted — a check is queued and `deposit/status` decides. The webhook payload carries the seller's `steam_id`: it is never read or logged.
- **No external call holds a DB lock or an open transaction.** Two new AGENTS §11 carve-outs (ADR-0016): `GET /sell/inventory` (Skinslink `inventory`, 6 s timeout, a 120 s breaker, a 5-minute per-user Redis cache, its own `ip_guard` bucket `sell-inventory`) and `POST /sell` (one `create-deposit`, 10 s timeout, nothing open across it, bucket `sell-create`). Both routes join the `handler` regexes of `ApiHighLatency` / `ApiWaxpeerLatency`.
- **Card number = PII:** checked (16 digits, the type's prefix — Uzcard `8600` or `5614`, Humo `9860`, Uzum Visa `4` — Luhn), encrypted at rest under the purpose `csmarket:payout-card:v1`; logs, metrics, lists, letters and idempotency replays carry `last4` only; the full number leaves the database only through `POST /admin/sales/payouts/{id}/reveal`, audited every time (`sales.card.show` / `sales.card.copy`) and never stored as a replay. At most 3 live cards per user.
- **Never log:** the trade link, its token or `partner`; a Steam id; a card number; Skinslink error bodies (the refusal `code` only).
- **Banned words** under `apps/*/src` (`scripts/check-no-yupay.sh`): never write `supplier`, `merchants`, `merchant_api`, `voucher`, `game_id` or an identifier shaped like `sku`. `merchant_tx_id` is fine.
- **Copy:** ru / uz / en in the same commit; «вы»; outcome, not mechanism; no "Skinslink", no "hold", no "deposit" in customer copy; skin names stay English.
- **Coverage:** `sales` joins the 95 % gate (`scripts/check-module-coverage.py`); `skinslink`, `wallet`, `notifications`, `realtime` keep theirs.
- **Tests:** each task runs **only its own tests**, targeted (`uv run pytest <files> -q`, `pnpm --filter <pkg> exec vitest run <files>`). Never `make test` locally: the owner's laptop lags; CI runs the whole suite. Before each commit also format and lint what the task touched: `cd apps/api && uv run ruff format <touched paths> && uv run ruff check <touched paths> && uv run mypy <touched src paths>` (the tasks' Step "Run the tests and the linters" lines name the paths; run `ruff format` on the same paths first); TS: `pnpm --filter <pkg> exec tsc --noEmit` and `pnpm --filter <pkg> exec eslint <touched files> --max-warnings 0`.
- **Generated API:** a task that changes a route or schema runs `make gen-api` and commits `docs/api/openapi.json` + `packages/api-client`. Prettier only from the repo root (`npx prettier --write <files>`), never from `apps/web`.
- **ADR number:** 0016 (0014 is reserved by an unmerged branch). Migration: `0023_sales` after `0022_lisskins`.
- **Commits:** Conventional Commits, scopes `api/sales`, `api/skinslink`, `api/wallet`, `api/notifications`, `api/realtime`, `api/admin`, `worker`, `scheduler`, `web/sell`, `web/account`, `admin/sales`, `infra`, `docs`; every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing is pushed or deployed.

## Review Focus

1. **Double credit.** A `completed` webhook replayed, and the 60-s poll seeing `completed` at the same moment, must credit the balance exactly once (one ledger transaction, one `credited_at`) — pinned in Task 7 (`test_completed_twice_credits_the_balance_once`) and Task 10 (`test_two_checks_racing_on_completed_credit_once`).
2. **A reverted trade.** `reverted` out of `hold` pays nothing and cancels a card request; `reverted` after the balance was credited opens `attention_reason = rolled_back` and never debits — pinned in Task 7 (`test_reverted_out_of_hold_pays_nothing_and_cancels_the_request`, `test_reverted_after_a_credit_opens_rolled_back_and_never_debits`).
3. **The webhook signature.** A forged deposit webhook (bad `sign`, a `sign` made for another `trade_id`, a string `trade_id`) is 403 and queues nothing; a good one whose body says `completed` with a large `amount` changes nothing by itself — only `deposit/status` moves the sale — pinned in Task 10 (`test_a_forged_deposit_webhook_is_403_and_queues_nothing`, `test_the_webhook_body_is_never_trusted`).
4. **Price drift.** Skinslink crediting less than quoted (above the 99 % floor) leaves the user's payout as shown; a price under the floor (`item_specified_price_not_found`) or a stale snapshot (`inventory_reload`) is 409 `prices_changed`, closes the sale and drops the cached inventory; `min_prices` = price × 0.99 rounded down — pinned in Task 9 (`test_skinslink_crediting_less_than_quoted_keeps_the_payout`, `test_a_price_under_the_floor_is_prices_changed_and_closes_the_sale`, `test_min_prices_are_99_percent_rounded_down`).
5. **Card-number PII.** The number is never in a log line, an API list, a sale page, an admin page, an idempotency replay row or the database in clear; only the audited reveal returns it — pinned in Task 6 (`test_a_card_number_is_stored_encrypted_and_never_logged_or_listed`) and Task 12 (`test_the_card_number_leaves_only_through_the_audited_reveal`).

---

## File Structure

**Backend — new module `apps/api/src/csmarket/modules/sales/`:**

| File                | Responsibility                                                                                     |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| `api.py`            | The public interface other modules import                                                          |
| `models.py`         | `Sale`, `SaleItem`, `PayoutCard`, `PayoutRequest`, `SaleSettingsRow`, `SaleCheck`, `SALES_CHANNEL` |
| `rules.py`          | `SaleSettings` (the admin document), `CardFees`, `DEFAULT_SALE_SETTINGS`                           |
| `pricing.py`        | Pure: the sale rate, an item's soʻm price, the payout, `min_prices`, the minimum in soʻm           |
| `settings_store.py` | Read / save row 1 of `sale_settings`                                                               |
| `letters.py`        | Sale letters into the email outbox                                                                 |
| `cards.py`          | Card checks (prefix, Luhn), encryption, add / list / delete, reveal                                |
| `cards_routes.py`   | `GET /payout-cards`, `DELETE /payout-cards/{id}`                                                   |
| `payouts.py`        | A sale's payout request: open, cancel, read                                                        |
| `status.py`         | `apply_deposit` (every transition), `lock_sale`, `check_sale`                                      |
| `gate.py`           | The switches, the trade link, the sale rate now                                                    |
| `clients.py`        | FastAPI dependencies building the Skinslink deposit client with each route's timeout               |
| `inventory.py`      | The cached inventory snapshot, the breaker, the priced inventory                                   |
| `service.py`        | `create_sale` (`POST /sell`)                                                                       |
| `views.py`          | Customer reads: one sale, the list, the pending sum, `SaleOut`                                     |
| `schemas.py`        | Customer wire shapes                                                                               |
| `routes.py`         | `/sell/config`, `/sell/inventory`, `/sell`, `/sales`, `/sales/pending`, `/sales/{number}`          |
| `checks.py`         | The `sale_checks` queue: enqueue (webhook), claim, drain (worker)                                  |
| `reconcile.py`      | The poll of open sales; overdue payouts for the alert                                              |
| `admin_schemas.py`  | Admin wire shapes                                                                                  |
| `admin_sales.py`    | Admin sales list / page, the settings view and save                                                |
| `admin_payouts.py`  | Payout queue, request page, reveal, paid, reject, the dashboard summary                            |
| `admin_routes.py`   | `/admin/sales/*`                                                                                   |
| `README.md`         | What the module owns                                                                               |

**Backend — changed:** `core/config.py`, `core/logging.py`, `core/metrics.py`, `core/numbers.py`; `skinslink/client.py` (refusal codes from `message`), new `skinslink/deposits.py`, `skinslink/api.py`, `skinslink/routes.py` (the deposit branch); `wallet/models.py`, `wallet/service.py`, new `wallet/sales.py`, `wallet/api.py`, `wallet/entries.py`, `wallet/schemas.py`; `realtime/api.py`, `realtime/listener.py`, `realtime/registry.py`; `notifications/models.py`, `outbox.py`, `copy.py`, `sender.py`, `templates/__init__.py`, `templates/base.py`, new `templates/sale.py`; `skins/api.py` (export `Bracket`, `bracket_margin`); `admin/dashboard_schemas.py`, `admin/dashboard_routes.py`, `admin/users_schemas.py`; `api/v1/router.py`; `migrations/env.py`, new `migrations/versions/0023_sales.py`; worker `consumer.py`; scheduler `main.py` + new `jobs/sales_poll.py`; `infra/prometheus/alerts/api.yml`, new `infra/prometheus/alerts/sales.yml`; `.env.example`, `infra/secrets-example/api.env`; `scripts/check-module-coverage.py`.

**Storefront (`apps/web/src`):** rewritten `lib/sell.ts`; new `lib/sales.ts`; `lib/paths.ts`; `lib/balance.ts`; `lib/realtime.ts`; `hooks/useOrderSocket.ts`; `app/[locale]/sell/page.tsx`; `components/sell/*`; new `app/[locale]/account/sales/[number]/page.tsx` + `components/sale/SaleView.tsx`; new `components/account/SalesList.tsx`; new `app/[locale]/account/cards/page.tsx` + `components/account/CardsList.tsx`; `components/trades/TradesView.tsx`; `components/balance/BalanceView.tsx`; `components/header/nav.ts`; deleted `lib/sell-demo.ts`. i18n: `packages/i18n/locales/{ru,uz,en}/web.json`.

**Admin SPA (`apps/admin/src`):** new `features/sales/` (`api.ts`, `keys.ts`, `labels.ts`, `fixtures.ts`, `PayoutsPage.tsx`, `PayoutDetail.tsx`, `SalesPage.tsx`, `SaleDetail.tsx`, `SaleSettingsPage.tsx` + tests); `app/router.tsx`; `app/Layout.tsx`; `features/dashboard/*`; `features/users/labels.ts`.

**Docs:** ADR-0016, `docs/architecture/module-map.md`, `docs/architecture/sequence-diagrams/skin-sale.mmd`, `docs/product/flows/sell.md`, `docs/runbooks/sales.md`, `docs/security/pii-handling.md`, `docs/architecture/cache-keys.md`, `docs/architecture/metrics.md`, `docs/api/README.md`, `AGENTS.md` (§0, §9, §11), `docs/runbooks/skinslink.md`.

---

### Task 1: Settings, redaction, rate-limit buckets, coverage gate, module skeleton

**Files:**

- Modify: `apps/api/src/csmarket/core/config.py` (after `lisskins_balance_alert_usd`; the property after `lisskins_active`; two entries in `auth_ip_guard_bucket_max`)
- Modify: `apps/api/src/csmarket/core/logging.py` (`REDACTED_KEYS`, after `"lisskins_api_key",`)
- Modify: `.env.example` and `infra/secrets-example/api.env` (after the LIS-SKINS block)
- Modify: `scripts/check-module-coverage.py` and `apps/api/tests/unit/test_check_module_coverage.py` (`MODULES`)
- Create: `apps/api/src/csmarket/modules/sales/__init__.py` (empty), `apps/api/src/csmarket/modules/sales/api.py`, `apps/api/src/csmarket/modules/sales/README.md`
- Test: `apps/api/tests/unit/test_sales_settings.py`

**Interfaces:**

- Produces: `Settings.sales_enabled: bool = False`, `Settings.sales_inventory_timeout_seconds: float = 6.0`, `Settings.sales_deposit_timeout_seconds: float = 10.0`, `Settings.sales_active -> bool` (the switch **and** `skinslink_api_key` **and** `skinslink_secret`); `auth_ip_guard_bucket_max["sell-inventory"] == 60`, `["sell-create"] == 60`; `REDACTED_KEYS ⊇ {"card_number", "number_enc", "new_card", "pan"}`; `csmarket.modules.sales.api.__all__`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_sales_settings.py
"""Sales settings: off by default; active only with the switch and both Skinslink credentials."""

from __future__ import annotations

import csmarket.modules.sales.api as sales_api
from csmarket.core.config import Settings
from csmarket.core.logging import REDACTED_KEYS


def _make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def test_off_by_default() -> None:
    s = _make()
    assert s.sales_enabled is False
    assert s.sales_active is False
    assert (s.sales_inventory_timeout_seconds, s.sales_deposit_timeout_seconds) == (6.0, 10.0)
    assert s.auth_ip_guard_bucket_max["sell-inventory"] == 60
    assert s.auth_ip_guard_bucket_max["sell-create"] == 60


def test_active_needs_the_switch_the_key_and_the_secret() -> None:
    assert _make(sales_enabled=True).sales_active is False
    assert _make(sales_enabled=True, skinslink_api_key="k").sales_active is False
    assert _make(skinslink_api_key="k", skinslink_secret="s").sales_active is False
    on = _make(sales_enabled=True, skinslink_api_key="k", skinslink_secret="s")
    assert on.sales_active is True


def test_card_numbers_are_redacted() -> None:
    assert {"card_number", "number_enc", "new_card", "pan"} <= REDACTED_KEYS


def test_the_module_has_a_public_interface() -> None:
    assert isinstance(sales_api.__all__, list)
```

- [ ] **Step 2: Run it**

Run: `cd apps/api && uv run pytest tests/unit/test_sales_settings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'csmarket.modules.sales'`.

- [ ] **Step 3: Add the settings, the redaction, the buckets, the gate and the skeleton**

`core/config.py`, right after `lisskins_balance_alert_usd`:

```python
    # --- sales (users sell skins to us through Skinslink deposits; spec 2026-10-08) ---
    sales_enabled: bool = Field(
        default=False,
        description="Let users sell skins (the admin's «Выкуп включён» must be on too).",
    )
    sales_inventory_timeout_seconds: float = Field(
        default=6.0, gt=0, description="Skinslink inventory on GET /sell/inventory (ADR-0016)."
    )
    sales_deposit_timeout_seconds: float = Field(
        default=10.0, gt=0, description="Skinslink create-deposit on POST /sell (ADR-0016)."
    )
```

In `auth_ip_guard_bucket_max`'s default dict, after `"email-verify": 60,`:

```python
            "sell-inventory": 60,
            "sell-create": 60,
```

After the `lisskins_active` property:

```python
    @property
    def sales_active(self) -> bool:
        """Selling is possible: switched on with both Skinslink credentials.

        The admin's «Выкуп включён» (``sale_settings.enabled``) is checked beside it by
        ``sales.gate.open_settings``.
        """
        return self.sales_enabled and bool(self.skinslink_api_key and self.skinslink_secret)
```

`core/logging.py`, in `REDACTED_KEYS` after `"lisskins_api_key",`:

```python
        # A payout card's number (spec 2026-10-08): only ``last4`` may ever be logged.
        "card_number",
        "number_enc",
        "new_card",
        "pan",
```

`.env.example`, after the LIS-SKINS block:

```
# Selling skins to us through Skinslink deposits (spec 2026-10-08). Needs the Skinslink
# key and secret above, and the admin's «Выкуп включён».
CSMARKET_SALES_ENABLED=false
```

`infra/secrets-example/api.env`, after `CSMARKET_LISSKINS_API_KEY`:

```
# Selling skins to us (docs/runbooks/sales.md). Uses the Skinslink key and secret above.
CSMARKET_SALES_ENABLED=false
```

`scripts/check-module-coverage.py` and `apps/api/tests/unit/test_check_module_coverage.py`, both:

```python
MODULES = (
    "orders",
    "payments",
    "wallet",
    "skins",
    "notifications",
    "realtime",
    "skinslink",
    "lisskins",
    "sales",
)
```

`modules/sales/__init__.py`: empty. `modules/sales/api.py`:

```python
"""Public interface of the ``sales`` module — other modules import from here only."""

from __future__ import annotations

__all__: list[str] = []
```

`modules/sales/README.md`:

```markdown
# `sales` — users sell skins to us (Skinslink deposits)

Spec: `docs/superpowers/specs/2026-10-08-skin-sales-design.md`; ADR-0016.

Owns: the sale-settings document, the sale pricing, saved payout cards, the priced inventory,
sales and their items, payout requests, the sale check queue, the poll, the sale letters and
the admin's payout and sale pages. Does not own: the Skinslink HTTP client (`skinslink`), the
ledger (`wallet`), the outbox (`notifications`), the socket (`realtime`).

## Settings

| Env                                        | Default | Meaning                                    |
| ------------------------------------------ | ------- | ------------------------------------------ |
| `CSMARKET_SALES_ENABLED`                   | `false` | The env kill switch                        |
| `CSMARKET_SALES_INVENTORY_TIMEOUT_SECONDS` | `6`     | Skinslink `inventory` on the request path  |
| `CSMARKET_SALES_DEPOSIT_TIMEOUT_SECONDS`   | `10`    | Skinslink `create-deposit` on `POST /sell` |
```

(Task 16 completes the README.)

- [ ] **Step 4: Run the tests and the linters**

Run: `cd apps/api && uv run pytest tests/unit/test_sales_settings.py tests/unit/test_check_module_coverage.py tests/unit/test_config.py tests/unit/test_logging.py -q && uv run ruff check src/csmarket/core src/csmarket/modules/sales tests/unit/test_sales_settings.py && uv run mypy src/csmarket/core/config.py src/csmarket/modules/sales`
Expected: PASS; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/csmarket/core/config.py apps/api/src/csmarket/core/logging.py .env.example infra/secrets-example/api.env scripts/check-module-coverage.py apps/api/tests/unit/test_check_module_coverage.py apps/api/src/csmarket/modules/sales apps/api/tests/unit/test_sales_settings.py
git commit -m "feat(api/sales): settings, card redaction, rate-limit buckets and the coverage gate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Skinslink deposit calls — inventory, create-deposit, deposit status

Decision: the three calls live in a new `skinslink/deposits.py` as `SkinslinkDepositClient(SkinslinkClient)` — `client.py` is already 584 lines — and reuse its envelope handling (`_request`, `_verdict`) and value readers. Skinslink names three refusals only in `message` (no `data`): `item_specified_price_not_found`, `already exist error` (409) and `deposit exceeds the maximum of N items per deposit`; `_code` learns to turn them into stable codes, after the `data` codes it already reads.

**Files:**

- Modify: `apps/api/src/csmarket/modules/skinslink/client.py` (`_code`)
- Create: `apps/api/src/csmarket/modules/skinslink/deposits.py`
- Modify: `apps/api/src/csmarket/modules/skinslink/api.py` (exports)
- Modify: `apps/api/src/csmarket/core/metrics.py` (`SkinslinkEndpoint`, `_SKINSLINK_ENDPOINTS`)
- Test: `apps/api/tests/contract/test_skinslink_deposits.py`

**Interfaces:**

- Consumes: `SkinslinkClient._request(method, path, *, endpoint, params=None, json_body=None)`, `SkinslinkError(.status, .code)`, `SkinslinkForbiddenError`, `SkinslinkUnavailableError`, `SkinslinkRateLimitedError`, `LINK_ERROR_CODES`, `_decimal`, `_str` (all in `skinslink/client.py`).
- Produces (re-exported by `skinslink.api`):
  - `@dataclass(frozen=True) InventoryItem(id: str, name: str, price_usd: Decimal, image_url: str | None, exterior: str | None, rarity: str | None, rarity_color: str | None)`
  - `@dataclass(frozen=True) Inventory(items: list[InventoryItem], max_items: int)`
  - `@dataclass(frozen=True) Deposit(id: int, merchant_tx_id: str | None, status: str, amount_usd: Decimal | None, bot_name: str | None, trade_offer_id: str | None, offer_expiry_at: str | None, hold_end_date: str | None, fail_reason: str | None)`
  - `class DepositClient(Protocol)`: `inventory(*, partner: int, token: str) -> Inventory`; `create_deposit(*, merchant_tx_id: str, partner: int, token: str, asset_ids: Sequence[str], min_prices: Mapping[str, Decimal]) -> Deposit`; `deposit_status(*, merchant_tx_id: str) -> Deposit | None`
  - `class SkinslinkDepositClient(SkinslinkClient)` implementing it; `deposit_client_for(settings: Settings, *, timeout_seconds: float) -> SkinslinkDepositClient`
  - `PRICE_CODES = frozenset({"inventory_reload", "item_specified_price_not_found"})`, `STEAM_ACCOUNT_CODES` (= `LINK_ERROR_CODES`)
  - refusal codes from `message`: `"item_specified_price_not_found"`, `"already_exists"`, `"too_many_items"`
  - metric endpoints `"inventory"`, `"deposit"`, `"deposit_status"` on `csmarket_skinslink_calls_total`

- [ ] **Step 1: Write the failing contract tests**

```python
# apps/api/tests/contract/test_skinslink_deposits.py
"""Skinslink deposit API (respx): inventory, create-deposit, deposit status, every refusal.

Shapes from the Skinslink docs saved on 2026-10-08 (get-inventory, create-deposit,
deposit-status, errors). Every partner, token, asset id and Steam id is made up.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.skinslink.api import (
    STEAM_ACCOUNT_CODES,
    Deposit,
    InventoryItem,
    SkinslinkDepositClient,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)

BASE = "https://api.skinslink.com/api/v1"
PARTNER = 39734273
TOKEN = "AbCdEf12"

ITEM = {
    "id": "38029384123",
    "name": "AK-47 | Redline (Field-Tested)",
    "price": 12.45,
    "image_url": "https://community.cloudflare.steamstatic.com/economy/image/x",
    "exterior": "Field-Tested",
    "rarity": "Classified",
    "rarity_color": "#d32ce6",
}
INVENTORY = {
    "items": [ITEM, {"id": "1", "name": "Free", "price": 0}, {"name": "No id", "price": 1}],
    "total": 47,
    "sum": 284.9,
    "game": "csgo",
    "max_items": 50,
}
DEPOSIT = {
    "id": 42,
    "merchant_tx_id": "sale-1",
    "status": "active",
    "amount": 36.25,
    "bot_name": "Skinslink Bot #3",
    "bot_steam_id": 76561190000000003,
    "trade_offer_id": "6912345678",
    "trade_offer_expiry_at": "2026-02-16T12:30:00Z",
}


def _client() -> SkinslinkDepositClient:
    return SkinslinkDepositClient(api_key="k", base_url=BASE, timeout_seconds=1)


def _ok(data: object) -> dict[str, object]:
    return {"success": True, "message": "ok", "data": data}


def _no(message: str, data: object = None, *, status: int = 400) -> httpx.Response:
    body: dict[str, object] = {"success": False, "message": message}
    if data is not None:
        body["data"] = data
    return httpx.Response(status, json=body)


def _field(code: str, field: str = "partner") -> list[dict[str, str]]:
    return [{"field": field, "code": code, "message": "x"}]


async def _create(min_prices: dict[str, Decimal] | None = None) -> Deposit:
    return await _client().create_deposit(
        merchant_tx_id="sale-1",
        partner=PARTNER,
        token=TOKEN,
        asset_ids=["38029384123"],
        min_prices=min_prices or {"38029384123": Decimal("12.3255")},
    )


@respx.mock
async def test_inventory_reads_the_priced_items_and_max_items() -> None:
    route = respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=httpx.Response(200, json=_ok(INVENTORY))
    )
    inv = await _client().inventory(partner=PARTNER, token=TOKEN)
    assert inv.max_items == 50
    assert inv.items == [
        InventoryItem(
            id="38029384123",
            name="AK-47 | Redline (Field-Tested)",
            price_usd=Decimal("12.45"),
            image_url="https://community.cloudflare.steamstatic.com/economy/image/x",
            exterior="Field-Tested",
            rarity="Classified",
            rarity_color="#d32ce6",
        )
    ]
    request = route.calls.last.request
    assert json.loads(request.content) == {"game": "csgo", "partner": PARTNER, "token": TOKEN}
    assert request.headers["X-Api-Key"] == "k"


@respx.mock
async def test_inventory_without_max_items_is_unavailable() -> None:
    body = {k: v for k, v in INVENTORY.items() if k != "max_items"}
    respx.post(f"{BASE}/merchant/inventory").mock(return_value=httpx.Response(200, json=_ok(body)))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@pytest.mark.parametrize("code", sorted(STEAM_ACCOUNT_CODES))
@respx.mock
async def test_inventory_steam_account_refusals_carry_their_code(code: str) -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=_no("validation error", _field(code))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _client().inventory(partner=PARTNER, token=TOKEN)
    assert (caught.value.status, caught.value.code) == (400, code)


@respx.mock
async def test_inventory_reload_is_a_refusal_with_its_code() -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=_no("validation error", _field("inventory_reload", "inventory"))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _client().inventory(partner=PARTNER, token=TOKEN)
    assert caught.value.code == "inventory_reload"


@pytest.mark.parametrize("status", [408, 500, 502])
@respx.mock
async def test_inventory_timeouts_and_5xx_are_unavailable(status: int) -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(return_value=_no("timeout error", status=status))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@respx.mock
async def test_inventory_403_is_forbidden() -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=_no("IP not whitelisted: 203.0.113.42", status=403)
    )
    with pytest.raises(SkinslinkForbiddenError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@respx.mock
async def test_a_transport_error_is_unavailable() -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@respx.mock
async def test_create_deposit_sends_floors_rounded_down_and_reads_the_offer() -> None:
    route = respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=httpx.Response(200, json=_ok(DEPOSIT))
    )
    deposit = await _create({"38029384123": Decimal("12.3259")})
    assert deposit == Deposit(
        id=42,
        merchant_tx_id="sale-1",
        status="active",
        amount_usd=Decimal("36.25"),
        bot_name="Skinslink Bot #3",
        trade_offer_id="6912345678",
        offer_expiry_at="2026-02-16T12:30:00Z",
        hold_end_date=None,
        fail_reason=None,
    )
    assert json.loads(route.calls.last.request.content) == {
        "merchant_tx_id": "sale-1",
        "game": "csgo",
        "partner": PARTNER,
        "token": TOKEN,
        "asset_ids": ["38029384123"],
        "min_prices": {"38029384123": 12.325},
    }


@respx.mock
async def test_a_price_under_the_floor_is_item_specified_price_not_found() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("item_specified_price_not_found")
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert (caught.value.status, caught.value.code) == (400, "item_specified_price_not_found")


@respx.mock
async def test_a_stale_snapshot_on_create_is_inventory_reload() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("validation error", _field("inventory_reload", "inventory"))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert caught.value.code == "inventory_reload"


@respx.mock
async def test_a_used_merchant_tx_id_is_409_already_exists() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("already exist error", status=409)
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert (caught.value.status, caught.value.code) == (409, "already_exists")


@respx.mock
async def test_too_many_items_is_its_own_code() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("deposit exceeds the maximum of 50 items per deposit")
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert caught.value.code == "too_many_items"


@respx.mock
async def test_a_steam_refusal_on_create_carries_its_code() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("validation error", _field("trade_banned"))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert caught.value.code == "trade_banned"


@respx.mock
async def test_a_5xx_on_create_is_unavailable_the_deposit_may_exist() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(return_value=_no("internal", status=500))
    with pytest.raises(SkinslinkUnavailableError):
        await _create()


@respx.mock
async def test_status_is_asked_by_merchant_tx_id_and_reads_hold() -> None:
    body = {**DEPOSIT, "status": "hold", "hold_end_date": "2026-10-15T10:00:00Z"}
    del body["amount"]
    route = respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=httpx.Response(200, json=_ok(body))
    )
    deposit = await _client().deposit_status(merchant_tx_id="sale-1")
    assert deposit is not None
    assert (deposit.status, deposit.hold_end_date, deposit.amount_usd) == (
        "hold",
        "2026-10-15T10:00:00Z",
        None,
    )
    assert route.calls.last.request.url.params["merchant_tx_id"] == "sale-1"


@respx.mock
async def test_status_reads_the_fail_reason() -> None:
    body = {**DEPOSIT, "status": "reverted", "fail_reason": "user_reverted"}
    respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=httpx.Response(200, json=_ok(body))
    )
    deposit = await _client().deposit_status(merchant_tx_id="sale-1")
    assert deposit is not None
    assert (deposit.status, deposit.fail_reason) == ("reverted", "user_reverted")


@respx.mock
async def test_an_unknown_deposit_is_none() -> None:
    respx.get(f"{BASE}/merchant/deposit/status").mock(return_value=_no("not found error", status=404))
    assert await _client().deposit_status(merchant_tx_id="sale-1") is None


@respx.mock
async def test_a_status_without_an_id_is_unavailable() -> None:
    respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=httpx.Response(200, json=_ok({"status": "hold"}))
    )
    with pytest.raises(SkinslinkUnavailableError):
        await _client().deposit_status(merchant_tx_id="sale-1")
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/contract/test_skinslink_deposits.py -q`
Expected: FAIL — `ImportError: cannot import name 'STEAM_ACCOUNT_CODES' from 'csmarket.modules.skinslink.api'`.

- [ ] **Step 3: Teach `_code` the message-only refusals**

`skinslink/client.py`, above `_code`:

```python
#: Refusals Skinslink names only in ``message`` (no ``data``), as stable codes.
_MESSAGE_CODES = {
    "item_specified_price_not_found": "item_specified_price_not_found",
    "already exist error": "already_exists",
}
_TOO_MANY = "deposit exceeds the maximum"
```

and replace `_code`'s final `return None` with:

```python
    message = body.get("message")
    if isinstance(message, str):
        if message in _MESSAGE_CODES:
            return _MESSAGE_CODES[message]
        if message.startswith(_TOO_MANY):
            return "too_many_items"
    return None
```

(Data codes are read first, so a purchase's `fail_reason` and a validation error's field code win over the message, as before.)

- [ ] **Step 4: Write `skinslink/deposits.py`**

```python
"""Skinslink deposits: users sell skins to our balance at Skinslink (spec 2026-10-08).

``POST /merchant/inventory`` prices the user's tradable CS2 items — a 5-minute snapshot that
``create-deposit`` prices from; ``POST /merchant/create-deposit`` has a Skinslink bot send the
user one trade offer; ``GET /merchant/deposit/status`` says where the deposit is. Same
envelope, error types and metric as the purchase calls (:mod:`.client`). The trade token is
sent, never logged; error bodies are never logged (the refusal ``code`` only).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

from csmarket.core.config import Settings
from csmarket.modules.skinslink.client import (
    LINK_ERROR_CODES,
    SkinslinkClient,
    SkinslinkError,
    SkinslinkUnavailableError,
    _decimal,
    _str,
)

#: Refusals that mean "the prices moved": the inventory must be read again.
PRICE_CODES = frozenset({"inventory_reload", "item_specified_price_not_found"})
#: Refusals about the user's Steam account (Get Inventory and Create Deposit share them).
STEAM_ACCOUNT_CODES = LINK_ERROR_CODES
#: Skinslink prices to 1/1000 $; a floor rounded down never refuses the price we quoted.
_THREE_PLACES = Decimal("0.001")


@dataclass(frozen=True)
class InventoryItem:
    """One tradable item Skinslink accepts now, priced in USD (``items[]``)."""

    id: str
    name: str
    price_usd: Decimal
    image_url: str | None
    exterior: str | None
    rarity: str | None
    rarity_color: str | None


@dataclass(frozen=True)
class Inventory:
    """The priced inventory and the most items one deposit may carry."""

    items: list[InventoryItem]
    max_items: int


@dataclass(frozen=True)
class Deposit:
    """A deposit as Skinslink reports it (Create Deposit / Deposit Status).

    ``amount_usd`` comes with Create Deposit only; ``hold_end_date`` with ``hold``;
    ``fail_reason`` with ``failed`` / ``canceled`` / ``reverted``.
    """

    id: int
    merchant_tx_id: str | None
    status: str
    amount_usd: Decimal | None
    bot_name: str | None
    trade_offer_id: str | None
    offer_expiry_at: str | None
    hold_end_date: str | None
    fail_reason: str | None


class DepositClient(Protocol):
    """What ``sales`` needs from Skinslink (the real client or a test double)."""

    async def inventory(self, *, partner: int, token: str) -> Inventory:
        """The user's priced, tradable inventory."""
        ...

    async def create_deposit(
        self,
        *,
        merchant_tx_id: str,
        partner: int,
        token: str,
        asset_ids: Sequence[str],
        min_prices: Mapping[str, Decimal],
    ) -> Deposit:
        """Have a bot send the user one offer for ``asset_ids``."""
        ...

    async def deposit_status(self, *, merchant_tx_id: str) -> Deposit | None:
        """The deposit under ``merchant_tx_id``, or ``None`` when Skinslink has none."""
        ...


# Any: one JSON object of Skinslink's, read field by field.
def _inventory_item(raw: Mapping[str, Any]) -> InventoryItem | None:
    """An inventory card, or ``None`` when its id, name or price is unusable."""
    raw_id = raw.get("id")
    item_id = str(raw_id) if isinstance(raw_id, int | str) and not isinstance(raw_id, bool) else ""
    name = _str(raw.get("name"))
    price = _decimal(raw.get("price"))
    if not item_id or name is None or price is None or price <= 0:
        return None
    return InventoryItem(
        id=item_id,
        name=name,
        price_usd=price,
        image_url=_str(raw.get("image_url")),
        exterior=_str(raw.get("exterior")),
        rarity=_str(raw.get("rarity")),
        rarity_color=_str(raw.get("rarity_color")),
    )


def _deposit(raw: object) -> Deposit:
    """A deposit answer; one without an integer id or a status is an outage, not a deposit."""
    if not isinstance(raw, Mapping):
        raise SkinslinkUnavailableError("unexpected body")
    did = raw.get("id")
    status = _str(raw.get("status"))
    if not isinstance(did, int) or isinstance(did, bool) or status is None:
        raise SkinslinkUnavailableError("unexpected body")
    return Deposit(
        id=did,
        merchant_tx_id=_str(raw.get("merchant_tx_id")),
        status=status,
        amount_usd=_decimal(raw.get("amount")),
        bot_name=_str(raw.get("bot_name")),
        trade_offer_id=_str(raw.get("trade_offer_id")),
        offer_expiry_at=_str(raw.get("trade_offer_expiry_at")),
        hold_end_date=_str(raw.get("hold_end_date")),
        fail_reason=_str(raw.get("fail_reason")),
    )


class SkinslinkDepositClient(SkinslinkClient):
    """The merchant client with the deposit calls; inject ``client`` in tests."""

    async def inventory(self, *, partner: int, token: str) -> Inventory:
        """``POST /merchant/inventory`` (CS2). Unreadable cards are skipped.

        Raises:
            SkinslinkError: A refusal (``code``: a Steam account code, ``inventory_reload``).
            SkinslinkForbiddenError: HTTP 403.
            SkinslinkUnavailableError: Transport, 408/5xx, 429 or an unreadable body.
        """
        data = await self._request(
            "POST",
            "/merchant/inventory",
            endpoint="inventory",
            json_body={"game": "csgo", "partner": partner, "token": token},
        )
        if not isinstance(data, Mapping) or not isinstance(data.get("items"), list):
            raise SkinslinkUnavailableError("unexpected body")
        max_items = data.get("max_items")
        if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1:
            raise SkinslinkUnavailableError("unexpected body")
        items = [
            item
            for raw in data["items"]
            if isinstance(raw, Mapping) and (item := _inventory_item(raw)) is not None
        ]
        return Inventory(items=items, max_items=max_items)

    async def create_deposit(
        self,
        *,
        merchant_tx_id: str,
        partner: int,
        token: str,
        asset_ids: Sequence[str],
        min_prices: Mapping[str, Decimal],
    ) -> Deposit:
        """``POST /merchant/create-deposit``; ``min_prices`` (USD) rounded down to 0.001.

        Raises:
            SkinslinkError: A refusal — ``code`` one of :data:`PRICE_CODES`, a Steam account
                code, ``too_many_items``; ``status`` 409 (``already_exists``) when the
                ``merchant_tx_id`` was used: the deposit exists, read it by status.
            SkinslinkForbiddenError: HTTP 403.
            SkinslinkUnavailableError: The deposit may exist: resolve through the status.
        """
        data = await self._request(
            "POST",
            "/merchant/create-deposit",
            endpoint="deposit",
            json_body={
                "merchant_tx_id": merchant_tx_id,
                "game": "csgo",
                "partner": partner,
                "token": token,
                "asset_ids": list(asset_ids),
                "min_prices": {
                    asset: float(floor.quantize(_THREE_PLACES, rounding=ROUND_DOWN))
                    for asset, floor in min_prices.items()
                },
            },
        )
        return _deposit(data)

    async def deposit_status(self, *, merchant_tx_id: str) -> Deposit | None:
        """``GET /merchant/deposit/status``; ``None`` when Skinslink has no such deposit."""
        try:
            data = await self._request(
                "GET",
                "/merchant/deposit/status",
                endpoint="deposit_status",
                params={"merchant_tx_id": merchant_tx_id},
            )
        except SkinslinkError as exc:
            if exc.status == 404:
                return None
            raise
        return _deposit(data)


def deposit_client_for(settings: Settings, *, timeout_seconds: float) -> SkinslinkDepositClient:
    """The process's deposit client with ``timeout_seconds`` per call."""
    return SkinslinkDepositClient(
        api_key=settings.skinslink_api_key,
        base_url=settings.skinslink_base_url,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "PRICE_CODES",
    "STEAM_ACCOUNT_CODES",
    "Deposit",
    "DepositClient",
    "Inventory",
    "InventoryItem",
    "SkinslinkDepositClient",
    "deposit_client_for",
]
```

`skinslink/api.py`: add

```python
from csmarket.modules.skinslink.deposits import (
    PRICE_CODES,
    STEAM_ACCOUNT_CODES,
    Deposit,
    DepositClient,
    Inventory,
    InventoryItem,
    SkinslinkDepositClient,
    deposit_client_for,
)
```

and the eight names to `__all__` (alphabetical, constants first, as the file keeps it).

`core/metrics.py`:

```python
#: A Skinslink merchant API call (spec 2026-10-06; deposits since 2026-10-08).
SkinslinkEndpoint = Literal[
    "available", "events", "purchase", "status", "balance", "inventory", "deposit", "deposit_status"
]
```

```python
_SKINSLINK_ENDPOINTS = frozenset(
    (
        "available",
        "events",
        "purchase",
        "status",
        "balance",
        "inventory",
        "deposit",
        "deposit_status",
    )
)
```

- [ ] **Step 5: Run the tests and the linters**

Run: `cd apps/api && uv run pytest tests/contract/test_skinslink_deposits.py tests/contract/test_skinslink_client.py tests/unit/test_metrics.py -q && uv run ruff check src/csmarket/modules/skinslink src/csmarket/core/metrics.py tests/contract/test_skinslink_deposits.py && uv run mypy src/csmarket/modules/skinslink src/csmarket/core/metrics.py`
Expected: PASS (the purchase contract tests unchanged); ruff and mypy clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/csmarket/modules/skinslink apps/api/src/csmarket/core/metrics.py apps/api/tests/contract/test_skinslink_deposits.py
git commit -m "feat(api/skinslink): deposit calls — inventory, create-deposit, deposit status" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tables, the migration (0023), sale numbers, the new account and letter kinds

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/models.py`
- Create: `apps/api/migrations/versions/0023_sales.py`
- Modify: `apps/api/src/csmarket/core/numbers.py` (`sale_number`, `is_sale_number`; order numbers never start with `S`)
- Modify: `apps/api/src/csmarket/modules/wallet/models.py` (`ACCOUNT_KINDS` + `house_skin_buys`)
- Modify: `apps/api/src/csmarket/modules/notifications/models.py` (`KINDS` + three sale letters, `sale_id`, its unique index)
- Modify: `apps/api/migrations/env.py`, `apps/worker/src/csmarket_worker/consumer.py`, `apps/scheduler/src/csmarket_scheduler/main.py` (import `sales.models` so the mappers resolve)
- Modify: `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER`)
- Create: `apps/api/tests/integration/sales_factory.py`
- Test: `apps/api/tests/unit/test_numbers.py` (append), `apps/api/tests/integration/test_sales_models.py`, `apps/api/tests/integration/test_migrations.py` (existing `test_head_matches_models`)

**Interfaces:**

- Produces in `sales/models.py`: `SALES_CHANNEL = "sales"`, `CARD_PURPOSE = "csmarket:payout-card:v1"`, `SALE_STATUSES`, `OPEN_STATUSES = ("creating", "offered", "hold")`, `PAYOUT_TO`, `CARD_TYPES = ("uzcard", "humo", "uzum_visa")`, `REQUEST_STATUSES`, `ATTENTION_REASONS = ("rolled_back", "late_deposit")`; ORM classes:
  - `Sale(id, number, user_id, status, payout_to, payout_card_id, quoted_usd, amount_usd, items_uzs, payout_uzs, rate, margin_usd, trade_id, trade_offer_id, bot_name, offer_expiry_at, hold_end_at, fail_reason, credited_at, attention_reason, idempotency_key, last_polled_at, created_at, updated_at)`
  - `SaleItem(id, sale_id, asset_id, name, image_url, price_usd, price_uzs)`
  - `PayoutCard(id, user_id, type, number_enc, number_nonce, last4, created_at, deleted_at)`
  - `PayoutRequest(id, sale_id, user_id, card_id, amount_uzs, fee_uzs, status, to_pay_at, paid_by, paid_at, rejected_at, note, reject_reason, created_at, updated_at)`
  - `SaleSettingsRow(id=1, settings: dict, updated_by, updated_at)`
  - `SaleCheck(id, sale_id, created_at)`
- Produces in `core/numbers.py`: `SALE_PREFIX = "S"`, `sale_number() -> str` (`S` + 7), `is_sale_number(value: str) -> bool`.
- Produces in `notifications/models.py`: `KINDS = ("receipt", "trade_sent", "refunded", "verify", "sale_hold", "sale_paid", "sale_canceled")`, `EmailOutbox.sale_id: str | None`.
- Produces in tests: `sales_factory.RATE = Decimal("12650.5")`, `HUMO = "9860123456789015"`, `UZCARD = "8600123456789012"`, `VISA = "4000000000000002"` (fake, Luhn-valid), `make_card(db, user, *, card_type="humo", number=HUMO) -> PayoutCard`, `make_sale(db, *, user=None, status="offered", payout_to="balance", card=None, items=ITEMS, payout_uzs=None, **over) -> Sale`, `make_request(db, sale, *, status="to_pay", **over) -> PayoutRequest`, `ITEMS` (the two priced items of the spec's example).

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/unit/test_numbers.py`:

```python
def test_sale_numbers_are_s_plus_7_and_orders_never_start_with_s() -> None:
    from csmarket.core.numbers import is_sale_number, sale_number

    for _ in range(200):
        sale, order = sale_number(), order_number()
        assert sale.startswith("S") and is_number(sale) and is_sale_number(sale)
        assert order[0] not in {"S", "T"}
        assert not is_sale_number(order)
```

(`order_number` and `is_number` are already imported at the top of that file.)

```python
# apps/api/tests/integration/test_sales_models.py
"""The sales tables: constraints that keep a sale, its card and its request consistent."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.sales.models import PayoutRequest, SaleItem
from csmarket.modules.wallet.models import WalletAccount
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import make_card, make_request, make_sale

pytestmark = pytest.mark.asyncio


async def test_a_sale_and_its_items_round_trip(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session)
    items = (
        await db_session.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.asset_id)
        )
    ).all()
    assert [(i.asset_id, i.price_uzs) for i in items] == [("100", 149_600), ("101", 5_600)]
    assert sale.number.startswith("S")
    assert sale.items_uzs == Decimal(155_200)


async def test_a_card_sale_needs_a_card_and_a_balance_sale_none(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(IntegrityError):
        await make_sale(db_session, user=user, payout_to="card", payout_card_id=None)
    await db_session.rollback()
    card = await make_card(db_session, user)
    with pytest.raises(IntegrityError):
        await make_sale(db_session, user=user, payout_to="balance", payout_card_id=card.id)


async def test_one_idempotency_key_per_user(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session)
    with pytest.raises(IntegrityError):
        # ``user_id`` through ``**over`` makes the second sale the same user's.
        await make_sale(db_session, user_id=sale.user_id, idempotency_key=sale.idempotency_key)


async def test_one_payout_request_per_sale(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", status="payout")
    await make_request(db_session, sale)
    with pytest.raises(IntegrityError):
        await make_request(db_session, sale)


async def test_a_request_status_outside_the_set_is_refused(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", status="payout")
    with pytest.raises(IntegrityError):
        await make_request(db_session, sale, status="sent")


async def test_house_skin_buys_is_an_account_kind(db_session: AsyncSession) -> None:
    db_session.add(
        WalletAccount(id=new_id(), owner_type="house", owner_id="house", kind="house_skin_buys")
    )
    await db_session.commit()


async def test_a_sale_letter_is_unique_per_sale_and_kind(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session)
    for _ in range(2):
        db_session.add(
            EmailOutbox(kind="sale_hold", user_id=sale.user_id, sale_id=sale.id, payload={})
        )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_a_request_points_at_its_card(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", status="hold")
    request = await make_request(db_session, sale, status="waiting_hold")
    stored = await db_session.get(PayoutRequest, request.id)
    assert stored is not None
    assert (stored.card_id, stored.amount_uzs, stored.fee_uzs) == (
        sale.payout_card_id,
        sale.payout_uzs,
        sale.items_uzs - sale.payout_uzs,
    )
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_numbers.py tests/integration/test_sales_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'sale_number'` / `ModuleNotFoundError: csmarket.modules.sales.models`.

- [ ] **Step 3: Sale numbers**

`core/numbers.py`: under `TOPUP_PREFIX = "T"`:

```python
#: A sale's number (spec 2026-10-08) is ``S`` + 7 chars; an order's never starts with it.
SALE_PREFIX = "S"
_FIRST = ALPHABET.replace(TOPUP_PREFIX, "").replace(SALE_PREFIX, "")
```

(replacing the old `_FIRST` line), update the module docstring's last sentence to "…an order number must never start with `T` (or `S`, a sale's)", and add after `topup_number`:

```python
def sale_number() -> str:
    """A sale number: ``S`` + 7 chars."""
    return SALE_PREFIX + _chars(_LEN - 1)
```

and after `is_topup_number`:

```python
def is_sale_number(value: str) -> bool:
    """Whether ``value`` is a well-formed sale number."""
    return is_number(value) and value.startswith(SALE_PREFIX)
```

- [ ] **Step 4: The models**

```python
# apps/api/src/csmarket/modules/sales/models.py
"""SQLAlchemy ORM for the ``sales`` module (spec 2026-10-08 §4).

- :class:`Sale` — one Skinslink deposit; its ``id`` is the ``merchant_tx_id``. Its payout is
  fixed when it is created; ``amount_usd`` is what Skinslink says it credits us.
- :class:`SaleItem` — the items of a sale, at the prices the user saw.
- :class:`PayoutCard` — a saved card, encrypted under :data:`CARD_PURPOSE`; only ``last4`` is
  in the clear. Deleted softly: a paid request keeps pointing at its card.
- :class:`PayoutRequest` — a card payout an admin pays by hand; at most one per sale.
- :class:`SaleSettingsRow` — row 1, the admin's document (``rules.SaleSettings``).
- :class:`SaleCheck` — «ask Skinslink about sale N»: queued by the webhook, drained by the
  worker's ``sales`` queue.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

#: The LISTEN channel of the worker's ``sales`` queue.
SALES_CHANNEL = "sales"
#: The ``core.crypto`` purpose label of a card number. A new cipher means a new label.
CARD_PURPOSE = "csmarket:payout-card:v1"

SALE_STATUSES = ("creating", "offered", "hold", "credited", "payout", "closed", "reverted")
#: Statuses Skinslink may still move; everything else is settled.
OPEN_STATUSES = ("creating", "offered", "hold")
PAYOUT_TO = ("balance", "card")
CARD_TYPES = ("uzcard", "humo", "uzum_visa")
REQUEST_STATUSES = ("waiting_hold", "to_pay", "paid", "rejected", "canceled")
#: ``rolled_back``: reverted after the money left; ``late_deposit``: a closed sale Skinslink
#: reports alive. Both wait for an admin (``docs/runbooks/sales.md``).
ATTENTION_REASONS = ("rolled_back", "late_deposit")


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


def _at() -> Mapped[datetime | None]:
    """A nullable timestamp."""
    return mapped_column(DateTime(timezone=True), nullable=True)


class PayoutCard(Base):
    """A user's saved payout card."""

    __tablename__ = "payout_cards"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The 16 digits, encrypted (``core.crypto``, :data:`CARD_PURPOSE`). PII.
    number_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    number_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = _ts()
    deleted_at: Mapped[datetime | None] = _at()

    __table_args__ = (
        CheckConstraint(f"type IN {_in(CARD_TYPES)}", name="type"),
        Index(
            "ix_payout_cards_user_live", "user_id", postgresql_where=text("deleted_at IS NULL")
        ),
    )


class Sale(Base):
    """One sale: the user's items deposited at Skinslink, our payout fixed at creation."""

    __tablename__ = "sales"

    #: Also the Skinslink ``merchant_tx_id``.
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    #: ``S`` + 7 Crockford chars (``core.numbers.sale_number``).
    number: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'creating'")
    )
    payout_to: Mapped[str] = mapped_column(String(8), nullable=False)
    payout_card_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payout_cards.id", ondelete="RESTRICT"), nullable=True
    )
    #: The sum of the items' Skinslink prices when the sale was created, USD.
    quoted_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    #: What Skinslink says it credits us (Create Deposit's ``amount``), USD.
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    #: The sum of the items' soʻm prices, before the bonus or the card fee.
    items_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: What the user gets, fixed at creation.
    payout_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: The sale rate: the CBU rate less ``rate_cut_pct``.
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    margin_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    #: Skinslink's deposit id (``trade_id`` in its webhook).
    trade_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_offer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bot_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offer_expiry_at: Mapped[datetime | None] = _at()
    hold_end_at: Mapped[datetime | None] = _at()
    fail_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    credited_at: Mapped[datetime | None] = _at()
    attention_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    last_polled_at: Mapped[datetime | None] = _at()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("number", name="uq_sales_number"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_sales_user_id_idempotency_key"),
        CheckConstraint(f"status IN {_in(SALE_STATUSES)}", name="status"),
        CheckConstraint(f"payout_to IN {_in(PAYOUT_TO)}", name="payout_to"),
        CheckConstraint("(payout_to = 'card') = (payout_card_id IS NOT NULL)", name="payout_card"),
        CheckConstraint(
            f"attention_reason IS NULL OR attention_reason IN {_in(ATTENTION_REASONS)}",
            name="attention_reason",
        ),
        Index("ix_sales_user_created", "user_id", text("created_at DESC")),
        Index(
            "ix_sales_open",
            "status",
            "last_polled_at",
            postgresql_where=text("status IN ('creating', 'offered', 'hold')"),
        ),
    )


class SaleItem(Base):
    """One item of a sale, at the prices the user saw."""

    __tablename__ = "sale_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    sale_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    #: Steam's asset id in the user's inventory.
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Skinslink's price, USD.
    price_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    #: Our price, soʻm.
    price_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)

    __table_args__ = (
        UniqueConstraint("sale_id", "asset_id", name="uq_sale_items_sale_id_asset_id"),
    )


class PayoutRequest(Base):
    """A card payout: opened at ``hold``, payable at ``completed``, paid or rejected by hand."""

    __tablename__ = "payout_requests"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    sale_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    card_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payout_cards.id", ondelete="RESTRICT"), nullable=False
    )
    #: What goes to the card (the sale's ``payout_uzs``).
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: The card fee kept (``items_uzs − payout_uzs``); a rejection credits both.
    fee_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Since when it is payable (``completed`` seen).
    to_pay_at: Mapped[datetime | None] = _at()
    #: The admin who paid or rejected it.
    paid_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = _at()
    rejected_at: Mapped[datetime | None] = _at()
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("sale_id", name="uq_payout_requests_sale_id"),
        CheckConstraint(f"status IN {_in(REQUEST_STATUSES)}", name="status"),
        Index("ix_payout_requests_status_due", "status", "to_pay_at"),
        Index("ix_payout_requests_user_created", "user_id", text("created_at DESC")),
    )


class SaleSettingsRow(Base):
    """Row 1: the sale-settings document (``rules.SaleSettings``) an admin edits."""

    __tablename__ = "sale_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Any: a JSONB document validated by ``rules.SaleSettings`` on every read.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class SaleCheck(Base):
    """«Ask Skinslink about sale N» — one-shot, drained by the worker."""

    __tablename__ = "sale_checks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    sale_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_sale_checks_created_at", "created_at"),)


__all__ = [
    "ATTENTION_REASONS",
    "CARD_PURPOSE",
    "CARD_TYPES",
    "OPEN_STATUSES",
    "PAYOUT_TO",
    "REQUEST_STATUSES",
    "SALES_CHANNEL",
    "SALE_STATUSES",
    "PayoutCard",
    "PayoutRequest",
    "Sale",
    "SaleCheck",
    "SaleItem",
    "SaleSettingsRow",
]
```

`wallet/models.py`:

```python
#: Account kinds (ruling R2; ``house_skin_buys`` since spec 2026-10-08); their normal sides
#: live in ``service.NORMAL_SIDE``.
ACCOUNT_KINDS = (
    "user_wallet",
    "provider_clearing",
    "house_payments_received",
    "house_adjustments",
    "house_skin_buys",
)
```

`notifications/models.py`:

```python
#: Letter kinds: three order letters, the email confirmation, three sale letters (2026-10-08).
KINDS = (
    "receipt",
    "trade_sent",
    "refunded",
    "verify",
    "sale_hold",
    "sale_paid",
    "sale_canceled",
)
```

a column after `order_id`:

```python
    #: The sale a sale letter reports; ``NULL`` otherwise.
    sale_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=True
    )
```

and in `__table_args__`, after `uq_email_outbox_order_kind`:

```python
        # A replayed sale event never enqueues the same sale letter twice.
        Index(
            "uq_email_outbox_sale_kind",
            "sale_id",
            "kind",
            unique=True,
            postgresql_where=text("sale_id IS NOT NULL"),
        ),
```

Mappers: add `from csmarket.modules.sales import models as _sales_models  # noqa: F401` to `migrations/env.py` (after `_payments_models`), `apps/worker/src/csmarket_worker/consumer.py` and `apps/scheduler/src/csmarket_scheduler/main.py` (alphabetical in each import block) — `email_outbox.sale_id` names `sales.id`, so every process that flushes a letter needs the `sales` mapper.

- [ ] **Step 5: The migration**

```python
# apps/api/migrations/versions/0023_sales.py
"""sales: users sell skins through Skinslink deposits; cards, payout requests, settings

Spec 2026-10-08, ADR-0016: one row per deposit and its items, saved payout cards (the number
encrypted), card payout requests, the admin's settings document, a check queue; the email
outbox learns three sale letters; the ledger a ``house_skin_buys`` account.

Revision ID: 0023_sales
Revises: 0022_lisskins
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_sales"
down_revision: str | None = "0022_lisskins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_SALE_STATUSES = "'creating', 'offered', 'hold', 'credited', 'payout', 'closed', 'reverted'"
_REQUEST_STATUSES = "'waiting_hold', 'to_pay', 'paid', 'rejected', 'canceled'"
_KINDS_OLD = "'receipt', 'trade_sent', 'refunded', 'verify'"
_KINDS_NEW = _KINDS_OLD + ", 'sale_hold', 'sale_paid', 'sale_canceled'"
_ACCOUNTS_OLD = "'user_wallet', 'provider_clearing', 'house_payments_received', 'house_adjustments'"
_ACCOUNTS_NEW = _ACCOUNTS_OLD + ", 'house_skin_buys'"


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


def _at(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _fk(name: str, target: str, *, ondelete: str, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, _UUID, sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _cards() -> None:
    op.create_table(
        "payout_cards",
        sa.Column("id", _UUID, primary_key=True),
        _fk("user_id", "users.id", ondelete="RESTRICT"),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("number_enc", sa.LargeBinary(), nullable=False),
        sa.Column("number_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        _ts("created_at"),
        _at("deleted_at"),
        sa.CheckConstraint("type IN ('uzcard', 'humo', 'uzum_visa')", name="type"),
    )
    op.create_index(
        "ix_payout_cards_user_live",
        "payout_cards",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def _sales() -> None:
    op.create_table(
        "sales",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("number", sa.String(8), nullable=False),
        _fk("user_id", "users.id", ondelete="RESTRICT"),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'creating'")),
        sa.Column("payout_to", sa.String(8), nullable=False),
        _fk("payout_card_id", "payout_cards.id", ondelete="RESTRICT", nullable=True),
        sa.Column("quoted_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("amount_usd", sa.Numeric(14, 6), nullable=True),
        sa.Column("items_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("payout_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("margin_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("trade_id", sa.BigInteger(), nullable=True),
        sa.Column("trade_offer_id", sa.String(32), nullable=True),
        sa.Column("bot_name", sa.String(64), nullable=True),
        _at("offer_expiry_at"),
        _at("hold_end_at"),
        sa.Column("fail_reason", sa.String(48), nullable=True),
        _at("credited_at"),
        sa.Column("attention_reason", sa.String(16), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        _at("last_polled_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("number", name="uq_sales_number"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_sales_user_id_idempotency_key"),
        sa.CheckConstraint(f"status IN ({_SALE_STATUSES})", name="status"),
        sa.CheckConstraint("payout_to IN ('balance', 'card')", name="payout_to"),
        sa.CheckConstraint(
            "(payout_to = 'card') = (payout_card_id IS NOT NULL)", name="payout_card"
        ),
        sa.CheckConstraint(
            "attention_reason IS NULL OR attention_reason IN ('rolled_back', 'late_deposit')",
            name="attention_reason",
        ),
    )
    op.create_index("ix_sales_user_created", "sales", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_sales_open",
        "sales",
        ["status", "last_polled_at"],
        postgresql_where=sa.text("status IN ('creating', 'offered', 'hold')"),
    )
    op.create_table(
        "sale_items",
        sa.Column("id", _UUID, primary_key=True),
        _fk("sale_id", "sales.id", ondelete="CASCADE"),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("price_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("price_uzs", sa.Numeric(14, 0), nullable=False),
        sa.UniqueConstraint("sale_id", "asset_id", name="uq_sale_items_sale_id_asset_id"),
    )


def _requests_settings_checks() -> None:
    op.create_table(
        "payout_requests",
        sa.Column("id", _UUID, primary_key=True),
        _fk("sale_id", "sales.id", ondelete="RESTRICT"),
        _fk("user_id", "users.id", ondelete="RESTRICT"),
        _fk("card_id", "payout_cards.id", ondelete="RESTRICT"),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("fee_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _at("to_pay_at"),
        _fk("paid_by", "users.id", ondelete="SET NULL", nullable=True),
        _at("paid_at"),
        _at("rejected_at"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("sale_id", name="uq_payout_requests_sale_id"),
        sa.CheckConstraint(f"status IN ({_REQUEST_STATUSES})", name="status"),
    )
    op.create_index(
        "ix_payout_requests_status_due", "payout_requests", ["status", "to_pay_at"]
    )
    op.create_index(
        "ix_payout_requests_user_created",
        "payout_requests",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_table(
        "sale_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        _fk("updated_by", "users.id", ondelete="SET NULL", nullable=True),
        _ts("updated_at"),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.create_table(
        "sale_checks",
        sa.Column("id", _UUID, primary_key=True),
        _fk("sale_id", "sales.id", ondelete="CASCADE"),
        _ts("created_at"),
    )
    op.create_index("ix_sale_checks_created_at", "sale_checks", ["created_at"])


def upgrade() -> None:
    """Create the sales tables; let the outbox and the ledger know about sales."""
    _cards()
    _sales()
    _requests_settings_checks()
    op.add_column(
        "email_outbox",
        sa.Column("sale_id", _UUID, sa.ForeignKey("sales.id", ondelete="RESTRICT"), nullable=True),
    )
    op.create_index(
        "uq_email_outbox_sale_kind",
        "email_outbox",
        ["sale_id", "kind"],
        unique=True,
        postgresql_where=sa.text("sale_id IS NOT NULL"),
    )
    op.drop_constraint("kind", "email_outbox", type_="check")
    op.create_check_constraint("kind", "email_outbox", f"kind IN ({_KINDS_NEW})")
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_ACCOUNTS_NEW})")


def downgrade() -> None:
    """Drop sales (sale letters and ``house_skin_buys`` rows must be gone first)."""
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_ACCOUNTS_OLD})")
    op.drop_constraint("kind", "email_outbox", type_="check")
    op.create_check_constraint("kind", "email_outbox", f"kind IN ({_KINDS_OLD})")
    op.drop_index("uq_email_outbox_sale_kind", table_name="email_outbox")
    op.drop_column("email_outbox", "sale_id")
    op.drop_index("ix_sale_checks_created_at", table_name="sale_checks")
    op.drop_table("sale_checks")
    op.drop_table("sale_settings")
    op.drop_index("ix_payout_requests_user_created", table_name="payout_requests")
    op.drop_index("ix_payout_requests_status_due", table_name="payout_requests")
    op.drop_table("payout_requests")
    op.drop_table("sale_items")
    op.drop_index("ix_sales_open", table_name="sales")
    op.drop_index("ix_sales_user_created", table_name="sales")
    op.drop_table("sales")
    op.drop_index("ix_payout_cards_user_live", table_name="payout_cards")
    op.drop_table("payout_cards")
```

(`op.drop_constraint("kind", ...)` resolves to `ck_email_outbox_kind` / `ck_wallet_accounts_kind` through the naming convention, as `0022` did for `ck_orders_source`.)

- [ ] **Step 6: The test plumbing**

`tests/integration/conftest.py`, in `_EMPTY_IN_ORDER`, right after `"uzum_transactions",`:

```python
    "sale_checks",
    "payout_requests",
    "sale_items",
    "sales",
    "payout_cards",
    "sale_settings",
```

(`email_outbox`, which now references `sales`, is already first.)

```python
# apps/api/tests/integration/sales_factory.py
"""Rows for the sales tests: cards, sales with their items, payout requests.

Card numbers here are made up (Luhn-valid, the right prefixes) and never belong to anyone.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from csmarket.core.crypto import encrypt
from csmarket.core.ids import new_id
from csmarket.core.numbers import allocate, sale_number
from csmarket.modules.sales.models import (
    CARD_PURPOSE,
    PayoutCard,
    PayoutRequest,
    Sale,
    SaleItem,
)
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

#: The CBU rate the sales tests price with (no uplift, no cut).
RATE = Decimal("12650.5")
HUMO = "9860123456789015"
UZCARD = "8600123456789012"
VISA = "4000000000000002"
#: ``(asset_id, name, Skinslink USD, our soʻm)`` — the spec's two-item example at RATE with the
#: default brackets: 12.45 $ → 149 600, 0.50 $ → 5 600.
ITEMS: tuple[tuple[str, str, Decimal, Decimal], ...] = (
    ("100", "AK-47 | Redline (Field-Tested)", Decimal("12.45"), Decimal(149_600)),
    ("101", "P250 | Sand Dune (Field-Tested)", Decimal("0.5"), Decimal(5_600)),
)


async def make_card(
    db: AsyncSession, user: User, *, card_type: str = "humo", number: str = HUMO
) -> PayoutCard:
    """A committed, encrypted card of ``user``."""
    enc, nonce = encrypt(number, purpose=CARD_PURPOSE)
    card = PayoutCard(
        id=new_id(),
        user_id=user.id,
        type=card_type,
        number_enc=enc,
        number_nonce=nonce,
        last4=number[-4:],
    )
    db.add(card)
    await db.commit()
    return card


async def make_sale(
    db: AsyncSession,
    *,
    user: User | None = None,
    status: str = "offered",
    payout_to: str = "balance",
    card: PayoutCard | None = None,
    items: tuple[tuple[str, str, Decimal, Decimal], ...] = ITEMS,
    payout_uzs: Decimal | None = None,
    **over: object,
) -> Sale:
    """A committed sale with ``items`` (a new user's unless ``user``; ``over`` replaces any
    column). A card sale gets a new card unless ``card`` or ``payout_card_id`` is given."""
    owner = user or await make_user(db)
    if payout_to == "card" and card is None and "payout_card_id" not in over:
        card = await make_card(db, owner)
    items_uzs = sum((i[3] for i in items), Decimal(0))
    values: dict[str, object] = {
        "id": new_id(),
        "number": await allocate(db, Sale.number, sale_number),
        "user_id": owner.id,
        "status": status,
        "payout_to": payout_to,
        "payout_card_id": card.id if card is not None else None,
        "quoted_usd": sum((i[2] for i in items), Decimal(0)),
        "items_uzs": items_uzs,
        "payout_uzs": payout_uzs if payout_uzs is not None else items_uzs,
        "rate": RATE,
        "margin_usd": Decimal("0.6735"),
        "trade_offer_id": "6912345678" if status != "creating" else None,
        "idempotency_key": f"test-{uuid4()}",
    }
    values.update(over)
    sale = Sale(**values)
    db.add(sale)
    db.add_all(
        SaleItem(sale_id=sale.id, asset_id=a, name=n, price_usd=usd, price_uzs=uzs)
        for a, n, usd, uzs in items
    )
    await db.commit()
    return sale


async def make_request(
    db: AsyncSession, sale: Sale, *, status: str = "to_pay", **over: object
) -> PayoutRequest:
    """A committed payout request of the card sale ``sale``."""
    assert sale.payout_card_id is not None, "a card sale"
    values: dict[str, object] = {
        "id": new_id(),
        "sale_id": sale.id,
        "user_id": sale.user_id,
        "card_id": sale.payout_card_id,
        "amount_uzs": sale.payout_uzs,
        "fee_uzs": sale.items_uzs - sale.payout_uzs,
        "status": status,
    }
    values.update(over)
    request = PayoutRequest(**values)
    db.add(request)
    await db.commit()
    return request
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/api && uv run pytest tests/unit/test_numbers.py tests/integration/test_sales_models.py tests/integration/test_migrations.py tests/integration/test_email_outbox.py -q`
Expected: PASS — including `test_head_matches_models` (models and `0023` agree) and the existing outbox tests.

Then: `cd apps/api && uv run ruff check src/csmarket/modules/sales src/csmarket/core/numbers.py migrations/versions/0023_sales.py tests/integration/sales_factory.py tests/integration/test_sales_models.py && uv run mypy src/csmarket/modules/sales src/csmarket/core/numbers.py src/csmarket/modules/notifications src/csmarket/modules/wallet`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/csmarket/modules/sales/models.py apps/api/migrations apps/api/src/csmarket/core/numbers.py apps/api/src/csmarket/modules/wallet/models.py apps/api/src/csmarket/modules/notifications/models.py apps/worker/src/csmarket_worker/consumer.py apps/scheduler/src/csmarket_scheduler/main.py apps/api/tests/integration/conftest.py apps/api/tests/integration/sales_factory.py apps/api/tests/integration/test_sales_models.py apps/api/tests/unit/test_numbers.py
git commit -m "feat(api/sales): tables for sales, items, cards, payout requests, settings and checks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The sale-settings document and the pricing

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/rules.py`, `apps/api/src/csmarket/modules/sales/pricing.py`, `apps/api/src/csmarket/modules/sales/settings_store.py`
- Modify: `apps/api/src/csmarket/modules/skins/api.py` (export `Bracket`, `bracket_margin`)
- Modify: `apps/api/tests/integration/sales_factory.py` (`enable_sales`)
- Test: `apps/api/tests/unit/test_sales_pricing.py`, `apps/api/tests/integration/test_sales_settings_store.py`

**Interfaces:**

- Consumes: `skins.api.Bracket(from_usd, percent)`, `skins.api.bracket_margin(cost: Decimal, brackets: list[Bracket]) -> Decimal`; `SaleSettingsRow` (Task 3).
- Produces in `rules.py`: `CardType = Literal["uzcard", "humo", "uzum_visa"]`, `PayoutTo = Literal["balance", "card"]`, `CardFees(uzcard: Decimal, humo: Decimal, uzum_visa: Decimal)` with `.of(card_type) -> Decimal`, `SaleSettings(enabled: bool, margin: list[Bracket], rate_cut_pct: Decimal, balance_bonus_pct: Decimal, card_fee_pct: CardFees, card_min_uzs: int, min_sum_usd: Decimal)`, `DEFAULT_SALE_SETTINGS`.
- Produces in `pricing.py`: `floor_100(amount: Decimal) -> Decimal`, `sale_rate(cbu_rate: Decimal, settings: SaleSettings) -> Decimal`, `ItemQuote(price_uzs: Decimal, margin_usd: Decimal)`, `quote_item(price_usd: Decimal, settings: SaleSettings, rate: Decimal) -> ItemQuote`, `Payout(items_uzs, bonus_uzs, fee_uzs, payout_uzs)`, `payout_for(items_uzs: Decimal, settings: SaleSettings, *, to: PayoutTo, card_type: CardType | None) -> Payout`, `MIN_PRICE_SHARE = Decimal("0.99")`, `min_prices(items: Sequence[tuple[str, Decimal]]) -> dict[str, Decimal]`, `min_sum_uzs(settings: SaleSettings, rate: Decimal) -> Decimal`.
- Produces in `settings_store.py`: `read_sale_settings(db) -> SaleSettings` (row 1, or the default when missing or unreadable), `settings_row(db) -> SaleSettingsRow | None`, `save_sale_settings(db, *, settings: SaleSettings, admin_id: str) -> None` (flushes).
- Produces in the factory: `enable_sales(db, **over) -> SaleSettings` (row 1 = the default with `enabled=True` and `over`).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/unit/test_sales_pricing.py
"""Sale pricing (spec 2026-10-08 §3): brackets, the raw CBU rate, every soʻm figure down to 100."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.sales.pricing import (
    ItemQuote,
    Payout,
    floor_100,
    min_prices,
    min_sum_uzs,
    payout_for,
    quote_item,
    sale_rate,
)
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, SaleSettings
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

RATE = Decimal("12650.5")
S = DEFAULT_SALE_SETTINGS


def test_floor_100_rounds_down() -> None:
    assert [floor_100(Decimal(x)) for x in ("149611.13", "100", "99.99", "0")] == [
        Decimal(149_600),
        Decimal(100),
        Decimal(0),
        Decimal(0),
    ]


@pytest.mark.parametrize(
    ("usd", "uzs", "margin"),
    [
        ("12.45", 149_600, "0.6235"),
        ("0.5", 5_600, "0.05"),
        ("1.00", 11_300, "0.1"),
        ("250", 3_083_500, "6.25"),
    ],
)
def test_an_item_is_priced_through_the_progressive_brackets(usd: str, uzs: int, margin: str) -> None:
    assert quote_item(Decimal(usd), S, RATE) == ItemQuote(
        price_uzs=Decimal(uzs), margin_usd=Decimal(margin)
    )


def test_a_cent_item_can_price_to_zero() -> None:
    assert quote_item(Decimal("0.005"), S, RATE).price_uzs == 0


def test_the_rate_is_the_cbu_rate_less_the_cut_rounded_down() -> None:
    assert sale_rate(RATE, S) == Decimal("12650.5000")
    cut = S.model_copy(update={"rate_cut_pct": Decimal("1")})
    assert sale_rate(RATE, cut) == Decimal("12523.9950")


def test_the_balance_gets_the_bonus_rounded_down() -> None:
    assert payout_for(Decimal(155_200), S, to="balance", card_type=None) == Payout(
        items_uzs=Decimal(155_200),
        bonus_uzs=Decimal(3_100),
        fee_uzs=Decimal(0),
        payout_uzs=Decimal(158_300),
    )


def test_a_card_pays_its_type_fee_rounded_down() -> None:
    assert payout_for(Decimal(155_200), S, to="card", card_type="humo") == Payout(
        items_uzs=Decimal(155_200),
        bonus_uzs=Decimal(0),
        fee_uzs=Decimal(7_800),
        payout_uzs=Decimal(147_400),
    )


def test_a_card_payout_needs_a_card_type() -> None:
    with pytest.raises(ValueError, match="card type"):
        payout_for(Decimal(155_200), S, to="card", card_type=None)


def test_min_prices_are_99_percent_rounded_down_to_a_tenth_of_a_cent() -> None:
    assert min_prices([("100", Decimal("12.45")), ("101", Decimal("0.5"))]) == {
        "100": Decimal("12.325"),
        "101": Decimal("0.495"),
    }


def test_the_minimum_in_soum_is_one_dollar_priced_as_an_item() -> None:
    assert min_sum_uzs(S, RATE) == Decimal(11_300)


def test_the_defaults_ship_switched_off() -> None:
    assert S.enabled is False
    assert (S.card_min_uzs, S.min_sum_usd, S.balance_bonus_pct) == (
        30_000,
        Decimal(1),
        Decimal(2),
    )


@pytest.mark.parametrize(
    "margin",
    [
        [{"from_usd": "1", "percent": "10"}],
        [{"from_usd": "0", "percent": "10"}, {"from_usd": "0", "percent": "5"}],
        [{"from_usd": "0", "percent": "100"}],
        [{"from_usd": "0", "percent": "-1"}],
    ],
)
def test_a_bad_margin_table_is_refused(margin: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError):
        SaleSettings.model_validate({**S.model_dump(mode="json"), "margin": margin})


def test_a_minimum_under_skinslinks_one_dollar_is_refused() -> None:
    with pytest.raises(ValidationError):
        SaleSettings.model_validate({**S.model_dump(mode="json"), "min_sum_usd": "0.5"})


@given(
    usd=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(20_000), places=3),
    rate=st.decimals(min_value=Decimal(9_000), max_value=Decimal(15_000), places=2),
)
def test_an_item_never_pays_more_than_skinslink_pays_us(usd: Decimal, rate: Decimal) -> None:
    q = quote_item(usd, S, rate)
    assert q.price_uzs % 100 == 0
    assert 0 <= q.price_uzs <= usd * rate
    assert q.margin_usd > 0


@given(
    low=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(5_000), places=2),
    step=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(5_000), places=2),
)
def test_a_dearer_item_never_prices_lower(low: Decimal, step: Decimal) -> None:
    assert quote_item(low + step, S, RATE).price_uzs >= quote_item(low, S, RATE).price_uzs


@given(items=st.integers(min_value=0, max_value=10_000_000).map(lambda n: Decimal(n * 100)))
def test_payouts_are_whole_hundreds_and_cards_never_get_more_than_the_items(
    items: Decimal,
) -> None:
    balance = payout_for(items, S, to="balance", card_type=None)
    card = payout_for(items, S, to="card", card_type="uzum_visa")
    assert balance.payout_uzs % 100 == 0 and card.payout_uzs % 100 == 0
    assert card.payout_uzs <= items <= balance.payout_uzs
    assert card.payout_uzs + card.fee_uzs == items
```

```python
# apps/api/tests/integration/test_sales_settings_store.py
"""``sale_settings`` row 1: the default until saved; an unreadable row reads as the default."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.sales.models import SaleSettingsRow
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS
from csmarket.modules.sales.settings_store import read_sale_settings, save_sale_settings
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio


async def test_the_default_until_saved(db_session: AsyncSession) -> None:
    assert await read_sale_settings(db_session) == DEFAULT_SALE_SETTINGS


async def test_a_save_is_read_back_with_its_author(db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    doc = DEFAULT_SALE_SETTINGS.model_copy(update={"enabled": True, "card_min_uzs": 50_000})
    await save_sale_settings(db_session, settings=doc, admin_id=admin.id)
    await db_session.commit()
    assert await read_sale_settings(db_session) == doc
    row = await db_session.get(SaleSettingsRow, 1)
    assert row is not None and row.updated_by == admin.id
    again = doc.model_copy(update={"balance_bonus_pct": Decimal("3")})
    await save_sale_settings(db_session, settings=again, admin_id=admin.id)
    await db_session.commit()
    assert (await read_sale_settings(db_session)).balance_bonus_pct == Decimal("3")


async def test_an_unreadable_row_reads_as_the_switched_off_default(
    db_session: AsyncSession,
) -> None:
    db_session.add(SaleSettingsRow(id=1, settings={"enabled": True, "margin": "nonsense"}))
    await db_session.commit()
    assert await read_sale_settings(db_session) == DEFAULT_SALE_SETTINGS
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_sales_pricing.py tests/integration/test_sales_settings_store.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.sales.pricing`.

- [ ] **Step 3: Export the brackets from `skins`**

`skins/api.py`: extend the existing `from csmarket.modules.skins.pricing import PricingRules, quote, to_uzs` to `from csmarket.modules.skins.pricing import Bracket, PricingRules, bracket_margin, quote, to_uzs` and add `"Bracket"` and `"bracket_margin"` to `__all__`.

- [ ] **Step 4: Write `rules.py`, `pricing.py`, `settings_store.py`**

```python
# apps/api/src/csmarket/modules/sales/rules.py
"""The sale-settings document an admin edits (spec 2026-10-08 §3, §4): ``sale_settings`` row 1.

The margin is progressive by price bracket like the retail brackets (``skins.Bracket``,
reused), but here it is taken **off** Skinslink's price. Fees and the bonus are percents; the
minimum sum is Skinslink's own (1 $) or more. The default ships switched off: the owner sets
the real fees before turning selling on (the card fees below are the demo's placeholders).
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from csmarket.modules.skins.api import Bracket

CardType = Literal["uzcard", "humo", "uzum_visa"]
PayoutTo = Literal["balance", "card"]

#: A margin bracket keeps less than all of the price.
_MAX_PERCENT = Decimal(100)


class CardFees(BaseModel):
    """The fee kept on a payout to each card type, percent."""

    model_config = ConfigDict(frozen=True)

    uzcard: Decimal = Field(ge=0, le=50, max_digits=5, decimal_places=2)
    humo: Decimal = Field(ge=0, le=50, max_digits=5, decimal_places=2)
    uzum_visa: Decimal = Field(ge=0, le=50, max_digits=5, decimal_places=2)

    def of(self, card_type: CardType) -> Decimal:
        """The fee of ``card_type``."""
        return {"uzcard": self.uzcard, "humo": self.humo, "uzum_visa": self.uzum_visa}[card_type]


class SaleSettings(BaseModel):
    """The whole document, as stored in ``sale_settings.settings``."""

    model_config = ConfigDict(frozen=True)

    #: «Выкуп включён»; ``CSMARKET_SALES_ENABLED`` must be on too.
    enabled: bool = False
    #: Our margin, taken off Skinslink's price: each bracket's percent on its slice.
    margin: list[Bracket] = Field(min_length=1)
    #: Percent taken off the CBU rate (the buy side's 1 % uplift is never applied here).
    rate_cut_pct: Decimal = Field(default=Decimal(0), ge=0, le=20, max_digits=5, decimal_places=2)
    #: Percent added to a payout to the balance.
    balance_bonus_pct: Decimal = Field(ge=0, le=20, max_digits=5, decimal_places=2)
    card_fee_pct: CardFees
    #: The smallest payout to a card, whole soʻm.
    card_min_uzs: int = Field(ge=0, le=100_000_000)
    #: The smallest sum of the chosen items' Skinslink prices, USD (Skinslink's floor is 1).
    min_sum_usd: Decimal = Field(default=Decimal(1), ge=1, le=1000, max_digits=7, decimal_places=2)

    @model_validator(mode="after")
    def _brackets(self) -> SaleSettings:
        if self.margin[0].from_usd != 0:
            raise ValueError("margin: the first bracket must start at 0")
        for prev, cur in pairwise(self.margin):
            if cur.from_usd <= prev.from_usd:
                raise ValueError("margin: brackets must ascend strictly")
        if any(not 0 <= b.percent < _MAX_PERCENT for b in self.margin):
            raise ValueError("margin: every percent is at least 0 and under 100")
        return self


DEFAULT_SALE_SETTINGS = SaleSettings(
    enabled=False,
    # The spec's example brackets (2026-10-08).
    margin=[
        Bracket(from_usd=Decimal(0), percent=Decimal(10)),
        Bracket(from_usd=Decimal(1), percent=Decimal(5)),
        Bracket(from_usd=Decimal(10), percent=Decimal(3)),
        Bracket(from_usd=Decimal(100), percent=Decimal(2)),
    ],
    rate_cut_pct=Decimal(0),
    balance_bonus_pct=Decimal(2),
    card_fee_pct=CardFees(uzcard=Decimal(5), humo=Decimal(5), uzum_visa=Decimal(5)),
    card_min_uzs=30_000,
    min_sum_usd=Decimal(1),
)

__all__ = ["DEFAULT_SALE_SETTINGS", "CardFees", "CardType", "PayoutTo", "SaleSettings"]
```

```python
# apps/api/src/csmarket/modules/sales/pricing.py
"""Sale pricing (spec 2026-10-08 §3) — pure functions, no I/O.

``price_uzs = floor100((usd − bracket_margin(usd)) × rate)`` with ``rate`` the CBU rate less
``rate_cut_pct`` (never the buy side's uplift). A payout to the balance adds the bonus, one to
a card takes its type's fee; each is rounded down to 100 soʻm. ``min_prices`` floors each item
at 99 % of its quoted price, so Skinslink never credits us below what we quoted by more.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_FLOOR, Decimal

from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings
from csmarket.modules.skins.api import bracket_margin

_HUNDRED = Decimal(100)
_RATE_PLACES = Decimal("0.0001")
_THREE_PLACES = Decimal("0.001")
#: An item's ``min_prices`` floor, as a share of its quoted Skinslink price.
MIN_PRICE_SHARE = Decimal("0.99")


def floor_100(amount: Decimal) -> Decimal:
    """``amount`` rounded down to a whole hundred soʻm (never below 0)."""
    hundreds = (amount / _HUNDRED).to_integral_value(rounding=ROUND_FLOOR)
    return max(hundreds, Decimal(0)) * _HUNDRED


def sale_rate(cbu_rate: Decimal, settings: SaleSettings) -> Decimal:
    """The CBU rate less ``rate_cut_pct``, rounded down to 4 places."""
    cut = Decimal(1) - settings.rate_cut_pct / _HUNDRED
    return (cbu_rate * cut).quantize(_RATE_PLACES, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class ItemQuote:
    """One item: what we pay for it and the margin we keep, USD."""

    price_uzs: Decimal
    margin_usd: Decimal


def quote_item(price_usd: Decimal, settings: SaleSettings, rate: Decimal) -> ItemQuote:
    """Our price for an item Skinslink prices at ``price_usd``."""
    margin = bracket_margin(price_usd, settings.margin)
    return ItemQuote(price_uzs=floor_100((price_usd - margin) * rate), margin_usd=margin)


@dataclass(frozen=True)
class Payout:
    """A sale's money: the items, the bonus or the fee, what the user gets."""

    items_uzs: Decimal
    bonus_uzs: Decimal
    fee_uzs: Decimal
    payout_uzs: Decimal


def payout_for(
    items_uzs: Decimal, settings: SaleSettings, *, to: PayoutTo, card_type: CardType | None
) -> Payout:
    """The payout of a sale whose items sum to ``items_uzs``.

    Raises:
        ValueError: A card payout without a card type — a caller bug.
    """
    if to == "balance":
        total = floor_100(items_uzs * (1 + settings.balance_bonus_pct / _HUNDRED))
        return Payout(items_uzs, total - items_uzs, Decimal(0), total)
    if card_type is None:
        raise ValueError("a card payout needs a card type")
    total = floor_100(items_uzs * (1 - settings.card_fee_pct.of(card_type) / _HUNDRED))
    return Payout(items_uzs, Decimal(0), items_uzs - total, total)


def min_prices(items: Sequence[tuple[str, Decimal]]) -> dict[str, Decimal]:
    """``{asset_id: floor}``: 99 % of each quoted price, rounded down to 0.001 $."""
    return {
        asset: (price * MIN_PRICE_SHARE).quantize(_THREE_PLACES, rounding=ROUND_DOWN)
        for asset, price in items
    }


def min_sum_uzs(settings: SaleSettings, rate: Decimal) -> Decimal:
    """The minimum sum in soʻm, for the cart's hint: ``min_sum_usd`` priced as one item.

    The API decides on the USD sum; this is what the storefront shows before the click.
    """
    return quote_item(settings.min_sum_usd, settings, rate).price_uzs


__all__ = [
    "MIN_PRICE_SHARE",
    "ItemQuote",
    "Payout",
    "floor_100",
    "min_prices",
    "min_sum_uzs",
    "payout_for",
    "quote_item",
    "sale_rate",
]
```

```python
# apps/api/src/csmarket/modules/sales/settings_store.py
"""Row 1 of ``sale_settings``: read (the default when missing or unreadable) and saved.

No cache: one primary-key read per sell request is cheaper than keeping a copy honest. A row
that no longer parses reads as :data:`DEFAULT_SALE_SETTINGS` — switched off — with a warning,
never as a half-read document that prices sales.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.sales.models import SaleSettingsRow
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, SaleSettings

log = get_logger("csmarket.sales.settings")


async def settings_row(db: AsyncSession) -> SaleSettingsRow | None:
    """Row 1, read fresh."""
    return await db.get(SaleSettingsRow, 1, populate_existing=True)


async def read_sale_settings(db: AsyncSession) -> SaleSettings:
    """The saved document, or the switched-off default."""
    row = await settings_row(db)
    if row is None:
        return DEFAULT_SALE_SETTINGS
    try:
        return SaleSettings.model_validate(row.settings)
    except ValidationError:
        log.warning("sales.settings.row_invalid", reason="falling back to the default")
        return DEFAULT_SALE_SETTINGS


async def save_sale_settings(db: AsyncSession, *, settings: SaleSettings, admin_id: str) -> None:
    """Upsert row 1; flushes, never commits. New sales use it; existing ones keep theirs."""
    document = json.loads(settings.model_dump_json())
    row = await settings_row(db)
    if row is None:
        db.add(SaleSettingsRow(id=1, settings=document, updated_by=admin_id))
    else:
        row.settings, row.updated_by, row.updated_at = document, admin_id, now()
    await db.flush()


__all__ = ["read_sale_settings", "save_sale_settings", "settings_row"]
```

Append to `tests/integration/sales_factory.py`:

```python
from csmarket.modules.sales.models import SaleSettingsRow
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, SaleSettings


async def enable_sales(db: AsyncSession, **over: object) -> SaleSettings:
    """Row 1 = the default document switched on (``over`` replaces any field); commit."""
    doc = DEFAULT_SALE_SETTINGS.model_copy(update={"enabled": True, **over})
    existing = await db.get(SaleSettingsRow, 1)
    document = doc.model_dump(mode="json")
    if existing is None:
        db.add(SaleSettingsRow(id=1, settings=document))
    else:
        existing.settings = document
    await db.commit()
    return doc
```

(move the two new imports to the file's import block.)

- [ ] **Step 5: Run the tests and the linters**

Run: `cd apps/api && uv run pytest tests/unit/test_sales_pricing.py tests/integration/test_sales_settings_store.py tests/unit/test_skins_pricing.py -q && uv run ruff check src/csmarket/modules/sales src/csmarket/modules/skins/api.py tests/unit/test_sales_pricing.py tests/integration/test_sales_settings_store.py tests/integration/sales_factory.py && uv run mypy src/csmarket/modules/sales src/csmarket/modules/skins/api.py`
Expected: PASS; clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/modules/skins/api.py apps/api/tests/unit/test_sales_pricing.py apps/api/tests/integration/test_sales_settings_store.py apps/api/tests/integration/sales_factory.py
git commit -m "feat(api/sales): the sale-settings document and the bracket pricing in soʻm" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Sale letters — the outbox learns `sale_id`, three templates, `sales/letters.py`

**Files:**

- Modify: `apps/api/src/csmarket/modules/notifications/outbox.py` (`enqueue(..., sale_id=None)`)
- Modify: `apps/api/src/csmarket/modules/notifications/copy.py` (sale keys in ru / uz / en)
- Create: `apps/api/src/csmarket/modules/notifications/templates/sale.py`
- Modify: `apps/api/src/csmarket/modules/notifications/templates/__init__.py` (`render`), `templates/base.py` (`Links.sale_url`), `apps/api/src/csmarket/modules/notifications/sender.py` (`_links`)
- Create: `apps/api/src/csmarket/modules/sales/letters.py`
- Test: `apps/api/tests/unit/test_email_templates.py` (append), `apps/api/tests/integration/test_sale_emails.py`

**Interfaces:**

- Consumes: `Sale` (Task 3); `core.money.wire_uzs`.
- Produces: `notifications.api.enqueue(db, *, kind, user_id, order_id=None, sale_id=None, address=None, payload=None) -> str | None` (one letter per `(sale_id, kind)`); `Links.sale_url: str = ""` (`{root}/account/sales/{number}`); `sales.letters.SaleLetter = Literal["sale_hold", "sale_paid", "sale_canceled"]`, `enqueue_sale_letter(db, sale: Sale, kind: SaleLetter, *, amount_uzs: Decimal | None = None, to: Literal["balance", "card"] | None = None, last4: str | None = None) -> None` (payload `number`, `amount_uzs` — the sale's `payout_uzs` unless given — and `to` / `last4` when given).

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/unit/test_email_templates.py`:

```python
SALE_LINKS = Links(
    order_url="",
    balance_url="https://csmarket.test/en/account/transactions",
    confirm_url="",
    sale_url="https://csmarket.test/en/account/sales/S7K2M9QX",
)
SALE_PAYLOADS = {
    "sale_hold": {"number": "S7K2M9QX", "amount_uzs": "158300"},
    "sale_paid": {"number": "S7K2M9QX", "amount_uzs": "158300", "to": "balance"},
    "sale_canceled": {"number": "S7K2M9QX", "amount_uzs": "158300"},
}
#: Never in customer copy: who buys the skins, or the words for their mechanism.
SALE_FORBIDDEN = ("Skinslink", "skinslink", "hold", "deposit", "депозит", "холд")


@pytest.mark.parametrize("locale", ["ru", "uz", "en"])
@pytest.mark.parametrize("kind", ["sale_hold", "sale_paid", "sale_canceled"])
def test_every_sale_letter_renders_in_every_locale(kind: str, locale: str) -> None:
    letter = render(
        kind, locale=locale, number="S7K2M9QX", payload=SALE_PAYLOADS[kind], links=SALE_LINKS  # type: ignore[arg-type]
    )
    assert "S7K2M9QX" in letter.subject
    link = SALE_LINKS.balance_url if kind == "sale_paid" else SALE_LINKS.sale_url
    assert link in letter.text
    for leak in (*FORBIDDEN, *SALE_FORBIDDEN):
        assert leak not in letter.subject + letter.text


def test_a_card_payout_letter_names_the_card_by_its_last_four() -> None:
    payload = {"number": "S7K2M9QX", "amount_uzs": "147400", "to": "card", "last4": "9015"}
    letter = render("sale_paid", locale="ru", number="S7K2M9QX", payload=payload, links=SALE_LINKS)
    assert "147 400 сум" in letter.text
    assert "•••• 9015" in letter.text
    assert SALE_LINKS.sale_url in letter.text


def test_the_sale_copy_is_the_owners() -> None:
    hold = render(
        "sale_hold", locale="ru", number="S7K2M9QX", payload=SALE_PAYLOADS["sale_hold"], links=SALE_LINKS
    )
    assert "158 300 сум поступят через 7 дней" in hold.text
```

```python
# apps/api/tests/integration/test_sale_emails.py
"""Sale letters: one per sale and kind; rendered with the sale's link in the seller's locale."""

from __future__ import annotations

import json

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.dev_transport import DEV_MAIL_KEY, DevTransport
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.notifications.sender import drain_emails
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.users.models import User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_sale

pytestmark = pytest.mark.asyncio


async def test_a_replayed_event_enqueues_one_letter(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold")
    for _ in range(2):
        await enqueue_sale_letter(db_session, sale, "sale_hold")
        await db_session.commit()
    rows = (await db_session.scalars(select(EmailOutbox).where(EmailOutbox.sale_id == sale.id))).all()
    assert [(r.kind, r.order_id, r.payload) for r in rows] == [
        ("sale_hold", None, {"number": sale.number, "amount_uzs": "155200"})
    ]


async def test_a_card_letter_carries_the_last_four_only(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="payout", payout_to="card")
    await enqueue_sale_letter(db_session, sale, "sale_paid", to="card", last4="9015")
    await db_session.commit()
    row = await db_session.scalar(select(EmailOutbox).where(EmailOutbox.sale_id == sale.id))
    assert row is not None
    assert row.payload == {
        "number": sale.number,
        "amount_uzs": "155200",
        "to": "card",
        "last4": "9015",
    }


@pytest.mark.parametrize("locale", ["ru", "uz", "en"])
async def test_the_drain_sends_it_with_the_sale_link(db_session: AsyncSession, locale: str) -> None:
    sale = await make_sale(db_session, status="hold")
    await db_session.execute(
        update(User)
        .where(User.id == sale.user_id)
        .values(email="seller@example.test", email_verified_at=core_clock.now(), locale=locale)
    )
    await enqueue_sale_letter(db_session, sale, "sale_hold")
    await db_session.commit()
    assert await drain_emails(db_session, transport=DevTransport(get_redis())) == 1
    [letter] = [json.loads(x) for x in await get_redis().lrange(DEV_MAIL_KEY, 0, -1)]
    prefix = {"ru": "", "uz": "/uz", "en": "/en"}[locale]
    assert letter["kind"] == "sale_hold"
    assert f"{prefix}/account/sales/{sale.number}" in letter["text"]
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_email_templates.py tests/integration/test_sale_emails.py -q`
Expected: FAIL — `TypeError: Links.__init__() got an unexpected keyword argument 'sale_url'` / `ModuleNotFoundError: csmarket.modules.sales.letters`.

- [ ] **Step 3: The outbox, the links, the copy, the templates**

`notifications/outbox.py` — `enqueue` gains `sale_id` and the matching conflict target (the docstring's Args gain `sale_id: The sale a sale letter reports; None otherwise.` and Returns says "…when this order or sale already has a letter of this kind"):

```python
async def enqueue(
    db: AsyncSession,
    *,
    kind: str,
    user_id: str,
    order_id: str | None = None,
    sale_id: str | None = None,
    address: str | None = None,
    payload: dict[str, str] | None = None,
) -> str | None:
    if kind not in KINDS:
        raise ValueError(f"unknown email kind {kind!r}")
    stmt = insert(EmailOutbox).values(
        kind=kind,
        user_id=user_id,
        order_id=order_id,
        sale_id=sale_id,
        address=address,
        payload=payload or {},
    )
    if sale_id is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["sale_id", "kind"], index_where=EmailOutbox.sale_id.is_not(None)
        )
    else:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["order_id", "kind"], index_where=EmailOutbox.order_id.is_not(None)
        )
    row_id = await db.scalar(stmt.returning(EmailOutbox.id))
    if row_id is None:
        return None
    await db.execute(select(func.pg_notify(EMAILS_CHANNEL, row_id)))
    return str(row_id)
```

`templates/base.py`, in `Links` after `home_url`:

```python
    #: The sale's page (``/account/sales/{number}``); empty for other letters.
    sale_url: str = ""
```

`sender.py`, in `_links(...)`'s `Links(...)` call, after `home_url=root or home,`:

```python
        sale_url=f"{root}/account/sales/{number}" if number else "",
```

`copy.py` — in `COPY["ru"]`, after `"refunded.body"`:

```python
        "sale_hold.subject": "Продажа #{number}: скины получены",
        "sale_hold.body": (
            "Обмен принят. {amount} поступят через 7 дней — мы напишем, когда деньги придут."
        ),
        "sale_paid.subject": "Продажа #{number}: деньги отправлены",
        "sale_paid.body_balance": "{amount} зачислены на баланс csmarket.",
        "sale_paid.body_card": "{amount} отправлены на карту •••• {last4}.",
        "sale_canceled.subject": "Продажа #{number} не состоялась",
        "sale_canceled.body": "Обмен не состоялся, деньги за эту продажу не начисляются.",
```

and after `"button.verify"`: `"button.sale": "Открыть продажу",`.

In `COPY["uz"]`:

```python
        "sale_hold.subject": "#{number} sotuv: skinlar qabul qilindi",
        "sale_hold.body": (
            "Almashuv qabul qilindi. {amount} 7 kundan keyin tushadi — pul kelganda xabar beramiz."
        ),
        "sale_paid.subject": "#{number} sotuv: pul yuborildi",
        "sale_paid.body_balance": "{amount} csmarket balansiga oʻtkazildi.",
        "sale_paid.body_card": "{amount} •••• {last4} kartasiga yuborildi.",
        "sale_canceled.subject": "#{number} sotuv amalga oshmadi",
        "sale_canceled.body": "Almashuv amalga oshmadi, bu sotuv uchun pul hisoblanmaydi.",
```

and `"button.sale": "Sotuvni ochish",`. In `COPY["en"]`:

```python
        "sale_hold.subject": "Sale #{number}: skins received",
        "sale_hold.body": (
            "The trade is accepted. {amount} will arrive in 7 days — we will email you when it does."
        ),
        "sale_paid.subject": "Sale #{number}: money sent",
        "sale_paid.body_balance": "{amount} is on your csmarket balance.",
        "sale_paid.body_card": "{amount} was sent to the card •••• {last4}.",
        "sale_canceled.subject": "Sale #{number} did not go through",
        "sale_canceled.body": "The trade did not happen; nothing is paid for this sale.",
```

and `"button.sale": "Open sale",`. Add `{last4}` to the module docstring's placeholder list.

```python
# apps/api/src/csmarket/modules/notifications/templates/sale.py
"""Sale letters (spec 2026-10-08 §8): the trade accepted, the money sent, the sale off.

The reader sold skins and waits for money: no names of who buys them, no "hold", no
"deposit". A card is named by its last four digits only.
"""

from __future__ import annotations

from collections.abc import Mapping

from csmarket.modules.notifications.copy import COPY
from csmarket.modules.notifications.templates.base import (
    EmailContent,
    Links,
    Locale,
    amount,
    compose,
)


def hold(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The trade is accepted; the money comes in 7 days."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["sale_hold.subject"].format(number=number),
        body=words["sale_hold.body"].format(amount=amount(payload.get("amount_uzs", "0"), locale)),
        href=links.sale_url,
        label=words["button.sale"],
        links=links,
    )


def paid(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The money is on the balance (``to`` = ``balance``) or sent to a card (``card``)."""
    words = COPY[locale]
    money = amount(payload.get("amount_uzs", "0"), locale)
    to_card = payload.get("to") == "card"
    body = (
        words["sale_paid.body_card"].format(amount=money, last4=payload.get("last4", ""))
        if to_card
        else words["sale_paid.body_balance"].format(amount=money)
    )
    return compose(
        locale=locale,
        subject=words["sale_paid.subject"].format(number=number),
        body=body,
        href=links.sale_url if to_card else links.balance_url,
        label=words["button.sale"] if to_card else words["button.balance"],
        links=links,
    )


def canceled(
    *, locale: Locale, number: str, payload: Mapping[str, str], links: Links
) -> EmailContent:
    """The sale did not go through; nothing is paid."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["sale_canceled.subject"].format(number=number),
        body=words["sale_canceled.body"],
        href=links.sale_url,
        label=words["button.sale"],
        links=links,
    )
```

`templates/__init__.py`: import `sale` beside the others and extend the map (and the `render` docstring: "`kind`: an order letter, a sale letter or `verify`"; "`number`: the order's or sale's number"):

```python
from csmarket.modules.notifications.templates import receipt, refunded, sale, trade_sent, verify

_ORDER_LETTERS = {
    "receipt": receipt.build,
    "trade_sent": trade_sent.build,
    "refunded": refunded.build,
    "sale_hold": sale.hold,
    "sale_paid": sale.paid,
    "sale_canceled": sale.canceled,
}
```

- [ ] **Step 4: `sales/letters.py`**

```python
"""Sale letters, enqueued in the transaction of the event they report (spec 2026-10-08 §8).

``sale_hold`` when the trade is accepted, ``sale_paid`` when the money is on the balance or
an admin paid the card (or rejected it and the money went to the balance), ``sale_canceled``
when an offered sale closes or is reverted. One letter per sale and kind (a replay enqueues
nothing); whether it is sent is decided at send time (a verified address). The payload
snapshots the number and the amount; a card appears by its last four digits only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.money import wire_uzs
from csmarket.modules.notifications.api import enqueue
from csmarket.modules.sales.models import Sale

SaleLetter = Literal["sale_hold", "sale_paid", "sale_canceled"]


async def enqueue_sale_letter(
    db: AsyncSession,
    sale: Sale,
    kind: SaleLetter,
    *,
    amount_uzs: Decimal | None = None,
    to: Literal["balance", "card"] | None = None,
    last4: str | None = None,
) -> None:
    """Queue ``kind`` about ``sale``; flushes with the caller's transaction, never commits."""
    payload = {
        "number": sale.number,
        "amount_uzs": wire_uzs(amount_uzs if amount_uzs is not None else sale.payout_uzs),
    }
    if to is not None:
        payload["to"] = to
    if last4 is not None:
        payload["last4"] = last4
    await enqueue(db, kind=kind, user_id=sale.user_id, sale_id=sale.id, payload=payload)


__all__ = ["SaleLetter", "enqueue_sale_letter"]
```

- [ ] **Step 5: Run the tests and the linters**

Run: `cd apps/api && uv run pytest tests/unit/test_email_templates.py tests/integration/test_sale_emails.py tests/integration/test_order_emails.py tests/integration/test_email_outbox.py -q && uv run ruff check src/csmarket/modules/notifications src/csmarket/modules/sales tests/unit/test_email_templates.py tests/integration/test_sale_emails.py && uv run mypy src/csmarket/modules/notifications src/csmarket/modules/sales`
Expected: PASS (order letters unchanged); clean. If a copy-parity test exists for `copy.py` it passes because all three locales gained the same keys.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/csmarket/modules/notifications apps/api/src/csmarket/modules/sales/letters.py apps/api/tests/unit/test_email_templates.py apps/api/tests/integration/test_sale_emails.py
git commit -m "feat(api/notifications): sale letters — skins received, money sent, sale off" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Payout cards — checked, encrypted, listed by the last four

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/cards.py`, `apps/api/src/csmarket/modules/sales/cards_routes.py`, `apps/api/src/csmarket/modules/sales/schemas.py`
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `cards_routes.router`)
- Modify: `apps/api/src/csmarket/modules/sales/api.py` (exports)
- Test: `apps/api/tests/unit/test_sales_cards.py`, `apps/api/tests/integration/test_sales_cards.py`

**Interfaces:**

- Consumes: `PayoutCard`, `CARD_PURPOSE` (Task 3); `core.crypto.encrypt/decrypt`; `users.api.User`; `auth.api.current_user`; `core.idempotency.require_idempotency_key`.
- Produces in `cards.py`: `MAX_LIVE_CARDS = 3`, `luhn_ok(digits: str) -> bool`, `card_digits(card_type: str, raw: str) -> str` (raises `ValidationError(code="card_invalid")`, never echoing the number), `live_cards(db, user_id) -> list[PayoutCard]`, `add_card(db, *, user_id: str, card_type: CardType, raw_number: str) -> PayoutCard` (locks the user row; 409 `cards_limit`), `owned_card(db, *, user_id: str, card_id: str) -> PayoutCard` (404 for another's, unknown or deleted), `delete_card(db, *, user_id: str, card_id: str) -> None` (soft; a repeat is a no-op), `reveal_number(card: PayoutCard) -> str`, `masked(last4: str) -> str` (`"•••• 9015"`).
- Produces in `schemas.py`: `CardOut(id: str, type: CardType, last4: str, created_at: datetime)` with `.of(card)`, `CardsOut(items: list[CardOut])`.
- Produces routes: `GET /api/v1/payout-cards` → `CardsOut`; `DELETE /api/v1/payout-cards/{card_id}` (`Idempotency-Key` required) → 204.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/unit/test_sales_cards.py
"""Card checks: 16 digits, the type's prefix, Luhn; a refusal never says the number."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.sales.cards import card_digits, luhn_ok, masked

HUMO = "9860123456789015"
UZCARD = "8600123456789012"
VISA = "4000000000000002"


@pytest.mark.parametrize("number", [HUMO, UZCARD, VISA])
def test_luhn_accepts_the_fake_cards(number: str) -> None:
    assert luhn_ok(number)


def test_luhn_refuses_a_typo() -> None:
    assert not luhn_ok("9860123456789016")


@pytest.mark.parametrize(
    ("card_type", "raw", "digits"),
    [
        ("humo", "9860 1234 5678 9015", HUMO),
        ("uzcard", "8600-1234-5678-9012", UZCARD),
        ("uzcard", "5614 1234 5678 9012", "5614123456789012"),  # Uzcard's 5614 range (owner)
        ("uzum_visa", VISA, VISA),
    ],
)
def test_spaces_and_dashes_are_dropped(card_type: str, raw: str, digits: str) -> None:
    assert card_digits(card_type, raw) == digits


@pytest.mark.parametrize(
    ("card_type", "raw"),
    [
        ("humo", UZCARD),  # another type's prefix
        ("uzcard", HUMO),
        ("uzum_visa", HUMO),
        ("humo", "9860123456789016"),  # Luhn
        ("humo", HUMO[:-1]),  # 15 digits
        ("humo", HUMO + "0"),  # 17 digits
        ("humo", "98601234567890１５"),  # full-width digits
        ("mastercard", "5100000000000008"),  # not a type we pay to
    ],
)
def test_a_bad_number_is_refused_without_echoing_it(card_type: str, raw: str) -> None:
    with pytest.raises(ValidationError) as caught:
        card_digits(card_type, raw)
    assert caught.value.extra.get("code") == "card_invalid"
    assert raw not in str(caught.value) and raw not in repr(caught.value.extra)


def test_masked_shows_the_last_four() -> None:
    assert masked("9015") == "•••• 9015"
```

```python
# apps/api/tests/integration/test_sales_cards.py
"""Saved payout cards: at most three, encrypted at rest, listed and logged by the last four."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.modules.sales.cards import (
    add_card,
    delete_card,
    live_cards,
    owned_card,
    reveal_number,
)
from csmarket.modules.sales.models import PayoutCard
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import HUMO, UZCARD, VISA, make_card

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
KEY = {"Idempotency-Key": "test-card-delete-0001"}


async def test_a_card_number_is_stored_encrypted_and_never_logged_or_listed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
) -> None:
    headers = await customer_headers()
    user_id = (await integration_client.get("/api/v1/me", headers=headers)).json()["id"]
    with capture_logs() as logs:
        card = await add_card(db_session, user_id=user_id, card_type="humo", raw_number=HUMO)
        await db_session.commit()
    assert HUMO not in repr(logs)
    assert any(e.get("last4") == "9015" for e in logs)
    raw = (
        await db_session.execute(
            text("SELECT number_enc::text, number_nonce::text FROM payout_cards WHERE id = :id"),
            {"id": card.id},
        )
    ).one()
    assert HUMO not in raw[0] and HUMO.encode().hex() not in raw[0]
    assert reveal_number(card) == HUMO
    r = await integration_client.get("/api/v1/payout-cards", headers=headers)
    assert r.status_code == 200
    assert HUMO not in r.text
    [item] = r.json()["items"]
    assert (item["id"], item["type"], item["last4"]) == (card.id, "humo", "9015")
    assert CUSTOMER_STEAM_ID not in r.text


async def test_a_fourth_live_card_is_cards_limit(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    for number, kind in ((HUMO, "humo"), (UZCARD, "uzcard"), (VISA, "uzum_visa")):
        await add_card(db_session, user_id=user.id, card_type=kind, raw_number=number)
    await db_session.commit()
    with pytest.raises(ConflictError) as caught:
        await add_card(db_session, user_id=user.id, card_type="humo", raw_number=HUMO)
    assert caught.value.extra["code"] == "cards_limit"
    await db_session.rollback()
    first = (await live_cards(db_session, user.id))[0]
    await delete_card(db_session, user_id=user.id, card_id=first.id)
    await add_card(db_session, user_id=user.id, card_type="humo", raw_number=HUMO)
    await db_session.commit()
    assert len(await live_cards(db_session, user.id)) == 3


async def test_another_users_or_a_deleted_card_is_not_found(db_session: AsyncSession) -> None:
    owner, other = await make_user(db_session), await make_user(db_session)
    card = await make_card(db_session, owner)
    with pytest.raises(NotFoundError):
        await owned_card(db_session, user_id=other.id, card_id=card.id)
    await delete_card(db_session, user_id=owner.id, card_id=card.id)
    await delete_card(db_session, user_id=owner.id, card_id=card.id)  # a repeat is a no-op
    await db_session.commit()
    with pytest.raises(NotFoundError):
        await owned_card(db_session, user_id=owner.id, card_id=card.id)
    stored = await db_session.scalar(select(PayoutCard).where(PayoutCard.id == card.id))
    assert stored is not None and stored.deleted_at is not None  # soft: a request may point at it


async def test_delete_route_needs_a_key_and_answers_204(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    user_id = (await integration_client.get("/api/v1/me", headers=headers)).json()["id"]
    card = await add_card(db_session, user_id=user_id, card_type="humo", raw_number=HUMO)
    await db_session.commit()
    url = f"/api/v1/payout-cards/{card.id}"
    assert (await integration_client.delete(url, headers=headers)).status_code == 422
    for _ in range(2):
        r = await integration_client.delete(url, headers={**headers, **KEY})
        assert r.status_code == 204
    r = await integration_client.get("/api/v1/payout-cards", headers=headers)
    assert r.json()["items"] == []


async def test_someone_elses_card_cannot_be_deleted(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    card = await make_card(db_session, await make_user(db_session))
    r = await integration_client.delete(f"/api/v1/payout-cards/{card.id}", headers={**headers, **KEY})
    assert r.status_code == 404
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_sales_cards.py tests/integration/test_sales_cards.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.sales.cards`.

- [ ] **Step 3: Write `cards.py`**

```python
"""Saved payout cards (spec 2026-10-08 §2, §4): checked, encrypted, shown by the last four.

A number is checked — 16 ASCII digits, the type's prefix, Luhn — and stored encrypted under
:data:`~csmarket.modules.sales.models.CARD_PURPOSE`; only ``last4`` is ever logged, listed,
replayed or put in a letter. The full number leaves the database through
:func:`reveal_number` alone, which only the admin's audited reveal calls. At most
:data:`MAX_LIVE_CARDS` live cards per user (the user row is locked while counting, so two
adds cannot both pass). A delete is soft: a paid request keeps pointing at its card.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.crypto import decrypt, encrypt
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.sales.models import CARD_PURPOSE, PayoutCard
from csmarket.modules.sales.rules import CardType
from csmarket.modules.users.api import User

log = get_logger("csmarket.sales.cards")

MAX_LIVE_CARDS = 3
_LENGTH = 16
#: The first digits of each card type we pay to (Uzcard, Humo, Uzum Visa).
_PREFIXES: dict[str, tuple[str, ...]] = {
    "uzcard": ("8600", "5614"),
    "humo": ("9860",),
    "uzum_visa": ("4",),
}


def luhn_ok(digits: str) -> bool:
    """Whether ``digits`` pass the Luhn check (every second digit from the right doubled)."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        total += sum(divmod(digit * 2, 10)) if index % 2 == 1 else digit
    return total % 10 == 0


def card_digits(card_type: str, raw: str) -> str:
    """The 16 digits of ``raw`` (spaces and dashes dropped) if they fit ``card_type``.

    Raises:
        ValidationError: ``code="card_invalid"`` — the message never contains the number.
    """
    digits = raw.replace(" ", "").replace("-", "")
    prefixes = _PREFIXES.get(card_type)
    fits = (
        prefixes is not None
        and len(digits) == _LENGTH
        and digits.isascii()
        and digits.isdigit()
        and digits.startswith(prefixes)
        and luhn_ok(digits)
    )
    if not fits:
        raise ValidationError("this card number is not valid", code="card_invalid")
    return digits


def masked(last4: str) -> str:
    """How a card is shown: ``•••• 9015``."""
    return f"•••• {last4}"


async def live_cards(db: AsyncSession, user_id: str) -> list[PayoutCard]:
    """The user's live cards, oldest first."""
    rows = await db.scalars(
        select(PayoutCard)
        .where(PayoutCard.user_id == user_id, PayoutCard.deleted_at.is_(None))
        .order_by(PayoutCard.created_at, PayoutCard.id)
    )
    return list(rows.all())


async def add_card(
    db: AsyncSession, *, user_id: str, card_type: CardType, raw_number: str
) -> PayoutCard:
    """Check, encrypt and save a card; flushes, never commits.

    Raises:
        ValidationError: ``card_invalid``.
        ConflictError: ``cards_limit`` — the user already has :data:`MAX_LIVE_CARDS`.
    """
    digits = card_digits(card_type, raw_number)
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    if len(await live_cards(db, user_id)) >= MAX_LIVE_CARDS:
        raise ConflictError("you already have 3 saved cards", code="cards_limit")
    enc, nonce = encrypt(digits, purpose=CARD_PURPOSE)
    card = PayoutCard(
        id=new_id(),
        user_id=user_id,
        type=card_type,
        number_enc=enc,
        number_nonce=nonce,
        last4=digits[-4:],
    )
    db.add(card)
    await db.flush()
    log.info("sales.card.added", card_type=card_type, last4=card.last4)
    return card


async def owned_card(db: AsyncSession, *, user_id: str, card_id: str) -> PayoutCard:
    """The user's live card ``card_id``.

    Raises:
        NotFoundError: Another user's, unknown or deleted.
    """
    card = await db.scalar(
        select(PayoutCard).where(
            PayoutCard.id == card_id,
            PayoutCard.user_id == user_id,
            PayoutCard.deleted_at.is_(None),
        )
    )
    if card is None:
        raise NotFoundError("card not found")
    return card


async def delete_card(db: AsyncSession, *, user_id: str, card_id: str) -> None:
    """Forget the user's card (soft); an already deleted one is left as it is. Flushes.

    Raises:
        NotFoundError: Another user's or unknown.
    """
    card = await db.scalar(
        select(PayoutCard).where(PayoutCard.id == card_id, PayoutCard.user_id == user_id)
    )
    if card is None:
        raise NotFoundError("card not found")
    if card.deleted_at is None:
        card.deleted_at = now()
        await db.flush()
        log.info("sales.card.deleted", last4=card.last4)


def reveal_number(card: PayoutCard) -> str:
    """The full number — for the admin's audited reveal only. PII: never log the result."""
    return decrypt(card.number_enc, card.number_nonce, purpose=CARD_PURPOSE)


__all__ = [
    "MAX_LIVE_CARDS",
    "add_card",
    "card_digits",
    "delete_card",
    "live_cards",
    "luhn_ok",
    "masked",
    "owned_card",
    "reveal_number",
]
```

- [ ] **Step 4: Schemas, routes, mount**

```python
# apps/api/src/csmarket/modules/sales/schemas.py
"""Customer wire shapes of ``sales``. Money travels as strings of whole soʻm."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from csmarket.modules.sales.models import PayoutCard
from csmarket.modules.sales.rules import CardType


class CardOut(BaseModel):
    """A saved card: its type and last four digits, never the number."""

    id: str
    type: CardType
    last4: str
    created_at: datetime

    @classmethod
    def of(cls, card: PayoutCard) -> CardOut:
        """Build from a row."""
        return cls(
            id=card.id,
            type=card.type,  # type: ignore[arg-type]  # the column's check admits only CardType
            last4=card.last4,
            created_at=card.created_at,
        )


class CardsOut(BaseModel):
    """The user's live cards, oldest first."""

    items: list[CardOut]
```

```python
# apps/api/src/csmarket/modules/sales/cards_routes.py
"""``/api/v1/payout-cards`` — the signed-in user's saved payout cards (spec 2026-10-08 §5).

A card is added only with a sale (``POST /sell`` with ``new_card``); here it is listed and
forgotten. Routers parse and dispatch; the logic is :mod:`.cards`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, require_idempotency_key
from csmarket.modules.auth.api import current_user
from csmarket.modules.sales.cards import delete_card, live_cards
from csmarket.modules.sales.schemas import CardOut, CardsOut
from csmarket.modules.users.api import User

router = APIRouter(prefix="/payout-cards", tags=["sales"])

Db = Annotated[AsyncSession, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]


@router.get("", response_model=CardsOut, summary="My payout cards")
async def get_cards(user: Me, db: Db) -> CardsOut:
    """Live cards, oldest first: type and last four digits."""
    return CardsOut(items=[CardOut.of(c) for c in await live_cards(db, user.id)])


@router.delete(
    "/{card_id}",
    status_code=204,
    responses={404: {"description": "Not my card"}},
    summary="Forget a payout card",
)
async def remove_card(
    card_id: uuid.UUID,
    user: Me,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> Response:
    """Soft delete; the key is required and the delete is its own replay (a repeat is 204)."""
    require_idempotency_key(idempotency_key)
    await delete_card(db, user_id=user.id, card_id=str(card_id))
    await db.commit()
    return Response(status_code=204)


__all__ = ["router"]
```

`api/v1/router.py`: `from csmarket.modules.sales.cards_routes import router as payout_cards_router` (alphabetical among the imports) and `router.include_router(payout_cards_router)` after `payments_router`.

`sales/api.py`:

```python
"""Public interface of the ``sales`` module — other modules import from here only."""

from __future__ import annotations

from csmarket.modules.sales.cards import MAX_LIVE_CARDS, masked
from csmarket.modules.sales.models import SALES_CHANNEL

__all__ = ["MAX_LIVE_CARDS", "SALES_CHANNEL", "masked"]
```

- [ ] **Step 5: Run the tests, the linters, regenerate the API**

Run: `cd apps/api && uv run pytest tests/unit/test_sales_cards.py tests/integration/test_sales_cards.py -q && uv run ruff check src/csmarket/modules/sales src/csmarket/api tests/unit/test_sales_cards.py tests/integration/test_sales_cards.py && uv run mypy src/csmarket/modules/sales && cd ../.. && make gen-api`
Expected: PASS; clean; `docs/api/openapi.json` and `packages/api-client` gain `/payout-cards`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/api/v1/router.py apps/api/tests/unit/test_sales_cards.py apps/api/tests/integration/test_sales_cards.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/sales): payout cards — Luhn and prefix checks, encrypted at rest, last four only" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The status machine — transitions, the idempotent credit, payout requests, the sale nudge

**Files:**

- Create: `apps/api/src/csmarket/modules/wallet/sales.py`
- Modify: `apps/api/src/csmarket/modules/wallet/service.py` (`NORMAL_SIDE`, `TX_KINDS`), `apps/api/src/csmarket/modules/wallet/api.py` (exports)
- Modify: `apps/api/src/csmarket/modules/realtime/api.py` (`nudge_sale`), `realtime/listener.py` (`_on_notify`), `realtime/registry.py` (`publish(..., kind=)`)
- Modify: `apps/api/src/csmarket/core/metrics.py` (`csmarket_sale_outcomes_total`)
- Create: `apps/api/src/csmarket/modules/sales/payouts.py`, `apps/api/src/csmarket/modules/sales/status.py`
- Modify: `apps/api/src/csmarket/modules/sales/api.py` (exports)
- Create: `apps/api/tests/integration/fake_deposit_client.py`
- Test: `apps/api/tests/integration/test_wallet_sales.py`, `apps/api/tests/integration/test_sales_status.py`, `apps/api/tests/unit/test_realtime_registry.py` (append), `apps/api/tests/unit/test_realtime_listener_kinds.py`

**Interfaces:**

- Consumes: `Deposit`, `DepositClient`, `SkinslinkError`, `SkinslinkUnavailableError` (`skinslink.api`, Task 2); `Sale`, `PayoutRequest`, `OPEN_STATUSES` (Task 3); `enqueue_sale_letter` (Task 5).
- Produces in `wallet` (re-exported by `wallet.api`): `credit_sale(db, *, user_id: str, sale_id: str, amount: Decimal) -> WalletTransaction` (key `sale:{sale_id}`, kind `sale_credit`), `credit_payout_return(db, *, user_id: str, sale_id: str, request_id: str, amount: Decimal, actor: str) -> WalletTransaction` (key `payout_return:{request_id}`, kind `payout_return`); `NORMAL_SIDE["house_skin_buys"] == "C"`.
- Produces in `realtime.api`: `nudge_sale(db, *, user_id: str, number: str) -> None` (payload `user_id:number:sale`; the socket frame `{"type": "sale.updated", "number": …}`); `Registry.publish(user_id, number, *, kind: Literal["order", "sale"] = "order") -> int`.
- Produces in `core.metrics`: `record_sale_outcome(outcome: str) -> None`.
- Produces in `sales/payouts.py`: `request_of(db, sale_id: str, *, lock: bool = False) -> PayoutRequest | None`, `open_request(db, sale: Sale, *, status: Literal["waiting_hold", "to_pay"]) -> PayoutRequest`, `cancel_request(db, sale: Sale) -> None`.
- Produces in `sales/status.py`: `Outcome = Literal["unchanged", "offered", "hold", "credited", "payout", "closed", "reverted", "attention"]`, `NOT_FOUND_GRACE = timedelta(minutes=2)`, `lock_sale(db, sale_id: str) -> Sale | None`, `apply_deposit(db, sale: Sale, deposit: Deposit | None, *, at: datetime) -> Outcome` (caller holds the lock; flushes, never commits), `check_sale(db, client: DepositClient, *, sale_id: str) -> Outcome` (commits).
- Produces in tests: `fake_deposit_client.deposit(status="active", **over) -> Deposit`, `inv_item(asset_id: str, price: str, name: str = ...) -> InventoryItem`, `FakeDepositClient(*, inventory=..., created=..., status=...)` with `.inventory_calls`, `.deposit_calls`, `.status_calls`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/fake_deposit_client.py
"""A scripted Skinslink deposit client for the sales tests (no HTTP)."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

from csmarket.modules.skinslink.api import Deposit, Inventory, InventoryItem


def deposit(status: str = "active", **over: object) -> Deposit:
    """A Skinslink deposit report (``over`` replaces any field)."""
    base: dict[str, object] = {
        "id": 42,
        "merchant_tx_id": None,
        "status": status,
        "amount_usd": None,
        "bot_name": "Bot #3",
        "trade_offer_id": "6912345678",
        "offer_expiry_at": "2026-10-08T12:30:00Z",
        "hold_end_date": None,
        "fail_reason": None,
    }
    base.update(over)
    return Deposit(**base)  # type: ignore[arg-type]  # the test's own field values


def inv_item(
    asset_id: str, price: str, name: str = "AK-47 | Redline (Field-Tested)"
) -> InventoryItem:
    """An inventory card priced at ``price`` USD."""
    return InventoryItem(
        id=asset_id,
        name=name,
        price_usd=Decimal(price),
        image_url=f"https://img.test/{asset_id}.png",
        exterior="Field-Tested",
        rarity="Classified",
        rarity_color="#d32ce6",
    )


class FakeDepositClient:
    """``inventory``: answers popped per call (the last one repeats); ``created``: the
    create-deposit answer or exception; ``status``: the deposit-status answer or exception."""

    def __init__(
        self,
        *,
        inventory: Sequence[Inventory | BaseException] = (),
        created: Deposit | BaseException | None = None,
        status: Deposit | BaseException | None = None,
    ) -> None:
        self.inventories: deque[Inventory | BaseException] = deque(inventory)
        self.created = created
        self.status = status
        self.inventory_calls = 0
        self.deposit_calls: list[dict[str, object]] = []
        self.status_calls: list[str] = []

    async def inventory(self, *, partner: int, token: str) -> Inventory:
        self.inventory_calls += 1
        answer = self.inventories.popleft() if len(self.inventories) > 1 else self.inventories[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def create_deposit(
        self,
        *,
        merchant_tx_id: str,
        partner: int,
        token: str,
        asset_ids: Sequence[str],
        min_prices: Mapping[str, Decimal],
    ) -> Deposit:
        self.deposit_calls.append(
            {"merchant_tx_id": merchant_tx_id, "asset_ids": list(asset_ids), "min_prices": dict(min_prices)}
        )
        if isinstance(self.created, BaseException):
            raise self.created
        assert self.created is not None, "script a create-deposit answer"
        return replace(self.created, merchant_tx_id=merchant_tx_id)

    async def deposit_status(self, *, merchant_tx_id: str) -> Deposit | None:
        self.status_calls.append(merchant_tx_id)
        if isinstance(self.status, BaseException):
            raise self.status
        return self.status
```

```python
# apps/api/tests/integration/test_wallet_sales.py
"""A sale on the ledger: credited once per sale, a rejected payout once per request."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.wallet.api import (
    balance,
    credit_payout_return,
    credit_sale,
    ensure_account,
    user_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio


async def test_a_sale_is_credited_once_whatever_the_amount_of_a_replay(
    db_session: AsyncSession,
) -> None:
    user, sale_id = await make_user(db_session), new_id()
    first = await credit_sale(db_session, user_id=user.id, sale_id=sale_id, amount=Decimal(158_300))
    again = await credit_sale(db_session, user_id=user.id, sale_id=sale_id, amount=Decimal(999))
    await db_session.commit()
    assert again.id == first.id
    assert (first.kind, first.idempotency_key) == ("sale_credit", f"sale:{sale_id}")
    assert await user_balance(db_session, user.id) == Decimal(158_300)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_skin_buys"
    )
    assert await balance(db_session, house.id) == Decimal(158_300)


async def test_a_payout_return_is_keyed_by_its_request(db_session: AsyncSession) -> None:
    user, sale_id, request_id = await make_user(db_session), new_id(), new_id()
    txn = await credit_payout_return(
        db_session,
        user_id=user.id,
        sale_id=sale_id,
        request_id=request_id,
        amount=Decimal(155_200),
        actor="admin:x",
    )
    await credit_payout_return(
        db_session,
        user_id=user.id,
        sale_id=sale_id,
        request_id=request_id,
        amount=Decimal(155_200),
        actor="admin:x",
    )
    await db_session.commit()
    assert (txn.kind, txn.idempotency_key, txn.reference_type, txn.reference_id) == (
        "payout_return",
        f"payout_return:{request_id}",
        "sale",
        sale_id,
    )
    assert await user_balance(db_session, user.id) == Decimal(155_200)
```

```python
# apps/api/tests/integration/test_sales_status.py
"""The status machine (spec 2026-10-08 §6): every transition, the credit once, reversals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.realtime.api import CHANNEL
from csmarket.modules.sales.models import Sale
from csmarket.modules.sales.payouts import request_of
from csmarket.modules.sales.status import Outcome, apply_deposit, check_sale, lock_sale
from csmarket.modules.skinslink.api import Deposit, SkinslinkUnavailableError
from csmarket.modules.wallet.api import WalletTransaction, user_balance
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.orders_factory import listen_channel
from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio


async def _apply(db: AsyncSession, sale: Sale, report: Deposit | None) -> Outcome:
    locked = await lock_sale(db, sale.id)
    assert locked is not None
    outcome = await apply_deposit(db, locked, report, at=now())
    await db.commit()
    return outcome


async def _fresh(db: AsyncSession, sale: Sale) -> Sale:
    row = await db.get(Sale, sale.id, populate_existing=True)
    assert row is not None
    return row


async def _letters(db: AsyncSession, sale: Sale) -> list[str]:
    rows = await db.scalars(
        select(EmailOutbox.kind).where(EmailOutbox.sale_id == sale.id).order_by("created_at")
    )
    return list(rows)


async def _credits(db: AsyncSession, sale: Sale) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(WalletTransaction)
            .where(WalletTransaction.reference_id == sale.id)
        )
        or 0
    )


async def test_an_active_deposit_offers_the_creating_sale(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="creating")
    report = deposit("active", amount_usd=Decimal("12.95"))
    assert await _apply(db_session, sale, report) == "offered"
    s = await _fresh(db_session, sale)
    assert (s.status, s.trade_id, s.trade_offer_id, s.bot_name) == (
        "offered",
        42,
        "6912345678",
        "Bot #3",
    )
    assert s.offer_expiry_at == datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
    assert s.amount_usd == Decimal("12.95")
    assert await _apply(db_session, sale, deposit("pending")) == "unchanged"


async def test_hold_never_steps_back_to_offered(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold")
    assert await _apply(db_session, sale, deposit("active")) == "unchanged"
    assert (await _fresh(db_session, sale)).status == "hold"


async def test_hold_stores_its_end_and_opens_a_waiting_card_request(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, payout_to="card", payout_uzs=Decimal(147_400))
    report = deposit("hold", hold_end_date="2026-10-15T10:00:00Z")
    assert await _apply(db_session, sale, report) == "hold"
    s = await _fresh(db_session, sale)
    assert s.hold_end_at == datetime(2026, 10, 15, 10, tzinfo=UTC)
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert (request.status, request.amount_uzs, request.fee_uzs, request.to_pay_at) == (
        "waiting_hold",
        Decimal(147_400),
        Decimal(7_800),
        None,
    )
    assert await _letters(db_session, sale) == ["sale_hold"]


async def test_completed_twice_credits_the_balance_once(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    assert await _apply(db_session, sale, deposit("completed")) == "credited"
    assert await _apply(db_session, sale, deposit("completed")) == "unchanged"
    s = await _fresh(db_session, sale)
    assert s.status == "credited" and s.credited_at is not None
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    assert await _credits(db_session, sale) == 1
    assert await _letters(db_session, sale) == ["sale_paid"]


async def test_completed_makes_a_card_request_payable(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", payout_uzs=Decimal(147_400))
    await _apply(db_session, sale, deposit("hold"))
    assert await _apply(db_session, sale, deposit("completed")) == "payout"
    request = await request_of(db_session, sale.id)
    assert request is not None and request.status == "to_pay" and request.to_pay_at is not None
    assert (await _fresh(db_session, sale)).status == "payout"
    assert await user_balance(db_session, sale.user_id) == 0


async def test_completed_without_a_hold_still_opens_a_payable_request(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, payout_to="card")
    assert await _apply(db_session, sale, deposit("completed")) == "payout"
    request = await request_of(db_session, sale.id)
    assert request is not None and request.status == "to_pay"


async def test_failed_closes_and_cancels_the_request(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold", payout_to="card")
    await make_request(db_session, sale, status="waiting_hold")
    report = deposit("failed", fail_reason="canceled_by_user")
    assert await _apply(db_session, sale, report) == "closed"
    s = await _fresh(db_session, sale)
    assert (s.status, s.fail_reason) == ("closed", "canceled_by_user")
    request = await request_of(db_session, sale.id)
    assert request is not None and request.status == "canceled"
    assert await _letters(db_session, sale) == ["sale_canceled"]


async def test_a_creating_sale_that_fails_closes_without_a_letter(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="creating")
    assert await _apply(db_session, sale, deposit("canceled")) == "closed"
    assert await _letters(db_session, sale) == []


async def test_reverted_out_of_hold_pays_nothing_and_cancels_the_request(
    db_session: AsyncSession,
) -> None:
    card_sale = await make_sale(db_session, status="hold", payout_to="card")
    await make_request(db_session, card_sale, status="waiting_hold")
    balance_sale = await make_sale(db_session, status="hold")
    for sale in (card_sale, balance_sale):
        report = deposit("reverted", fail_reason="user_reverted")
        assert await _apply(db_session, sale, report) == "reverted"
        assert (await _fresh(db_session, sale)).fail_reason == "user_reverted"
        assert await user_balance(db_session, sale.user_id) == 0
        assert await _credits(db_session, sale) == 0
    request = await request_of(db_session, card_sale.id)
    assert request is not None and request.status == "canceled"


async def test_reverted_after_a_credit_opens_rolled_back_and_never_debits(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    await _apply(db_session, sale, deposit("completed"))
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    assert await _apply(db_session, sale, deposit("reverted")) == "unchanged"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("credited", "rolled_back")
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    assert await _credits(db_session, sale) == 1


async def test_a_reverted_payout_still_to_pay_is_reverted(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, sale, status="to_pay")
    assert await _apply(db_session, sale, deposit("reverted")) == "reverted"
    request = await request_of(db_session, sale.id)
    assert request is not None and request.status == "canceled"


async def test_a_reverted_payout_already_paid_waits_for_an_admin(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, sale, status="paid")
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("payout", "rolled_back")


async def test_a_creating_sale_unknown_after_the_grace_closes(db_session: AsyncSession) -> None:
    young = await make_sale(db_session, status="creating")
    assert await _apply(db_session, young, None) == "unchanged"
    old = await make_sale(db_session, status="creating", created_at=now() - timedelta(minutes=3))
    assert await _apply(db_session, old, None) == "closed"
    assert (await _fresh(db_session, old)).fail_reason == "not_created"


async def test_a_closed_sale_reported_alive_is_late_deposit(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="closed", fail_reason="not_created")
    assert await _apply(db_session, sale, deposit("hold")) == "attention"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("closed", "late_deposit")


async def test_a_move_nudges_the_seller_on_commit(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="offered")
    async with listen_channel(CHANNEL) as events:
        assert await _apply(db_session, sale, deposit("hold")) == "hold"
        assert await events.drain() == [f"{sale.user_id}:{sale.number}:sale"]


async def test_check_sale_asks_the_status_and_applies_it(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="offered")
    client = FakeDepositClient(status=deposit("hold"))
    assert await check_sale(db_session, client, sale_id=sale.id) == "hold"
    assert client.status_calls == [sale.id]
    assert (await _fresh(db_session, sale)).last_polled_at is not None


async def test_check_sale_on_an_outage_changes_nothing(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="offered")
    client = FakeDepositClient(status=SkinslinkUnavailableError("down"))
    assert await check_sale(db_session, client, sale_id=sale.id) == "unchanged"
    assert (await _fresh(db_session, sale)).status == "offered"
```

Append to `apps/api/tests/unit/test_realtime_registry.py`:

```python
async def test_a_sale_nudge_says_sale_updated() -> None:
    reg = Registry()
    socket = _Socket()
    reg.add("a", socket)
    assert await reg.publish("a", "S0000001", kind="sale") == 1
    assert socket.sent == ['{"type":"sale.updated","number":"S0000001"}']
```

```python
# apps/api/tests/unit/test_realtime_listener_kinds.py
"""The listener tells an order's nudge from a sale's by the payload's third part."""

from __future__ import annotations

import asyncio

from csmarket.modules.realtime.listener import OrderEventsListener


class _Target:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def publish(self, user_id: str, number: str, *, kind: str = "order") -> int:
        self.calls.append((user_id, number, kind))
        return 1


async def test_a_sale_payload_publishes_a_sale_update() -> None:
    target = _Target()
    listener = OrderEventsListener("postgresql+asyncpg://u@h/db", target=target)  # type: ignore[arg-type]
    listener._on_notify(None, 0, "order_events", "u1:S0000001:sale")
    listener._on_notify(None, 0, "order_events", "u1:A0000001")
    listener._on_notify(None, 0, "order_events", "garbage")
    await asyncio.sleep(0)
    assert target.calls == [("u1", "S0000001", "sale"), ("u1", "A0000001", "order")]
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_wallet_sales.py tests/integration/test_sales_status.py tests/unit/test_realtime_registry.py tests/unit/test_realtime_listener_kinds.py -q`
Expected: FAIL — `ImportError: cannot import name 'credit_sale' from 'csmarket.modules.wallet.api'`.

- [ ] **Step 3: The ledger side**

`wallet/service.py`:

```python
    # Credit partner of ``user_wallet`` when a user's sale is paid to their balance
    # (spec 2026-10-08): grows with what we paid for skins, so its normal side is C.
    "house_skin_buys": "C",
```

(the last entry of `NORMAL_SIDE`), and

```python
#: Transaction kinds (spec §5): ``purchase`` and ``refund`` book an order (M4a);
#: ``sale_credit`` and ``payout_return`` a sale (2026-10-08).
TX_KINDS: tuple[str, ...] = (
    "topup",
    "topup_reversal",
    "admin_adjust",
    "purchase",
    "refund",
    "sale_credit",
    "payout_return",
)
```

```python
# apps/api/src/csmarket/modules/wallet/sales.py
"""A sale on the ledger: the user's money for skins they sold us (spec 2026-10-08 §4).

- :func:`credit_sale` — D ``user_wallet`` / C ``house_skin_buys``, key ``sale:{sale_id}``: at
  most once per sale, whatever the webhooks, polls and races.
- :func:`credit_payout_return` — a card payout an admin rejected comes to the balance
  instead: the same legs, key ``payout_return:{request_id}``.

The spec writes the credit «debit house_skin_buys / credit user_wallet» from the house's
side; on this ledger a user's money is a debit balance (``NORMAL_SIDE["user_wallet"] == "D"``,
as a top-up books it), so the legs are mirrored and ``house_skin_buys`` is credit-normal. A
credit needs no lock on the wallet. Both flush, never commit.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.wallet.models import WalletAccount, WalletTransaction
from csmarket.modules.wallet.service import Leg, Reference, ensure_account, post, user_account


async def _house_skin_buys(db: AsyncSession) -> WalletAccount:
    """The house account that pays for skins users sell us."""
    return await ensure_account(db, owner_type="house", owner_id="house", kind="house_skin_buys")


async def _credit(
    db: AsyncSession,
    *,
    kind: str,
    key: str,
    user_id: str,
    sale_id: str,
    amount: Decimal,
    actor: str,
) -> WalletTransaction:
    wallet = await user_account(db, user_id)
    house = await _house_skin_buys(db)
    return await post(
        db,
        kind=kind,
        legs=[Leg(wallet.id, "D", amount), Leg(house.id, "C", amount)],
        idempotency_key=key,
        reference=Reference(type="sale", id=sale_id),
        actor=actor,
    )


async def credit_sale(
    db: AsyncSession, *, user_id: str, sale_id: str, amount: Decimal
) -> WalletTransaction:
    """Pay sale ``sale_id`` to the user's balance, once (a replay returns the first)."""
    return await _credit(
        db,
        kind="sale_credit",
        key=f"sale:{sale_id}",
        user_id=user_id,
        sale_id=sale_id,
        amount=amount,
        actor="sales",
    )


async def credit_payout_return(
    db: AsyncSession,
    *,
    user_id: str,
    sale_id: str,
    request_id: str,
    amount: Decimal,
    actor: str,
) -> WalletTransaction:
    """Credit a rejected card payout to the balance, once per request."""
    return await _credit(
        db,
        kind="payout_return",
        key=f"payout_return:{request_id}",
        user_id=user_id,
        sale_id=sale_id,
        amount=amount,
        actor=actor,
    )


__all__ = ["credit_payout_return", "credit_sale"]
```

`wallet/api.py`: `from csmarket.modules.wallet.sales import credit_payout_return, credit_sale` and both names in `__all__`.

- [ ] **Step 4: The sale nudge**

`realtime/api.py`, after `nudge`:

```python
async def nudge_sale(db: AsyncSession, *, user_id: str, number: str) -> None:
    """Like :func:`nudge`, for a sale: the owner's sockets get ``sale.updated``. Never commits."""
    await db.execute(select(func.pg_notify(CHANNEL, f"{user_id}:{number}:sale")))
```

and `__all__ = ["CHANNEL", "nudge", "nudge_sale"]`.

`realtime/listener.py`, `_on_notify`:

```python
    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        """asyncpg's callback: ``user_id:number`` (an order) or ``user_id:number:sale``."""
        user_id, sep, rest = payload.partition(":")
        number, _, kind = rest.partition(":")
        if not sep or not user_id or not number:
            return
        send = asyncio.create_task(
            self._target.publish(user_id, number, kind="sale" if kind == "sale" else "order")
        )
        self._sends.add(send)
        send.add_done_callback(self._sends.discard)
```

`realtime/registry.py`: `from typing import Literal, Protocol`, and

```python
    async def publish(
        self, user_id: str, number: str, *, kind: Literal["order", "sale"] = "order"
    ) -> int:
        """Send ``{"type": "order.changed" | "sale.updated", "number": …}`` to every socket of
        ``user_id``.

        Returns:
            How many sockets it reached.
        """
        kind_type = "sale.updated" if kind == "sale" else "order.changed"
        frame = json.dumps({"type": kind_type, "number": number}, separators=(",", ":"))
```

(the rest of the body unchanged). Add "and `{"type": "sale.updated", "number": …}`" to the protocol paragraph of `realtime/routes.py`'s docstring.

- [ ] **Step 5: The outcome counter**

`core/metrics.py`, beside the Skinslink counter:

```python
#: Where the status machine moved a sale (``sales.status.apply_deposit``; spec 2026-10-08).
_SALE_OUTCOMES = frozenset(
    ("offered", "hold", "credited", "payout", "closed", "reverted", "attention")
)
SALE_OUTCOMES = Counter(
    "csmarket_sale_outcomes_total",
    "Sales moved by the status machine, by where they went (spec 2026-10-08).",
    ("outcome",),
)
```

after the other `_precreate` calls: `_precreate(SALE_OUTCOMES, outcome=_SALE_OUTCOMES)`; and beside `record_skinslink_call`:

```python
def record_sale_outcome(outcome: str) -> None:
    """Count one move of a sale; a value outside the set becomes ``"other"``. Never raises."""
    _inc(
        SALE_OUTCOMES,
        "csmarket_sale_outcomes_total",
        {"outcome": outcome if outcome in _SALE_OUTCOMES else "other"},
    )
```

- [ ] **Step 6: Payout requests and the status machine**

```python
# apps/api/src/csmarket/modules/sales/payouts.py
"""A card sale's payout request (spec 2026-10-08 §4, §6): opened at ``hold``, payable at
``completed``, canceled when the sale fails or is reverted before it was paid.

Read under the sale's lock and then its own (the order :mod:`.status` and the admin's
actions both take: sale, then request). Flush, never commit.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.sales.models import PayoutRequest, Sale

#: A request still waiting for its money; a failed or reverted sale cancels it.
_OPEN = frozenset({"waiting_hold", "to_pay"})


async def request_of(db: AsyncSession, sale_id: str, *, lock: bool = False) -> PayoutRequest | None:
    """The sale's request, read fresh (``FOR UPDATE`` with ``lock``)."""
    stmt = select(PayoutRequest).where(PayoutRequest.sale_id == sale_id)
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt.execution_options(populate_existing=True))


async def open_request(
    db: AsyncSession, sale: Sale, *, status: Literal["waiting_hold", "to_pay"]
) -> PayoutRequest:
    """The card sale's request, created in ``status`` if it has none yet.

    Raises:
        ValueError: ``sale`` pays to the balance — a caller bug.
    """
    existing = await request_of(db, sale.id, lock=True)
    if existing is not None:
        return existing
    if sale.payout_card_id is None:
        raise ValueError("a balance sale has no payout request")
    request = PayoutRequest(
        id=new_id(),
        sale_id=sale.id,
        user_id=sale.user_id,
        card_id=sale.payout_card_id,
        amount_uzs=sale.payout_uzs,
        fee_uzs=sale.items_uzs - sale.payout_uzs,
        status=status,
        to_pay_at=now() if status == "to_pay" else None,
    )
    db.add(request)
    await db.flush()
    return request


async def cancel_request(db: AsyncSession, sale: Sale) -> None:
    """Cancel the sale's request if it still waits for money; a paid one is left alone."""
    request = await request_of(db, sale.id, lock=True)
    if request is not None and request.status in _OPEN:
        request.status = "canceled"
        await db.flush()


__all__ = ["cancel_request", "open_request", "request_of"]
```

```python
# apps/api/src/csmarket/modules/sales/status.py
"""A deposit's status, applied to its sale (spec 2026-10-08 §6).

:func:`apply_deposit` is the one place a sale moves. It runs under the sale's row lock
(:func:`lock_sale`), flushes and never commits. :func:`check_sale` reads the sale, ends the
transaction, asks Skinslink ``deposit/status`` and applies the answer under the lock — the
worker (a webhook's check), the poll and ``POST /sell`` all go through it or through
:func:`apply_deposit`, so a webhook body is never trusted and no call holds a lock.

- open (``creating`` / ``offered`` / ``hold``) + ``new`` / ``pending`` / ``active`` →
  ``offered`` (never back from ``hold``);
- + ``hold`` → ``hold``, ``hold_end_at`` kept; a card sale's request opens ``waiting_hold``;
- + ``completed`` → ``credited`` (balance: the ledger credit, keyed by the sale, so at most
  once) or ``payout`` (card: the request becomes ``to_pay``);
- + ``failed`` / ``canceled`` → ``closed``; + ``reverted`` → ``reverted``; an open request is
  canceled — nothing was paid;
- ``creating`` that Skinslink does not know after :data:`NOT_FOUND_GRACE` → ``closed``
  (``not_created``: the call never landed);
- settled: ``reverted`` after the money left → ``attention_reason = rolled_back``, no debit
  (a ``payout`` whose request is still ``to_pay`` is reverted instead: nothing was paid); a
  ``closed`` sale Skinslink reports alive → ``late_deposit``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_sale_outcome
from csmarket.modules.realtime.api import nudge_sale
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.sales.models import OPEN_STATUSES, Sale
from csmarket.modules.sales.payouts import cancel_request, open_request, request_of
from csmarket.modules.skinslink.api import (
    Deposit,
    DepositClient,
    SkinslinkError,
    SkinslinkUnavailableError,
)
from csmarket.modules.wallet.api import credit_sale

log = get_logger("csmarket.sales.status")

Outcome = Literal[
    "unchanged", "offered", "hold", "credited", "payout", "closed", "reverted", "attention"
]
#: How long a ``creating`` sale Skinslink does not know stays open (the call may be in flight).
NOT_FOUND_GRACE = timedelta(minutes=2)
_LIVE = frozenset({"new", "pending", "active"})
_DEAD = frozenset({"failed", "canceled"})
_USD = Decimal("0.000001")


async def lock_sale(db: AsyncSession, sale_id: str) -> Sale | None:
    """Sale ``sale_id`` ``FOR UPDATE``, read fresh."""
    return await db.scalar(
        select(Sale)
        .where(Sale.id == sale_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _parse_at(value: str | None) -> datetime | None:
    """An ISO 8601 time from Skinslink, as an aware UTC datetime; ``None`` if unreadable."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _record(sale: Sale, report: Deposit) -> None:
    """Keep what Skinslink says about the offer; a missing field never erases a known one."""
    sale.trade_id = report.id
    if report.trade_offer_id:
        sale.trade_offer_id = report.trade_offer_id[:32]
    if report.bot_name:
        sale.bot_name = report.bot_name[:64]
    sale.offer_expiry_at = _parse_at(report.offer_expiry_at) or sale.offer_expiry_at
    sale.hold_end_at = _parse_at(report.hold_end_date) or sale.hold_end_at
    if report.amount_usd is not None:
        sale.amount_usd = report.amount_usd.quantize(_USD)


async def apply_deposit(
    db: AsyncSession, sale: Sale, report: Deposit | None, *, at: datetime
) -> Outcome:
    """Move ``sale`` by Skinslink's ``report`` (``None``: Skinslink has no such deposit).

    The caller holds ``sale`` ``FOR UPDATE`` and commits. A move enqueues its letter, counts
    the outcome and nudges the seller's socket in the same transaction.
    """
    if report is None:
        outcome = await _missing(db, sale, at)
    else:
        _record(sale, report)
        if sale.status in OPEN_STATUSES:
            outcome = await _open(db, sale, report)
        else:
            outcome = await _settled(db, sale, report.status)
    if outcome != "unchanged":
        record_sale_outcome(outcome)
        await nudge_sale(db, user_id=sale.user_id, number=sale.number)
        log.info("sales.moved", number=sale.number, outcome=outcome)
    await db.flush()
    return outcome


async def _missing(db: AsyncSession, sale: Sale, at: datetime) -> Outcome:
    if sale.status == "creating" and at - sale.created_at >= NOT_FOUND_GRACE:
        return await _close(db, sale, "not_created", letter=False)
    return "unchanged"


async def _open(db: AsyncSession, sale: Sale, report: Deposit) -> Outcome:
    status = report.status
    if status in _LIVE:
        return _offered(sale)
    if status == "hold":
        return await _hold(db, sale)
    if status == "completed":
        return await _complete(db, sale)
    if status in _DEAD:
        reason = report.fail_reason or status
        return await _close(db, sale, reason, letter=sale.status != "creating")
    if status == "reverted":
        return await _revert(db, sale, report.fail_reason or status)
    return "unchanged"


def _offered(sale: Sale) -> Outcome:
    if sale.status != "creating":  # ``offered`` stays; ``hold`` never steps back
        return "unchanged"
    sale.status = "offered"
    return "offered"


async def _hold(db: AsyncSession, sale: Sale) -> Outcome:
    if sale.status == "hold":
        return "unchanged"
    sale.status = "hold"
    if sale.payout_to == "card":
        await open_request(db, sale, status="waiting_hold")
    await enqueue_sale_letter(db, sale, "sale_hold")
    return "hold"


async def _complete(db: AsyncSession, sale: Sale) -> Outcome:
    at = now()
    if sale.payout_to == "balance":
        await credit_sale(db, user_id=sale.user_id, sale_id=sale.id, amount=sale.payout_uzs)
        sale.status, sale.credited_at = "credited", at
        await enqueue_sale_letter(db, sale, "sale_paid", to="balance")
        return "credited"
    request = await open_request(db, sale, status="to_pay")
    if request.status == "waiting_hold":
        request.status = "to_pay"
    request.to_pay_at = request.to_pay_at or at
    sale.status = "payout"
    return "payout"


async def _close(db: AsyncSession, sale: Sale, reason: str, *, letter: bool) -> Outcome:
    sale.status, sale.fail_reason = "closed", reason[:48]
    await cancel_request(db, sale)
    if letter:
        await enqueue_sale_letter(db, sale, "sale_canceled")
    return "closed"


async def _revert(db: AsyncSession, sale: Sale, reason: str) -> Outcome:
    sale.status, sale.fail_reason = "reverted", reason[:48]
    await cancel_request(db, sale)
    await enqueue_sale_letter(db, sale, "sale_canceled")
    return "reverted"


async def _settled(db: AsyncSession, sale: Sale, status: str) -> Outcome:
    if status == "reverted":
        return await _revert_settled(db, sale)
    if sale.status == "closed" and status not in _DEAD:
        return _attention(sale, "late_deposit")
    return "unchanged"


async def _revert_settled(db: AsyncSession, sale: Sale) -> Outcome:
    if sale.status == "reverted":
        return "unchanged"
    if sale.status == "payout":
        request = await request_of(db, sale.id, lock=True)
        if request is not None and request.status == "to_pay":  # nothing was paid yet
            return await _revert(db, sale, "reverted")
    return _attention(sale, "rolled_back")


def _attention(sale: Sale, reason: str) -> Outcome:
    if sale.attention_reason is not None:
        return "unchanged"
    sale.attention_reason = reason
    log.warning("sales.attention", number=sale.number, reason=reason)
    return "attention"


async def check_sale(db: AsyncSession, client: DepositClient, *, sale_id: str) -> Outcome:
    """Ask Skinslink about ``sale_id`` and apply the answer; commits.

    The read transaction ends before the call; the answer is applied under the sale's lock.
    An outage or a refusal changes nothing (the next poll asks again).
    """
    sale = await db.get(Sale, sale_id, populate_existing=True)
    number = sale.number if sale is not None else None
    await db.commit()
    if number is None:
        return "unchanged"
    try:
        report = await client.deposit_status(merchant_tx_id=sale_id)
    except (SkinslinkError, SkinslinkUnavailableError) as exc:
        log.warning("sales.status_unread", number=number, error=type(exc).__name__)
        return "unchanged"
    locked = await lock_sale(db, sale_id)
    if locked is None:
        await db.rollback()
        return "unchanged"
    outcome = await apply_deposit(db, locked, report, at=now())
    locked.last_polled_at = now()
    await db.commit()
    return outcome


__all__ = ["NOT_FOUND_GRACE", "Outcome", "apply_deposit", "check_sale", "lock_sale"]
```

`sales/api.py`: add `from csmarket.modules.sales.status import Outcome, apply_deposit, check_sale, lock_sale` and the four names to `__all__`.

- [ ] **Step 7: Run the tests and the linters**

Run: `cd apps/api && uv run pytest tests/integration/test_wallet_sales.py tests/integration/test_sales_status.py tests/unit/test_realtime_registry.py tests/unit/test_realtime_listener_kinds.py tests/integration/test_realtime_nudges.py tests/integration/test_orders_refunds.py -q && uv run ruff check src/csmarket/modules/sales src/csmarket/modules/wallet src/csmarket/modules/realtime src/csmarket/core/metrics.py tests/integration/fake_deposit_client.py tests/integration/test_sales_status.py tests/integration/test_wallet_sales.py tests/unit/test_realtime_listener_kinds.py && uv run mypy src/csmarket/modules/sales src/csmarket/modules/wallet src/csmarket/modules/realtime src/csmarket/core/metrics.py`
Expected: PASS (order nudges and refunds unchanged); clean.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/modules/wallet apps/api/src/csmarket/modules/realtime apps/api/src/csmarket/core/metrics.py apps/api/tests/integration/fake_deposit_client.py apps/api/tests/integration/test_wallet_sales.py apps/api/tests/integration/test_sales_status.py apps/api/tests/unit/test_realtime_registry.py apps/api/tests/unit/test_realtime_listener_kinds.py
git commit -m "feat(api/sales): the status machine — one credit per sale, payout requests, reversals to an admin" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `GET /sell/config` and `GET /sell/inventory` — the gate, the cached snapshot, the breaker

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/gate.py`, `apps/api/src/csmarket/modules/sales/clients.py`, `apps/api/src/csmarket/modules/sales/inventory.py`, `apps/api/src/csmarket/modules/sales/routes.py`
- Modify: `apps/api/src/csmarket/modules/sales/schemas.py` (`SellConfigOut`, `SellItemOut`, `InventoryOut`)
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `sales.routes.router`)
- Create: `apps/api/tests/integration/sales_kit.py`
- Test: `apps/api/tests/integration/test_sales_inventory.py`

**Interfaces:**

- Consumes: `DepositClient`, `Inventory`, `InventoryItem`, `SkinslinkError`, `SkinslinkForbiddenError`, `SkinslinkUnavailableError`, `STEAM_ACCOUNT_CODES`, `deposit_client_for` (Task 2); `SaleSettings`, `read_sale_settings`, `quote_item`, `sale_rate`, `min_sum_uzs` (Task 4); `fx.api.current_usd_uzs`; `users.api.TradeLink`, `parse_tradelink`; `skins.api.SkinItem`; `core.logging.hash_short`.
- Produces in `gate.py`: `RateUnavailableError` (503 `rate_unavailable`), `open_settings(db, settings: Settings) -> SaleSettings` (409 `sales_disabled`), `trade_link_of(user: User) -> TradeLink` (409 `trade_link_missing` / `trade_link_bad` + `reason`), `sale_rate_now(db, redis, settings: Settings, doc: SaleSettings) -> Decimal`.
- Produces in `clients.py`: `inventory_client() -> DepositClient`, `deposit_client() -> DepositClient` (FastAPI dependencies; tests override them).
- Produces in `inventory.py`: `CACHE_TTL = 300`, `BREAKER_KEY = "sales:inventory:breaker"`, `BREAKER_TTL = 120`, `SalesUnavailableError` (503 `sales_unavailable`), `unavailable() -> SalesUnavailableError`, `@dataclass(frozen=True) Snapshot(items: tuple[InventoryItem, ...], max_items: int, fetched_at: datetime)`, `cache_key(user_id: str, trade_link: str) -> str`, `cached_snapshot(redis, user_id: str, trade_link: str) -> Snapshot | None`, `forget_snapshot(redis, user_id: str, trade_link: str) -> None`, `fetch_snapshot(redis, client, *, user_id: str, link: TradeLink, refresh: bool) -> Snapshot` (409 `steam_refused` + `reason`), `priced_inventory(db, *, redis, user: User, client: DepositClient, settings: Settings, refresh: bool) -> InventoryOut`.
- Produces routes: `GET /api/v1/sell/config` (public) → `SellConfigOut(enabled, balance_bonus_pct, card_fee_pct: dict[CardType, str], card_min_uzs, min_sum_uzs: str | None, max_cards)`; `GET /api/v1/sell/inventory?refresh=1` (signed in; bucket `sell-inventory`) → `InventoryOut(items: list[SellItemOut(asset_id, name, image_url, exterior, rarity_color, category, price_uzs)], max_items, min_sum_uzs, fetched_at)`.
- Produces in tests: `sales_kit.sales_on` (fixture: env on with key + secret), `sales_kit.SECRET`, `ready_seller(db, customer_headers) -> dict[str, str]` (a signed-in customer with the fake trade link, sales switched on, a rate), `add_rate(db) -> None`, `use_client(app, client) -> None` (overrides both client dependencies).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/sales_kit.py
"""Shared set-up for the sales route tests: switches on, a seller with a link, a rate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.sales.clients import deposit_client, inventory_client
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.fake_deposit_client import FakeDepositClient
from tests.integration.orders_factory import saved_trade_link
from tests.integration.sales_factory import RATE, enable_sales

SECRET = "test-secret-not-real"
Headers = Callable[[], Awaitable[dict[str, str]]]


@pytest.fixture
def sales_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``CSMARKET_SALES_ENABLED`` with both Skinslink credentials."""
    for name, value in {
        "SALES_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": SECRET,
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def add_rate(db: AsyncSession) -> None:
    """A fresh CBU snapshot at :data:`RATE`."""
    db.add(FxSnapshot(id=new_id(), usd_uzs=RATE, source="cbu"))
    await db.commit()


async def ready_seller(db: AsyncSession, customer_headers: Headers) -> dict[str, str]:
    """The customer signed in with the fake trade link; selling on; a rate. Their headers."""
    headers = await customer_headers()
    await saved_trade_link(db, CUSTOMER_STEAM_ID)
    await enable_sales(db)
    await add_rate(db)
    return headers


def use_client(app: FastAPI, client: FakeDepositClient) -> None:
    """Route both deposit-client dependencies to ``client``."""
    app.dependency_overrides[inventory_client] = lambda: client
    app.dependency_overrides[deposit_client] = lambda: client
```

```python
# apps/api/tests/integration/test_sales_inventory.py
"""``GET /sell/config`` and ``GET /sell/inventory``: the switches, soʻm prices, the cache."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.api import Inventory, SkinslinkError, SkinslinkUnavailableError
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_deposit_client import FakeDepositClient, inv_item
from tests.integration.sales_factory import enable_sales
from tests.integration.sales_kit import (  # noqa: F401 -- the fixture
    Headers,
    add_rate,
    ready_seller,
    sales_on,
    use_client,
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/sell/inventory"
INVENTORY = Inventory(
    items=[
        inv_item("101", "0.5", "P250 | Sand Dune (Field-Tested)"),
        inv_item("100", "12.45"),
        inv_item("102", "0.005", "Sticker | Tiny"),
    ],
    max_items=50,
)


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(inventory=[INVENTORY])
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def test_config_is_public_and_says_off_by_default(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/sell/config")
    assert r.status_code == 200
    assert r.json() == {
        "enabled": False,
        "balance_bonus_pct": "2",
        "card_fee_pct": {"uzcard": "5", "humo": "5", "uzum_visa": "5"},
        "card_min_uzs": "30000",
        "min_sum_uzs": None,
        "max_cards": 3,
    }


async def test_config_when_on_gives_the_minimum_in_soum(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None
) -> None:
    await enable_sales(db_session)
    await add_rate(db_session)
    body = (await integration_client.get("/api/v1/sell/config")).json()
    assert (body["enabled"], body["min_sum_uzs"]) == (True, "11300")


async def test_the_inventory_is_priced_in_soum_from_the_cbu_rate(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    db_session.add(
        SkinItem(
            id=new_id(),
            market_hash_name="AK-47 | Redline (Field-Tested)",
            phase="",
            slug="ak-47-redline-field-tested",
            category="rifles",
            search_text="ak 47 redline field tested",
        )
    )
    await db_session.commit()
    r = await integration_client.get(URL, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(i["asset_id"], i["price_uzs"], i["category"]) for i in body["items"]] == [
        ("100", "149600", "rifles"),
        ("101", "5600", None),
    ]  # dearest first; the 0.005 $ item prices to 0 soʻm and is left out
    assert (body["max_items"], body["min_sum_uzs"]) == (50, "11300")
    assert "12.45" not in r.text  # Skinslink's own prices never reach the browser


async def test_the_snapshot_is_kept_and_refresh_asks_again(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    for _ in range(2):
        assert (await integration_client.get(URL, headers=headers)).status_code == 200
    assert fake.inventory_calls == 1
    assert (await integration_client.get(f"{URL}?refresh=1", headers=headers)).status_code == 200
    assert fake.inventory_calls == 2


async def test_selling_off_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)  # the env switch stays off
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, "sales_disabled")
    assert fake.inventory_calls == 0


async def test_the_admins_switch_off_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    await enable_sales(db_session, enabled=False)
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, "sales_disabled")


async def test_without_a_trade_link_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await customer_headers()
    await enable_sales(db_session)
    await add_rate(db_session)
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, "trade_link_missing")


async def test_a_steam_refusal_is_409_with_its_reason(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    fake.inventories.clear()
    fake.inventories.append(SkinslinkError("refused", status=400, code="trade_banned"))
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"], r.json()["reason"]) == (
        409,
        "steam_refused",
        "trade_banned",
    )


async def test_an_outage_opens_the_breaker(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    fake.inventories.clear()
    fake.inventories.append(SkinslinkUnavailableError("down"))
    for _ in range(2):
        r = await integration_client.get(f"{URL}?refresh=1", headers=headers)
        assert (r.status_code, r.json()["code"]) == (503, "sales_unavailable")
    assert fake.inventory_calls == 1  # the second read never reached Skinslink


async def test_a_stale_snapshot_is_asked_once_more(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    fake.inventories.clear()
    fake.inventories.extend(
        [SkinslinkError("refused", status=400, code="inventory_reload"), INVENTORY]
    )
    assert (await integration_client.get(URL, headers=headers)).status_code == 200
    assert fake.inventory_calls == 2


async def test_signed_out_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(URL)).status_code == 401
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_inventory.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.sales.clients`.

- [ ] **Step 3: `gate.py` and `clients.py`**

```python
# apps/api/src/csmarket/modules/sales/gate.py
"""What every sell request checks first: the two switches, the trade link, the rate.

Both switches must be on — ``CSMARKET_SALES_ENABLED`` (with the Skinslink credentials,
``Settings.sales_active``) and the admin's «Выкуп включён» — else 409 ``sales_disabled``. The
trade link must be saved and not found bad (the check is advisory, as on the buy side). The
rate is the raw CBU rate (no uplift) less ``rate_cut_pct``.
"""

from __future__ import annotations

from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError, UpstreamUnavailableError, ValidationError
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.pricing import sale_rate
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.settings_store import read_sale_settings
from csmarket.modules.users.api import TradeLink, User, parse_tradelink

#: Stored verdicts that refuse a link (as on the buy side: ``warn`` is a legacy trade hold).
_BAD_VERDICTS = frozenset({"bad", "warn"})


class RateUnavailableError(UpstreamUnavailableError):
    """No fresh CBU rate: nothing can be priced in soʻm."""

    status_code = 503
    type_uri = "https://csmarket.uz/errors/rate-unavailable"
    title = "Rate unavailable"


async def open_settings(db: AsyncSession, settings: Settings) -> SaleSettings:
    """The sale settings, if selling is on.

    Raises:
        ConflictError: ``sales_disabled`` — an env switch, a credential or the admin's switch
            is off.
    """
    doc = await read_sale_settings(db)
    if not settings.sales_active or not doc.enabled:
        raise ConflictError("selling is switched off", code="sales_disabled")
    return doc


def trade_link_of(user: User) -> TradeLink:
    """The seller's saved trade link, parsed.

    Raises:
        ConflictError: ``trade_link_missing``; ``trade_link_bad`` with ``reason``.
    """
    if not user.trade_link:
        raise ConflictError("add your Steam trade link first", code="trade_link_missing")
    if user.trade_link_verdict in _BAD_VERDICTS:
        reason = user.trade_link_reason or ("hold" if user.trade_link_verdict == "warn" else None)
        raise ConflictError(
            "this trade link cannot trade", code="trade_link_bad", reason=reason or "invalid"
        )
    try:
        return parse_tradelink(user.trade_link)
    except ValidationError as exc:
        raise ConflictError(
            "this trade link cannot trade", code="trade_link_bad", reason="invalid"
        ) from exc


async def sale_rate_now(
    db: AsyncSession, redis: Redis, settings: Settings, doc: SaleSettings
) -> Decimal:
    """The CBU rate (no uplift) less ``rate_cut_pct``.

    Raises:
        RateUnavailableError: No snapshot younger than ``fx_max_age_days``.
    """
    fx = await current_usd_uzs(
        db, redis, max_age_days=settings.fx_max_age_days, uplift_pct=Decimal(0)
    )
    if fx is None:
        raise RateUnavailableError("no soʻm rate", code="rate_unavailable")
    return sale_rate(fx.rate, doc)


__all__ = ["RateUnavailableError", "open_settings", "sale_rate_now", "trade_link_of"]
```

```python
# apps/api/src/csmarket/modules/sales/clients.py
"""The Skinslink deposit client, as FastAPI dependencies — one per route's timeout.

``GET /sell/inventory`` waits :attr:`Settings.sales_inventory_timeout_seconds` (6 s),
``POST /sell`` :attr:`Settings.sales_deposit_timeout_seconds` (10 s): ADR-0016. Tests
override both with a fake.
"""

from __future__ import annotations

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.api import DepositClient, deposit_client_for


def inventory_client() -> DepositClient:
    """The client ``GET /sell/inventory`` reads the inventory with."""
    settings = get_settings()
    return deposit_client_for(settings, timeout_seconds=settings.sales_inventory_timeout_seconds)


def deposit_client() -> DepositClient:
    """The client ``POST /sell`` creates the deposit with."""
    settings = get_settings()
    return deposit_client_for(settings, timeout_seconds=settings.sales_deposit_timeout_seconds)


__all__ = ["deposit_client", "inventory_client"]
```

- [ ] **Step 4: `inventory.py`**

```python
# apps/api/src/csmarket/modules/sales/inventory.py
"""The seller's priced inventory (spec 2026-10-08 §5): ``GET /sell/inventory``.

Skinslink's ``inventory`` lists only the items it accepts that are tradable now, priced in
USD; ``create-deposit`` prices from that snapshot for 5 minutes. We keep it in Redis for the
same :data:`CACHE_TTL` per user and trade link (:func:`cache_key`): ``POST /sell`` re-prices
from this copy, never from the browser. Soʻm prices are computed on every read (the settings
and the rate may move); an item that prices to 0 soʻm is left out.

The call is the ADR-0016 carve-out (AGENTS §11): advisory, a 6 s timeout, no database
connection held across it, a :data:`BREAKER_TTL` breaker after an outage or a 403, and the
route's own ``ip_guard`` bucket. ``inventory_reload`` is asked once more; a Steam account
refusal is 409 ``steam_refused`` with Skinslink's code as ``reason``.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError, UpstreamUnavailableError
from csmarket.core.logging import get_logger, hash_short
from csmarket.core.money import wire_uzs
from csmarket.modules.sales.gate import open_settings, sale_rate_now, trade_link_of
from csmarket.modules.sales.pricing import min_sum_uzs, quote_item
from csmarket.modules.sales.schemas import InventoryOut, SellItemOut
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.skinslink.api import (
    STEAM_ACCOUNT_CODES,
    DepositClient,
    Inventory,
    InventoryItem,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import TradeLink, User

log = get_logger("csmarket.sales.inventory")

CACHE_TTL = 300
BREAKER_KEY = "sales:inventory:breaker"
BREAKER_TTL = 120


class SalesUnavailableError(UpstreamUnavailableError):
    """Skinslink could not be asked (an outage, a 403, the breaker open)."""

    status_code = 503
    type_uri = "https://csmarket.uz/errors/sales-unavailable"
    title = "Selling unavailable"


def unavailable() -> SalesUnavailableError:
    """The one 503 every sell route answers when Skinslink cannot be asked."""
    return SalesUnavailableError("selling is unavailable right now", code="sales_unavailable")


@dataclass(frozen=True)
class Snapshot:
    """A priced inventory as Skinslink gave it, and when."""

    items: tuple[InventoryItem, ...]
    max_items: int
    fetched_at: datetime


def cache_key(user_id: str, trade_link: str) -> str:
    """``sales:inventory:{user_id}:{hash of the link}`` — a new link is a new inventory."""
    return f"sales:inventory:{user_id}:{hash_short(trade_link)}"


def _dump(snap: Snapshot) -> str:
    return json.dumps(
        {
            "max_items": snap.max_items,
            "fetched_at": snap.fetched_at.isoformat(),
            "items": [
                {
                    "id": i.id,
                    "name": i.name,
                    "price": str(i.price_usd),
                    "image_url": i.image_url,
                    "exterior": i.exterior,
                    "rarity": i.rarity,
                    "rarity_color": i.rarity_color,
                }
                for i in snap.items
            ],
        }
    )


def _load(raw: str | bytes) -> Snapshot | None:
    try:
        data = json.loads(raw)
        items = tuple(
            InventoryItem(
                id=str(x["id"]),
                name=str(x["name"]),
                price_usd=Decimal(x["price"]),
                image_url=x.get("image_url"),
                exterior=x.get("exterior"),
                rarity=x.get("rarity"),
                rarity_color=x.get("rarity_color"),
            )
            for x in data["items"]
        )
        return Snapshot(
            items=items,
            max_items=int(data["max_items"]),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
        )
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return None


async def cached_snapshot(redis: Redis, user_id: str, trade_link: str) -> Snapshot | None:
    """The kept snapshot, or ``None`` (none, expired, unreadable, or Redis down)."""
    with contextlib.suppress(RedisError):
        raw = await redis.get(cache_key(user_id, trade_link))
        return _load(raw) if raw is not None else None
    return None


async def forget_snapshot(redis: Redis, user_id: str, trade_link: str) -> None:
    """Drop the kept snapshot: the next read asks Skinslink."""
    with contextlib.suppress(RedisError):
        await redis.delete(cache_key(user_id, trade_link))


async def _keep(redis: Redis, user_id: str, trade_link: str, snap: Snapshot) -> None:
    with contextlib.suppress(RedisError):
        await redis.set(cache_key(user_id, trade_link), _dump(snap), ex=CACHE_TTL)


async def _breaker_open(redis: Redis) -> bool:
    with contextlib.suppress(RedisError):
        return bool(await redis.exists(BREAKER_KEY))
    return False


async def _open_breaker(redis: Redis, error: Exception) -> None:
    log.warning("sales.inventory.breaker_open", error=type(error).__name__)
    with contextlib.suppress(RedisError):
        await redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL)


async def _ask(client: DepositClient, link: TradeLink) -> Inventory:
    """Skinslink's inventory; a stale snapshot (``inventory_reload``) is asked once more."""
    try:
        return await client.inventory(partner=link.partner, token=link.token)
    except SkinslinkError as exc:
        if exc.code != "inventory_reload":
            raise
    return await client.inventory(partner=link.partner, token=link.token)


async def fetch_snapshot(
    redis: Redis, client: DepositClient, *, user_id: str, link: TradeLink, refresh: bool
) -> Snapshot:
    """The kept snapshot, or a fresh one from Skinslink (kept for :data:`CACHE_TTL`).

    Raises:
        ConflictError: ``steam_refused`` with ``reason`` — the Steam account cannot trade.
        SalesUnavailableError: ``sales_unavailable`` — an outage, a 403, a refusal, the breaker.
    """
    if not refresh and (kept := await cached_snapshot(redis, user_id, link.url)) is not None:
        return kept
    if await _breaker_open(redis):
        raise unavailable()
    try:
        inventory = await _ask(client, link)
    except SkinslinkForbiddenError as exc:
        await _open_breaker(redis, exc)
        raise unavailable() from None
    except SkinslinkError as exc:
        if exc.code in STEAM_ACCOUNT_CODES:
            raise ConflictError(
                "Steam does not let this account trade", code="steam_refused", reason=exc.code
            ) from None
        log.warning("sales.inventory.refused", code=exc.code)
        raise unavailable() from None
    except SkinslinkUnavailableError as exc:
        await _open_breaker(redis, exc)
        raise unavailable() from None
    snap = Snapshot(items=tuple(inventory.items), max_items=inventory.max_items, fetched_at=now())
    await _keep(redis, user_id, link.url, snap)
    return snap


async def _categories(db: AsyncSession, names: Iterable[str]) -> dict[str, str]:
    """``market_hash_name → category`` of the catalogue items among ``names`` (one query)."""
    wanted = set(names)
    if not wanted:
        return {}
    rows = await db.execute(
        select(SkinItem.market_hash_name, SkinItem.category).where(
            SkinItem.market_hash_name.in_(wanted)
        )
    )
    return {name: category for name, category in rows.all()}


async def priced_inventory(
    db: AsyncSession,
    *,
    redis: Redis,
    user: User,
    client: DepositClient,
    settings: Settings,
    refresh: bool,
) -> InventoryOut:
    """The seller's items Skinslink accepts, priced in soʻm, dearest first.

    Raises:
        ConflictError: ``sales_disabled``, ``trade_link_missing``, ``trade_link_bad``,
            ``steam_refused``.
        RateUnavailableError: No fresh rate.
        SalesUnavailableError: Skinslink could not be asked.
    """
    doc = await open_settings(db, settings)
    link = trade_link_of(user)
    rate = await sale_rate_now(db, redis, settings, doc)
    user_id = user.id
    await db.rollback()  # no connection held across the Skinslink call (AGENTS §11)
    snap = await fetch_snapshot(redis, client, user_id=user_id, link=link, refresh=refresh)
    categories = await _categories(db, (i.name for i in snap.items))
    await db.rollback()
    priced = [(quote_item(i.price_usd, doc, rate).price_uzs, i) for i in snap.items]
    priced.sort(key=lambda pair: pair[0], reverse=True)
    return InventoryOut(
        items=[
            SellItemOut(
                asset_id=i.id,
                name=i.name,
                image_url=i.image_url,
                exterior=i.exterior,
                rarity_color=i.rarity_color,
                category=categories.get(i.name),
                price_uzs=wire_uzs(price),
            )
            for price, i in priced
            if price > 0
        ],
        max_items=snap.max_items,
        min_sum_uzs=wire_uzs(min_sum_uzs(doc, rate)),
        fetched_at=snap.fetched_at,
    )


__all__ = [
    "BREAKER_KEY",
    "BREAKER_TTL",
    "CACHE_TTL",
    "SalesUnavailableError",
    "Snapshot",
    "cache_key",
    "cached_snapshot",
    "fetch_snapshot",
    "forget_snapshot",
    "priced_inventory",
    "unavailable",
]
```

- [ ] **Step 5: Schemas and routes**

Append to `sales/schemas.py` (with `from decimal import Decimal` and `from csmarket.modules.sales.rules import SaleSettings` added to its imports):

```python
def plain(value: Decimal) -> str:
    """A percent or a price without trailing zeros or an exponent: ``2``, ``1.5``."""
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class SellConfigOut(BaseModel):
    """What the sell page shows before anything is chosen (public)."""

    enabled: bool
    balance_bonus_pct: str
    card_fee_pct: dict[CardType, str]
    #: Whole soʻm.
    card_min_uzs: str
    #: The minimum sum in soʻm, a hint (the API decides on the USD sum); ``null`` without a rate.
    min_sum_uzs: str | None
    max_cards: int

    @classmethod
    def of(
        cls, doc: SaleSettings, *, enabled: bool, min_sum_uzs: str | None, max_cards: int
    ) -> SellConfigOut:
        """Build from the settings document."""
        fees = doc.card_fee_pct
        return cls(
            enabled=enabled,
            balance_bonus_pct=plain(doc.balance_bonus_pct),
            card_fee_pct={
                "uzcard": plain(fees.uzcard),
                "humo": plain(fees.humo),
                "uzum_visa": plain(fees.uzum_visa),
            },
            card_min_uzs=str(doc.card_min_uzs),
            min_sum_uzs=min_sum_uzs,
            max_cards=max_cards,
        )


class SellItemOut(BaseModel):
    """One item the seller can sell now, at our price."""

    asset_id: str
    #: Steam's market name; skin names stay English.
    name: str
    image_url: str | None
    exterior: str | None
    rarity_color: str | None
    #: Our catalogue's category for the filter chips; ``null`` when we do not list the item.
    category: str | None
    price_uzs: str


class InventoryOut(BaseModel):
    """The priced inventory; ``max_items`` is the most one sale may carry."""

    items: list[SellItemOut]
    max_items: int
    min_sum_uzs: str
    fetched_at: datetime
```

```python
# apps/api/src/csmarket/modules/sales/routes.py
"""``/api/v1/sell*`` and ``/api/v1/sales*`` — selling skins to us (spec 2026-10-08 §5).

Routers parse and dispatch: the inventory is :mod:`.inventory`, a sale :mod:`.service`,
the reads :mod:`.views`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.money import wire_uzs
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.cards import MAX_LIVE_CARDS
from csmarket.modules.sales.clients import inventory_client
from csmarket.modules.sales.inventory import priced_inventory
from csmarket.modules.sales.pricing import min_sum_uzs, sale_rate
from csmarket.modules.sales.schemas import InventoryOut, SellConfigOut
from csmarket.modules.sales.settings_store import read_sale_settings
from csmarket.modules.skinslink.api import DepositClient
from csmarket.modules.users.api import User

router = APIRouter(tags=["sales"])

Db = Annotated[AsyncSession, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]


@router.get("/sell/config", response_model=SellConfigOut, summary="How selling works now")
async def get_sell_config(db: Db) -> SellConfigOut:
    """Public: whether selling is on, the bonus, the card fees and minimums."""
    settings = get_settings()
    doc = await read_sale_settings(db)
    fx = await current_usd_uzs(
        db, get_redis(), max_age_days=settings.fx_max_age_days, uplift_pct=Decimal(0)
    )
    minimum = None if fx is None else wire_uzs(min_sum_uzs(doc, sale_rate(fx.rate, doc)))
    return SellConfigOut.of(
        doc,
        enabled=settings.sales_active and doc.enabled,
        min_sum_uzs=minimum,
        max_cards=MAX_LIVE_CARDS,
    )


@router.get("/sell/inventory", response_model=InventoryOut, summary="My inventory, priced")
async def get_sell_inventory(
    *,
    request: Request,
    user: Me,
    db: Db,
    client: Annotated[DepositClient, Depends(inventory_client)],
    refresh: bool = False,
) -> InventoryOut:
    """The items we buy now, at our soʻm prices; kept 5 minutes, ``?refresh=1`` asks again.

    409 ``code``s: ``sales_disabled``, ``trade_link_missing``, ``trade_link_bad`` (+ ``reason``),
    ``steam_refused`` (+ ``reason``: Skinslink's Steam account code). 503 ``sales_unavailable``
    or ``rate_unavailable``.
    """
    user_id = user.id
    await guard_ip(request, bucket="sell-inventory", subject=user_id)
    return await priced_inventory(
        db,
        redis=get_redis(),
        user=user,
        client=client,
        settings=get_settings(),
        refresh=refresh,
    )


__all__ = ["router"]
```

`api/v1/router.py`: `from csmarket.modules.sales.routes import router as sales_router` and `router.include_router(sales_router)` after `payout_cards_router`.

- [ ] **Step 6: Run the tests, the linters, regenerate the API**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_inventory.py -q && uv run ruff check src/csmarket/modules/sales src/csmarket/api tests/integration/sales_kit.py tests/integration/test_sales_inventory.py && uv run mypy src/csmarket/modules/sales && cd ../.. && make gen-api`
Expected: PASS; clean; the client gains `/sell/config` and `/sell/inventory`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/api/v1/router.py apps/api/tests/integration/sales_kit.py apps/api/tests/integration/test_sales_inventory.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/sales): the priced inventory — 5-minute snapshot per seller, a breaker, soʻm prices" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `POST /sell` — store, commit, one `create-deposit`, apply its answer

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/service.py`, `apps/api/src/csmarket/modules/sales/views.py`
- Modify: `apps/api/src/csmarket/modules/sales/schemas.py` (`NewCardIn`, `PayoutIn`, `SellIn`, `SaleOut` and its parts), `apps/api/src/csmarket/modules/sales/routes.py` (`POST /sell`)
- Test: `apps/api/tests/integration/test_sales_create.py`

**Interfaces:**

- Consumes: `cached_snapshot`, `forget_snapshot`, `Snapshot`, `unavailable` (Task 8); `open_settings`, `trade_link_of`, `sale_rate_now` (Task 8); `quote_item`, `payout_for`, `min_prices`, `min_sum_uzs`, `ItemQuote`, `Payout` (Task 4); `add_card`, `owned_card`, `card_digits` (Task 6); `lock_sale`, `apply_deposit` (Task 7); `PRICE_CODES`, `STEAM_ACCOUNT_CODES`, `SkinslinkError`, `SkinslinkForbiddenError`, `SkinslinkUnavailableError` (Task 2); `core.numbers.allocate`, `sale_number`, `is_sale_number`.
- Produces in `schemas.py`: `NewCardIn(type: CardType, number: str)` (`repr=False`), `PayoutIn(to: PayoutTo, card_id: uuid.UUID | None, new_card: NewCardIn | None)`, `SellIn(asset_ids: list[str], payout: PayoutIn, expected_payout_uzs: int)`, `SaleStatusOut`, `PayoutStatusOut`, `SaleItemOut(asset_id, name, image_url, price_uzs)`, `SaleCardOut(type, last4)`, `SaleOfferOut(url, bot_name, expires_at)`, `SaleOut(number, status, payout_to, card, items_uzs, bonus_uzs, fee_uzs, payout_uzs, items, offer, money_at, payout_status, created_at)`, `OFFER_URL = "https://steamcommunity.com/tradeoffer/{id}/"`.
- Produces in `views.py`: `@dataclass(frozen=True) SaleRow(sale: Sale, items: list[SaleItem], card: PayoutCard | None, request: PayoutRequest | None)`, `rows_of(db, sales: list[Sale]) -> list[SaleRow]` (three queries, no N+1), `sale_out(row: SaleRow) -> SaleOut`, `owned_sale(db, user_id: str, number: str) -> SaleRow | None`.
- Produces in `service.py`: `create_sale(db, *, redis, user: User, body: SellIn, idempotency_key: str, client: DepositClient, settings: Settings) -> tuple[Sale, bool]` (`False` = a replayed key).
- Produces route: `POST /api/v1/sell` (`Idempotency-Key` required; bucket `sell-create`) → 201 `SaleOut` (200 on a replay). 409 `code`s: `sales_disabled`, `trade_link_missing`, `trade_link_bad`, `prices_changed`, `below_minimum` (+ `min_sum_uzs`), `below_card_minimum` (+ `card_min_uzs`), `too_many_items` (+ `max_items`), `steam_refused` (+ `reason`), `cards_limit`; 422 `card_invalid`; 404 for a card not the seller's; 503 `sales_unavailable` / `rate_unavailable`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_sales_create.py
"""``POST /sell``: re-priced from the kept snapshot, stored before the one Skinslink call."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.modules.sales.models import PayoutCard, Sale, SaleItem
from csmarket.modules.skinslink.api import (
    Inventory,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.fake_deposit_client import FakeDepositClient, deposit, inv_item
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import HUMO, make_card
from tests.integration.sales_kit import (  # noqa: F401 -- the fixture
    Headers,
    ready_seller,
    sales_on,
    use_client,
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/sell"
TWO = Inventory(
    items=[inv_item("100", "12.45"), inv_item("101", "0.5", "P250 | Sand Dune (Field-Tested)")],
    max_items=50,
)
#: Skinslink's prices of TWO sum to 12.95 $; at the test rate: 149 600 + 5 600 = 155 200 soʻm.
BALANCE = {"asset_ids": ["100", "101"], "payout": {"to": "balance"}, "expected_payout_uzs": 158_300}


def _key(n: int = 1) -> dict[str, str]:
    return {"Idempotency-Key": f"test-sell-key-{n:08d}"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        inventory=[TWO], created=deposit("active", amount_usd=Decimal("12.95"))
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _seller(
    db: AsyncSession, client: AsyncClient, customer_headers: Headers
) -> dict[str, str]:
    """A ready seller whose inventory was read (the snapshot is kept)."""
    headers = await ready_seller(db, customer_headers)
    assert (await client.get("/api/v1/sell/inventory", headers=headers)).status_code == 200
    return headers


async def _sale(db: AsyncSession, number: str) -> Sale:
    sale = await db.scalar(
        select(Sale).where(Sale.number == number).execution_options(populate_existing=True)
    )
    assert sale is not None
    return sale


async def test_a_balance_sale_is_offered_with_the_payout_it_showed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["payout_to"], body["payout_uzs"], body["bonus_uzs"]) == (
        "offered",
        "balance",
        "158300",
        "3100",
    )
    assert body["offer"] == {
        "url": "https://steamcommunity.com/tradeoffer/6912345678/",
        "bot_name": "Bot #3",
        "expires_at": "2026-10-08T12:30:00Z",
    }
    assert [(i["asset_id"], i["price_uzs"]) for i in body["items"]] == [
        ("100", "149600"),
        ("101", "5600"),
    ]
    sale = await _sale(db_session, body["number"])
    assert (sale.quoted_usd, sale.items_uzs, sale.margin_usd) == (
        Decimal("12.95"),
        Decimal(155_200),
        Decimal("0.6735"),
    )
    [call] = fake.deposit_calls
    assert (call["merchant_tx_id"], call["asset_ids"]) == (sale.id, ["100", "101"])


async def test_min_prices_are_99_percent_rounded_down(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert fake.deposit_calls[0]["min_prices"] == {
        "100": Decimal("12.325"),
        "101": Decimal("0.495"),
    }


async def test_a_replayed_key_answers_the_same_sale_and_calls_once(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    first = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    again = await integration_client.post(
        URL, json={**BALANCE, "asset_ids": ["100"]}, headers={**headers, **_key()}
    )
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["number"] == first.json()["number"]
    assert len(fake.deposit_calls) == 1


async def test_a_new_card_is_saved_encrypted_and_paid_to(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": ["100", "101"],
        "payout": {"to": "card", "new_card": {"type": "humo", "number": "9860 1234 5678 9015"}},
        "expected_payout_uzs": 147_400,
    }
    with capture_logs() as logs:
        r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert r.status_code == 201, r.text
    assert (r.json()["card"], r.json()["fee_uzs"]) == ({"type": "humo", "last4": "9015"}, "7800")
    assert HUMO not in r.text and HUMO not in repr(logs)
    assert await db_session.scalar(select(func.count()).select_from(PayoutCard)) == 1


async def test_a_saved_card_of_someone_else_is_404(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    card = await make_card(db_session, await make_user(db_session))
    body = {**BALANCE, "payout": {"to": "card", "card_id": card.id}, "expected_payout_uzs": 147_400}
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert r.status_code == 404
    assert fake.deposit_calls == []


async def test_a_bad_card_number_is_422_without_echoing_it(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    bad = "9860123456789016"
    body = {
        **BALANCE,
        "payout": {"to": "card", "new_card": {"type": "humo", "number": bad}},
        "expected_payout_uzs": 147_400,
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (422, "card_invalid")
    assert bad not in r.text


async def test_under_the_minimum_sum_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(Inventory(items=[inv_item("1", "0.4"), inv_item("2", "0.5")], max_items=50))
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {"asset_ids": ["1", "2"], "payout": {"to": "balance"}, "expected_payout_uzs": 10_200}
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["min_sum_uzs"]) == (409, "below_minimum", "11300")
    assert await db_session.scalar(select(func.count()).select_from(Sale)) == 0


async def test_ten_cheap_items_reaching_the_minimum_are_accepted(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(
        Inventory(items=[inv_item(str(n), "0.10") for n in range(10)], max_items=50)
    )
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": [str(n) for n in range(10)],
        "payout": {"to": "balance"},
        "expected_payout_uzs": 11_200,  # 10 × 1 100, +2 % = 11 220 → 11 200
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert r.status_code == 201, r.text


async def test_a_card_payout_under_the_card_minimum_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(Inventory(items=[inv_item("1", "1.20")], max_items=50))
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": ["1"],
        "payout": {"to": "card", "new_card": {"type": "humo", "number": HUMO}},
        "expected_payout_uzs": 13_000,
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["card_min_uzs"]) == (
        409,
        "below_card_minimum",
        "30000",
    )
    assert await db_session.scalar(select(func.count()).select_from(PayoutCard)) == 0


@pytest.mark.parametrize(
    "body",
    [
        {**BALANCE, "expected_payout_uzs": 158_400},  # the cart showed another figure
        {**BALANCE, "asset_ids": ["100", "999"]},  # not in the kept snapshot
    ],
)
async def test_a_moved_price_or_an_unknown_item_is_prices_changed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
    body: dict[str, object],
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "prices_changed")
    assert fake.deposit_calls == []


async def test_without_a_kept_snapshot_is_prices_changed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)  # the inventory never read
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "prices_changed")


async def test_more_than_max_items_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(Inventory(items=TWO.items, max_items=1))
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["max_items"]) == (409, "too_many_items", 1)


async def test_skinslink_crediting_less_than_quoted_keeps_the_payout(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = deposit("active", amount_usd=Decimal("12.83"))  # above the 99 % floors
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["payout_uzs"]) == (201, "158300")
    sale = await _sale(db_session, r.json()["number"])
    assert (sale.quoted_usd, sale.amount_usd, sale.payout_uzs) == (
        Decimal("12.95"),
        Decimal("12.83"),
        Decimal(158_300),
    )


@pytest.mark.parametrize("code", ["item_specified_price_not_found", "inventory_reload"])
async def test_a_price_under_the_floor_is_prices_changed_and_closes_the_sale(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
    code: str,
) -> None:
    fake.created = SkinslinkError("refused", status=400, code=code)
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "prices_changed")
    sale = await db_session.scalar(select(Sale).execution_options(populate_existing=True))
    assert sale is not None and (sale.status, sale.fail_reason) == ("closed", code)
    calls = fake.inventory_calls
    await integration_client.get("/api/v1/sell/inventory", headers=headers)
    assert fake.inventory_calls == calls + 1  # the kept snapshot was dropped


async def test_a_steam_refusal_closes_the_sale_and_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkError("refused", status=400, code="profile_private")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["reason"]) == (
        409,
        "steam_refused",
        "profile_private",
    )


async def test_a_used_tx_id_is_adopted_through_the_status(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkError("refused", status=409, code="already_exists")
    fake.status = deposit("active")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["status"]) == (201, "offered")
    assert len(fake.status_calls) == 1


async def test_a_timeout_leaves_the_sale_creating_for_the_poll(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkUnavailableError("ReadTimeout")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["status"], r.json()["offer"]) == (201, "creating", None)


async def test_a_forbidden_answer_closes_and_is_503(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkForbiddenError("forbidden", status=403)
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (503, "sales_unavailable")
    sale = await db_session.scalar(select(Sale).execution_options(populate_existing=True))
    assert sale is not None and (sale.status, sale.fail_reason) == ("closed", "forbidden")


async def test_selling_off_stores_nothing(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)  # env switch off
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "sales_disabled")
    assert await db_session.scalar(select(func.count()).select_from(SaleItem)) == 0


async def test_without_a_key_is_422(
    integration_client: AsyncClient, customer_headers: Headers, sales_on: None
) -> None:
    r = await integration_client.post(URL, json=BALANCE, headers=await customer_headers())
    assert r.status_code == 422
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_create.py -q`
Expected: FAIL — 405 Method Not Allowed on `POST /api/v1/sell` (no route yet).

- [ ] **Step 3: The request and answer shapes**

Append to `sales/schemas.py` (imports: `import uuid`, `from typing import Literal`, `from pydantic import Field, model_validator`, `from csmarket.modules.sales.rules import PayoutTo`):

```python
#: A Steam trade offer's page.
OFFER_URL = "https://steamcommunity.com/tradeoffer/{id}/"

SaleStatusOut = Literal["creating", "offered", "hold", "credited", "payout", "closed", "reverted"]
PayoutStatusOut = Literal["waiting_hold", "to_pay", "paid", "rejected", "canceled"]


class NewCardIn(BaseModel):
    """A card typed in the cart. PII: ``number`` never appears in a repr or a log."""

    type: CardType
    #: Digits; spaces and dashes allowed. Checked by the service (``card_invalid``).
    number: str = Field(min_length=12, max_length=32, repr=False)


class PayoutIn(BaseModel):
    """Where the money goes: the balance, a saved card, or a new card."""

    to: PayoutTo
    card_id: uuid.UUID | None = None
    new_card: NewCardIn | None = None

    @model_validator(mode="after")
    def _one_target(self) -> PayoutIn:
        cards = (self.card_id is not None) + (self.new_card is not None)
        if self.to == "balance" and cards:
            raise ValueError("a payout to the balance takes no card")
        if self.to == "card" and cards != 1:
            raise ValueError("a card payout takes card_id or new_card, one of them")
        return self


class SellIn(BaseModel):
    """``POST /sell``: the chosen asset ids, where the money goes, the payout the cart showed."""

    asset_ids: list[str] = Field(min_length=1, max_length=200)
    payout: PayoutIn
    #: Whole soʻm the cart showed; another server figure is 409 ``prices_changed``.
    expected_payout_uzs: int = Field(ge=0)


class SaleItemOut(BaseModel):
    """An item of a sale at the price the seller saw."""

    asset_id: str
    name: str
    image_url: str | None
    price_uzs: str


class SaleCardOut(BaseModel):
    """The card a sale pays to."""

    type: CardType
    last4: str


class SaleOfferOut(BaseModel):
    """The Steam offer to accept, while the sale is ``offered``."""

    url: str
    bot_name: str | None
    expires_at: datetime | None


class SaleOut(BaseModel):
    """A sale as its seller sees it. Money in whole soʻm, as strings."""

    number: str
    status: SaleStatusOut
    payout_to: PayoutTo
    card: SaleCardOut | None
    items_uzs: str
    bonus_uzs: str
    fee_uzs: str
    payout_uzs: str
    items: list[SaleItemOut]
    offer: SaleOfferOut | None
    #: When the money is due (while ``hold``).
    money_at: datetime | None
    #: A card sale's payout request, once there is one.
    payout_status: PayoutStatusOut | None
    created_at: datetime
```

(`SellItemOut` from Task 8 stays as it is — it is the inventory card; `SaleItemOut` is an item inside a sale.)

- [ ] **Step 4: `views.py`**

```python
# apps/api/src/csmarket/modules/sales/views.py
"""Sales as their seller sees them: one by number, and the shape of the answer.

A page of sales loads its items, cards and requests in one query each (no N+1).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.money import wire_uzs
from csmarket.core.numbers import is_sale_number
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale, SaleItem
from csmarket.modules.sales.schemas import (
    OFFER_URL,
    SaleCardOut,
    SaleItemOut,
    SaleOfferOut,
    SaleOut,
)


@dataclass(frozen=True)
class SaleRow:
    """A sale and what its page shows of its items, card and request."""

    sale: Sale
    items: list[SaleItem]
    card: PayoutCard | None
    request: PayoutRequest | None


async def rows_of(db: AsyncSession, sales: list[Sale]) -> list[SaleRow]:
    """``sales`` with their items, cards and requests: three queries for any number."""
    if not sales:
        return []
    ids = [s.id for s in sales]
    items: dict[str, list[SaleItem]] = defaultdict(list)
    for item in await db.scalars(
        select(SaleItem).where(SaleItem.sale_id.in_(ids)).order_by(SaleItem.price_uzs.desc())
    ):
        items[item.sale_id].append(item)
    card_ids = {s.payout_card_id for s in sales if s.payout_card_id is not None}
    cards = {
        c.id: c
        for c in (
            await db.scalars(select(PayoutCard).where(PayoutCard.id.in_(card_ids)))
            if card_ids
            else []
        )
    }
    requests = {
        r.sale_id: r
        for r in await db.scalars(select(PayoutRequest).where(PayoutRequest.sale_id.in_(ids)))
    }
    return [
        SaleRow(
            sale=s,
            items=items[s.id],
            card=cards.get(s.payout_card_id) if s.payout_card_id else None,
            request=requests.get(s.id),
        )
        for s in sales
    ]


def sale_out(row: SaleRow) -> SaleOut:
    """The seller's view of ``row``."""
    s = row.sale
    offer = None
    if s.status == "offered" and s.trade_offer_id:
        offer = SaleOfferOut(
            url=OFFER_URL.format(id=s.trade_offer_id),
            bot_name=s.bot_name,
            expires_at=s.offer_expiry_at,
        )
    to_card = s.payout_to == "card"
    zero = Decimal(0)
    return SaleOut(
        number=s.number,
        status=s.status,  # type: ignore[arg-type]  # the column's check admits only these
        payout_to=s.payout_to,  # type: ignore[arg-type]
        card=SaleCardOut(type=row.card.type, last4=row.card.last4)  # type: ignore[arg-type]
        if row.card is not None
        else None,
        items_uzs=wire_uzs(s.items_uzs),
        bonus_uzs=wire_uzs(zero if to_card else s.payout_uzs - s.items_uzs),
        fee_uzs=wire_uzs(s.items_uzs - s.payout_uzs if to_card else zero),
        payout_uzs=wire_uzs(s.payout_uzs),
        items=[
            SaleItemOut(
                asset_id=i.asset_id,
                name=i.name,
                image_url=i.image_url,
                price_uzs=wire_uzs(i.price_uzs),
            )
            for i in row.items
        ],
        offer=offer,
        money_at=s.hold_end_at if s.status == "hold" else None,
        payout_status=row.request.status if row.request is not None else None,  # type: ignore[arg-type]
        created_at=s.created_at,
    )


async def owned_sale(db: AsyncSession, user_id: str, number: str) -> SaleRow | None:
    """``user_id``'s sale ``number``; ``None`` for anyone else's, unknown or malformed."""
    if not is_sale_number(number):
        return None
    sale = await db.scalar(
        select(Sale)
        .where(Sale.number == number, Sale.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if sale is None:
        return None
    [row] = await rows_of(db, [sale])
    return row


__all__ = ["SaleRow", "owned_sale", "rows_of", "sale_out"]
```

- [ ] **Step 5: `service.py`**

```python
# apps/api/src/csmarket/modules/sales/service.py
"""``POST /sell``: a sale from the seller's kept inventory, then one ``create-deposit``.

Re-prices the chosen items from the snapshot the seller saw (Redis, 5 min — never the
browser's numbers), checks the switches, the minimums, ``max_items`` and that the payout is
the one the cart showed, stores the sale (``creating``), its items and a new card in one
transaction and commits; only then calls Skinslink — one call, nothing open across it (AGENTS
§11, ADR-0016). Its answer is applied by :func:`.status.apply_deposit`, like any later
status. ``min_prices`` floors every item at 99 % of its quoted price; the seller's payout is
fixed here, whatever Skinslink credits above the floor (spec §3).

A refusal closes the sale (``fail_reason`` = the code) and answers 409 (``prices_changed``
also drops the kept snapshot); a 403 closes it and answers 503; an outage or a timeout leaves
it ``creating`` for the poll; ``409 already exist`` — the call landed after all — is adopted
through ``deposit/status``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_uzs
from csmarket.core.numbers import allocate, sale_number
from csmarket.modules.sales.cards import add_card, card_digits, owned_card
from csmarket.modules.sales.gate import open_settings, sale_rate_now, trade_link_of
from csmarket.modules.sales.inventory import (
    Snapshot,
    cached_snapshot,
    forget_snapshot,
    unavailable,
)
from csmarket.modules.sales.models import Sale, SaleItem
from csmarket.modules.sales.pricing import (
    ItemQuote,
    Payout,
    min_prices,
    min_sum_uzs,
    payout_for,
    quote_item,
)
from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings
from csmarket.modules.sales.schemas import PayoutIn, SellIn
from csmarket.modules.sales.status import apply_deposit, lock_sale
from csmarket.modules.skinslink.api import (
    PRICE_CODES,
    STEAM_ACCOUNT_CODES,
    Deposit,
    DepositClient,
    InventoryItem,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import TradeLink, User

log = get_logger("csmarket.sales.service")

_USD = Decimal("0.000001")


@dataclass(frozen=True)
class _Draft:
    """Everything the sale row needs, checked; nothing written yet."""

    user_id: str
    link: TradeLink = field(repr=False)
    rate: Decimal
    chosen: list[InventoryItem]
    quotes: list[ItemQuote]
    payout: Payout
    payout_to: PayoutTo
    card_id: str | None
    #: ``(type, digits)`` of a card typed in the cart. PII: never in a repr or a log.
    new_card: tuple[CardType, str] | None = field(repr=False)

    @property
    def quoted_usd(self) -> Decimal:
        return sum((i.price_usd for i in self.chosen), Decimal(0))

    @property
    def margin_usd(self) -> Decimal:
        return sum((q.margin_usd for q in self.quotes), Decimal(0))


def _prices_changed() -> ConflictError:
    return ConflictError("prices changed; read the inventory again", code="prices_changed")


async def _by_key(db: AsyncSession, user_id: str, key: str) -> Sale | None:
    return await db.scalar(select(Sale).where(Sale.user_id == user_id, Sale.idempotency_key == key))


def _pick(snap: Snapshot, asset_ids: Sequence[str]) -> list[InventoryItem]:
    """The chosen items from the kept snapshot, in the order asked (duplicates once)."""
    wanted = list(dict.fromkeys(asset_ids))
    if len(wanted) > snap.max_items:
        raise ConflictError(
            "too many items for one sale", code="too_many_items", max_items=snap.max_items
        )
    by_id = {i.id: i for i in snap.items}
    if any(a not in by_id for a in wanted):
        raise _prices_changed()
    return [by_id[a] for a in wanted]


async def _card(
    db: AsyncSession, user_id: str, payout: PayoutIn
) -> tuple[CardType | None, str | None, tuple[CardType, str] | None]:
    """``(card type, saved card id, new card)`` of the payout; all ``None`` for the balance."""
    if payout.to == "balance":
        return None, None, None
    if payout.card_id is not None:
        card = await owned_card(db, user_id=user_id, card_id=str(payout.card_id))
        kind: CardType = card.type  # type: ignore[assignment]  # the column's check
        return kind, card.id, None
    if payout.new_card is None:  # PayoutIn's validator makes this unreachable
        raise ValueError("a card payout without a card")
    new = payout.new_card
    return new.type, None, (new.type, card_digits(new.type, new.number))


def _check_minimums(
    doc: SaleSettings, rate: Decimal, quoted: Decimal, payout: Payout, to: PayoutTo
) -> None:
    if quoted < doc.min_sum_usd:
        raise ConflictError(
            "the items are worth less than the minimum",
            code="below_minimum",
            min_sum_uzs=wire_uzs(min_sum_uzs(doc, rate)),
        )
    if to == "card" and payout.payout_uzs < doc.card_min_uzs:
        raise ConflictError(
            "a card payout is under the minimum",
            code="below_card_minimum",
            card_min_uzs=str(doc.card_min_uzs),
        )


async def _draft(
    db: AsyncSession, redis: Redis, user: User, body: SellIn, settings: Settings
) -> _Draft:
    """Every check and every number of the sale, from the kept snapshot."""
    doc = await open_settings(db, settings)
    link = trade_link_of(user)
    rate = await sale_rate_now(db, redis, settings, doc)
    snap = await cached_snapshot(redis, user.id, link.url)
    if snap is None:
        raise _prices_changed()
    chosen = _pick(snap, body.asset_ids)
    quotes = [quote_item(i.price_usd, doc, rate) for i in chosen]
    if any(q.price_uzs <= 0 for q in quotes):  # hidden from the list: never sold for nothing
        raise _prices_changed()
    card_type, card_id, new_card = await _card(db, user.id, body.payout)
    items_uzs = sum((q.price_uzs for q in quotes), Decimal(0))
    payout = payout_for(items_uzs, doc, to=body.payout.to, card_type=card_type)
    quoted = sum((i.price_usd for i in chosen), Decimal(0))
    _check_minimums(doc, rate, quoted, payout, body.payout.to)
    if payout.payout_uzs != body.expected_payout_uzs:
        raise _prices_changed()
    return _Draft(
        user_id=user.id,
        link=link,
        rate=rate,
        chosen=chosen,
        quotes=quotes,
        payout=payout,
        payout_to=body.payout.to,
        card_id=card_id,
        new_card=new_card,
    )


async def _store(db: AsyncSession, draft: _Draft, key: str) -> tuple[Sale, bool]:
    """The sale, its items and a new card in one transaction; a key that raced us replays."""
    card_id = draft.card_id
    if draft.new_card is not None:
        card_type, digits = draft.new_card
        card = await add_card(db, user_id=draft.user_id, card_type=card_type, raw_number=digits)
        card_id = card.id
    sale = Sale(
        id=new_id(),
        number=await allocate(db, Sale.number, sale_number),
        user_id=draft.user_id,
        status="creating",
        payout_to=draft.payout_to,
        payout_card_id=card_id,
        quoted_usd=draft.quoted_usd.quantize(_USD),
        items_uzs=draft.payout.items_uzs,
        payout_uzs=draft.payout.payout_uzs,
        rate=draft.rate,
        margin_usd=draft.margin_usd.quantize(_USD),
        idempotency_key=key,
    )
    db.add(sale)
    db.add_all(
        SaleItem(
            sale_id=sale.id,
            asset_id=item.id,
            name=item.name[:255],
            image_url=item.image_url,
            price_usd=item.price_usd.quantize(_USD),
            price_uzs=quote.price_uzs,
        )
        for item, quote in zip(draft.chosen, draft.quotes, strict=True)
    )
    try:
        await db.flush()
    except IntegrityError:  # the same key raced us: the other request's sale stands
        await db.rollback()
        replay = await _by_key(db, draft.user_id, key)
        if replay is None:
            raise
        return replay, False
    await db.commit()
    return sale, True


async def _apply(db: AsyncSession, sale_id: str, report: Deposit) -> Sale:
    locked = await lock_sale(db, sale_id)
    if locked is None:  # the row was committed above; only a bug gets here
        raise unavailable()
    await apply_deposit(db, locked, report, at=now())
    if report.amount_usd is not None and report.amount_usd < locked.quoted_usd:
        log.info(
            "sales.amount_below_quote",
            number=locked.number,
            quoted_usd=str(locked.quoted_usd),
            amount_usd=str(report.amount_usd),
        )
    await db.commit()
    return locked


async def _reload(db: AsyncSession, sale_id: str) -> Sale:
    sale = await db.get(Sale, sale_id, populate_existing=True)
    if sale is None:
        raise unavailable()
    return sale


async def _close(db: AsyncSession, sale_id: str, reason: str) -> None:
    """Close a sale Skinslink refused (no deposit exists); the seller hears it at once."""
    sale = await lock_sale(db, sale_id)
    if sale is not None and sale.status == "creating":
        sale.status, sale.fail_reason = "closed", reason[:48]
    await db.commit()


async def _refused(
    db: AsyncSession,
    redis: Redis,
    client: DepositClient,
    sale_id: str,
    draft: _Draft,
    exc: SkinslinkError,
) -> Sale:
    if exc.status == 409 or exc.code == "already_exists":  # the call landed after all
        try:
            report = await client.deposit_status(merchant_tx_id=sale_id)
        except (SkinslinkError, SkinslinkUnavailableError):
            return await _reload(db, sale_id)
        if report is None:
            return await _reload(db, sale_id)
        return await _apply(db, sale_id, report)
    code = exc.code or f"http_{exc.status}"
    await _close(db, sale_id, code)
    if code in PRICE_CODES:
        await forget_snapshot(redis, draft.user_id, draft.link.url)
        raise _prices_changed()
    if code in STEAM_ACCOUNT_CODES:
        raise ConflictError(
            "Steam does not let this account trade", code="steam_refused", reason=code
        )
    if code == "too_many_items":
        raise ConflictError("too many items for one sale", code="too_many_items")
    raise unavailable()


async def _deposit(
    db: AsyncSession, redis: Redis, client: DepositClient, sale_id: str, draft: _Draft
) -> Sale:
    """The one Skinslink call; its answer applied, or the sale closed or left for the poll."""
    try:
        report = await client.create_deposit(
            merchant_tx_id=sale_id,
            partner=draft.link.partner,
            token=draft.link.token,
            asset_ids=[i.id for i in draft.chosen],
            min_prices=min_prices([(i.id, i.price_usd) for i in draft.chosen]),
        )
    except SkinslinkForbiddenError:
        await _close(db, sale_id, "forbidden")
        raise unavailable() from None
    except SkinslinkError as exc:
        return await _refused(db, redis, client, sale_id, draft, exc)
    except SkinslinkUnavailableError as exc:
        log.warning("sales.deposit_unanswered", error=type(exc).__name__)
        return await _reload(db, sale_id)
    return await _apply(db, sale_id, report)


async def create_sale(
    db: AsyncSession,
    *,
    redis: Redis,
    user: User,
    body: SellIn,
    idempotency_key: str,
    client: DepositClient,
    settings: Settings,
) -> tuple[Sale, bool]:
    """Open a sale of the chosen items at the payout the cart showed.

    Returns:
        ``(sale, created)`` — ``created`` is ``False`` for a replayed key (the stored sale,
        whatever ``body`` says).

    Raises:
        ConflictError: ``sales_disabled``, ``trade_link_missing``, ``trade_link_bad``,
            ``prices_changed``, ``below_minimum``, ``below_card_minimum``, ``too_many_items``,
            ``steam_refused``, ``cards_limit``.
        ValidationError: ``card_invalid``.
        NotFoundError: A saved card that is not the seller's.
        RateUnavailableError: No fresh rate.
        SalesUnavailableError: Skinslink refused for a reason of ours, or answered 403.
    """
    existing = await _by_key(db, user.id, idempotency_key)
    if existing is not None:
        return existing, False
    draft = await _draft(db, redis, user, body, settings)
    sale, created = await _store(db, draft, idempotency_key)
    if not created:
        return sale, False
    log.info(
        "sales.created",
        number=sale.number,
        payout_to=draft.payout_to,
        items=len(draft.chosen),
        payout_uzs=str(draft.payout.payout_uzs),
    )
    return await _deposit(db, redis, client, sale.id, draft), True


__all__ = ["create_sale"]
```

- [ ] **Step 6: The route**

Append to `sales/routes.py` (imports: `Header`, `Response` from fastapi; `IDEMPOTENCY_HEADER`, `require_idempotency_key` from `core.idempotency`; `NotFoundError`; `deposit_client` from `.clients`; `create_sale` from `.service`; `SaleOut`, `SellIn` from `.schemas`; `owned_sale`, `sale_out` from `.views`):

```python
async def _owned_out(db: AsyncSession, user_id: str, number: str) -> SaleOut:
    row = await owned_sale(db, user_id, number)
    if row is None:
        raise NotFoundError("sale not found")
    return sale_out(row)


@router.post(
    "/sell",
    response_model=SaleOut,
    status_code=201,
    summary="Sell skins",
    responses={200: {"model": SaleOut, "description": "replayed key"}},
)
async def post_sell(
    *,
    body: SellIn,
    request: Request,
    response: Response,
    user: Me,
    db: Db,
    client: Annotated[DepositClient, Depends(deposit_client)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SaleOut:
    """Sell the chosen items at the payout the cart showed; one Steam offer follows.

    ``Idempotency-Key`` (16..160 chars) is required; a replayed key answers 200 with the stored
    sale whatever the body says. 409 ``code``s: ``sales_disabled``, ``trade_link_missing``,
    ``trade_link_bad``, ``prices_changed`` (read the inventory again), ``below_minimum``
    (+ ``min_sum_uzs``), ``below_card_minimum`` (+ ``card_min_uzs``), ``too_many_items``,
    ``steam_refused`` (+ ``reason``), ``cards_limit``. 422 ``card_invalid``. 404 for a card
    that is not mine. 503 ``sales_unavailable`` / ``rate_unavailable``.
    """
    key = require_idempotency_key(idempotency_key)
    user_id = user.id
    await guard_ip(request, bucket="sell-create", subject=user_id)
    sale, created = await create_sale(
        db,
        redis=get_redis(),
        user=user,
        body=body,
        idempotency_key=key,
        client=client,
        settings=get_settings(),
    )
    if not created:
        response.status_code = 200
    return await _owned_out(db, user_id, sale.number)
```

- [ ] **Step 7: Run the tests, the linters, regenerate the API**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_create.py tests/integration/test_sales_inventory.py -q && uv run ruff check src/csmarket/modules/sales tests/integration/test_sales_create.py && uv run mypy src/csmarket/modules/sales && cd ../.. && make gen-api`
Expected: PASS; clean; the client gains `POST /sell`.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/tests/integration/test_sales_create.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/sales): POST /sell — the payout fixed from the kept snapshot, then one create-deposit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The deposit webhook, the check queue, the poll, the overdue-payout alert

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/checks.py`, `apps/api/src/csmarket/modules/sales/reconcile.py`
- Modify: `apps/api/src/csmarket/modules/skinslink/routes.py` (the deposit branch, the gate)
- Modify: `apps/api/src/csmarket/core/metrics.py` (`csmarket_sale_payouts_overdue`)
- Modify: `apps/api/src/csmarket/modules/sales/api.py` (exports)
- Modify: `apps/worker/src/csmarket_worker/consumer.py` (the `sales` queue), `apps/worker/tests/test_consumer.py`
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/sales_poll.py`; modify `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/scheduler/tests/test_main.py`
- Create: `infra/prometheus/alerts/sales.yml`; modify `infra/prometheus/alerts/api.yml` (the two new routes in both `handler` regexes)
- Test: `apps/api/tests/integration/test_sales_webhook.py`, `apps/api/tests/integration/test_sales_reconcile.py`, `apps/scheduler/tests/test_sales_poll.py`

**Interfaces:**

- Consumes: `skinslink.webhook.verify(body, *, secret) -> int | None` (already accepts `trade_id`); `check_sale` (Task 7); `deposit_client_for` (Task 2); `SaleCheck`, `SALES_CHANNEL`, `Sale`, `PayoutRequest` (Task 3).
- Produces in `sales/checks.py`: `enqueue_sale_check(db, merchant_tx_id: object) -> bool` (queues only for a known sale id; never commits), `claim_sale_checks(db, *, limit: int = 20) -> list[str]`, `drain_sale_checks(db, *, client: DepositClient | None = None, settings: Settings | None = None, limit: int = 20) -> int`.
- Produces in `sales/reconcile.py`: `OPEN_POLL_EVERY = timedelta(seconds=60)`, `HOLD_POLL_EVERY = timedelta(minutes=30)`, `OVERDUE_AFTER = timedelta(hours=48)`, `BATCH = 50`, `payouts_overdue(db, *, at: datetime) -> int`, `poll_sales(db_factory: Callable[[], AsyncSession], client: DepositClient, *, at: datetime | None = None) -> int`.
- Produces in `core.metrics`: gauge `csmarket_sale_payouts_overdue`, `set_sale_payouts_overdue(count: int) -> None`.
- Produces: worker queue `Queue(name="sales", channel=SALES_CHANNEL, drain=_drain_sale_checks, concurrency=1)`; scheduler job `sales.poll` every 60 s (first run 125 s after start; the tick runs while `CSMARKET_SKINSLINK_API_KEY` is set, whatever the switches); alert `SalePayoutsOverdue`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_sales_webhook.py
"""The deposit webhook: a signature or 403; the body is never trusted — a check is queued."""

from __future__ import annotations

import base64
import hashlib
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.config import get_settings
from csmarket.core.ids import new_id
from csmarket.modules.sales.checks import drain_sale_checks
from csmarket.modules.sales.models import Sale, SaleCheck
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_factory import make_sale
from tests.integration.sales_kit import SECRET, sales_on  # noqa: F401 -- the fixture

pytestmark = pytest.mark.asyncio

URL = "/api/v1/skinslink/webhook"
TRADE = 178
#: The seller's Steam id rides the webhook; made up here, never logged.
STEAM_ID = "76561190000000001"


def _sign(trade_id: int) -> str:
    return base64.b64encode(hashlib.sha256((str(trade_id) + SECRET).encode()).digest()).decode()


def _body(sale_id: str, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "sign": _sign(TRADE),
        "status": "hold",
        "trade_id": TRADE,
        "merchant_tx_id": sale_id,
        "steam_id": STEAM_ID,
        "amount": 12.95,
        "amount_currency": "usd",
    }
    body.update(over)
    return body


async def _checks(db: AsyncSession) -> list[str]:
    return [str(x) for x in (await db.scalars(select(SaleCheck.sale_id))).all()]


async def test_off_is_404(integration_client: AsyncClient) -> None:
    r = await integration_client.post(URL, json=_body(new_id()))
    assert r.status_code == 404


async def test_a_signed_deposit_webhook_queues_a_check_of_its_sale(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None
) -> None:
    sale = await make_sale(db_session, status="offered")
    with capture_logs() as logs:
        r = await integration_client.post(URL, json=_body(sale.id))
    assert (r.status_code, r.json()) == (200, {"ok": True})
    assert await _checks(db_session) == [sale.id]
    assert STEAM_ID not in repr(logs)


@pytest.mark.parametrize(
    "over",
    [
        {"sign": "nope"},
        {"sign": _sign(TRADE + 1)},  # a signature made for another deposit
        {"trade_id": str(TRADE)},
        {"trade_id": True},
        {"sign": None},
    ],
)
async def test_a_forged_deposit_webhook_is_403_and_queues_nothing(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    sales_on: None,
    over: dict[str, Any],
) -> None:
    sale = await make_sale(db_session, status="offered")
    body = {k: v for k, v in _body(sale.id, **over).items() if v is not None}
    r = await integration_client.post(URL, json=body)
    assert r.status_code == 403, r.text
    assert await _checks(db_session) == []


@pytest.mark.parametrize("tx", ["not-a-uuid", "00000000-0000-4000-8000-000000000000", 7])
async def test_an_unknown_sale_is_answered_and_ignored(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None, tx: object
) -> None:
    r = await integration_client.post(URL, json=_body("x", merchant_tx_id=tx))
    assert r.status_code == 200
    assert await _checks(db_session) == []


async def test_the_webhook_body_is_never_trusted(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None
) -> None:
    sale = await make_sale(db_session, status="offered", payout_uzs=Decimal(158_300))
    r = await integration_client.post(URL, json=_body(sale.id, status="completed", amount=9999))
    assert r.status_code == 200
    client = FakeDepositClient(status=deposit("hold"))  # what Skinslink really says
    assert await drain_sale_checks(db_session, client=client, settings=get_settings()) == 1
    assert client.status_calls == [sale.id]
    fresh = await db_session.get(Sale, sale.id, populate_existing=True)
    assert fresh is not None and fresh.status == "hold"
    assert await user_balance(db_session, sale.user_id) == 0
    assert await _checks(db_session) == []  # the check was taken
```

`sales_on` switches on sales only (`CSMARKET_SKINSLINK_ENABLED` stays false), so these tests also pin that the webhook answers while only selling is active.

```python
# apps/api/tests/integration/test_sales_reconcile.py
"""The poll: open sales every minute, ``hold`` every 30 min; one credit when checks race."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.sales.reconcile import payouts_overdue, poll_sales
from csmarket.modules.sales.status import check_sale
from csmarket.modules.wallet.api import WalletTransaction, user_balance
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio


async def test_open_sales_every_minute_and_hold_every_half_hour(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    at = now()
    await make_sale(db_session, status="offered", last_polled_at=at - timedelta(seconds=30))
    offered = await make_sale(db_session, status="offered", last_polled_at=at - timedelta(seconds=61))
    creating = await make_sale(db_session, status="creating")
    await make_sale(db_session, status="hold", last_polled_at=at - timedelta(minutes=10))
    hold = await make_sale(db_session, status="hold", last_polled_at=at - timedelta(minutes=31))
    await make_sale(db_session, status="credited")
    client = FakeDepositClient(status=deposit("active"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await poll_sales(factory, client, at=at) == 3
    assert set(client.status_calls) == {offered.id, creating.id, hold.id}


async def test_two_checks_racing_on_completed_credit_once(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    client = FakeDepositClient(status=deposit("completed"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def one() -> str:
        async with factory() as db:
            return await check_sale(db, client, sale_id=sale.id)

    assert sorted(await asyncio.gather(one(), one())) == ["credited", "unchanged"]
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    count = await db_session.scalar(
        select(func.count()).select_from(WalletTransaction).where(
            WalletTransaction.reference_id == sale.id
        )
    )
    assert count == 1


async def test_overdue_payouts_are_counted_and_exported(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    at = now()
    old = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, old, status="to_pay", to_pay_at=at - timedelta(hours=49))
    young = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, young, status="to_pay", to_pay_at=at - timedelta(hours=1))
    assert await payouts_overdue(db_session, at=at) == 1
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await poll_sales(factory, FakeDepositClient(status=None), at=at)
    assert REGISTRY.get_sample_value("csmarket_sale_payouts_overdue") == 1.0


async def test_one_failing_sale_never_stops_the_tick(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    await make_sale(db_session, status="offered")
    await make_sale(db_session, status="offered")
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    client = FakeDepositClient(status=RuntimeError("boom"))
    assert await poll_sales(factory, client) == 2
    assert len(client.status_calls) == 2
```

```python
# apps/scheduler/tests/test_sales_poll.py
"""``sales.poll``: runs while a Skinslink key is set, never raises, every 60 s."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import sales_poll as job


def _settings(monkeypatch: pytest.MonkeyPatch, **update: object) -> None:
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_skipped_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock()
    monkeypatch.setattr(job, "poll_sales", tick)
    _settings(monkeypatch, skinslink_api_key="")
    await job.run()
    tick.assert_not_awaited()


async def test_switched_off_with_a_key_still_settles_open_sales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "poll_sales", tick)
    _settings(monkeypatch, sales_enabled=False, skinslink_api_key="k")
    await job.run()
    tick.assert_awaited_once()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "poll_sales", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, skinslink_api_key="k")
    await job.run()


def test_registers_every_60_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 60
```

In `apps/worker/tests/test_consumer.py`, `test_registers_the_orders_and_emails_queues` becomes:

```python
def test_registers_the_orders_and_emails_queues() -> None:
    """Orders two drainers wide, the rest one, each on the channel its module NOTIFYs."""
    from csmarket.modules.notifications.api import EMAILS_CHANNEL
    from csmarket.modules.orders.api import ORDERS_CHANNEL
    from csmarket.modules.sales.api import SALES_CHANNEL
    from csmarket.modules.skinslink.api import SKINSLINK_CHANNEL

    orders, emails, skinslink, sales = _queues(get_settings())
    assert (orders.name, orders.channel, orders.concurrency) == ("orders", ORDERS_CHANNEL, 2)
    assert orders.drain is consumer._drain_orders
    assert (emails.name, emails.channel, emails.concurrency) == ("emails", EMAILS_CHANNEL, 1)
    assert emails.drain is consumer._drain_emails
    assert (skinslink.name, skinslink.channel, skinslink.concurrency) == (
        "skinslink",
        SKINSLINK_CHANNEL,
        1,
    )
    assert skinslink.drain is consumer._drain_skinslink_checks
    assert (sales.name, sales.channel, sales.concurrency) == ("sales", SALES_CHANNEL, 1)
    assert sales.drain is consumer._drain_sale_checks
```

In `apps/scheduler/tests/test_main.py`, the expected job list gains `"sales.poll",` after `"lisskins.balance",`.

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_webhook.py tests/integration/test_sales_reconcile.py -q; cd ../scheduler && uv run pytest tests/test_sales_poll.py tests/test_main.py -q; cd ../worker && uv run pytest tests/test_consumer.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.sales.checks`, `ImportError` of `sales_poll`, and the worker's tuple unpacking.

- [ ] **Step 3: The queue**

```python
# apps/api/src/csmarket/modules/sales/checks.py
"""«Ask Skinslink about sale N» rows, drained by the worker's ``sales`` queue (spec §6).

The deposit webhook — after its signature — inserts a row and notifies in its transaction;
only a known sale id is queued (``merchant_tx_id`` is the sale's id), so a forged or stray id
queues nothing. The drain claims rows ``FOR UPDATE SKIP LOCKED``, deletes them and asks
Skinslink about each (``status.check_sale``). A failed ask is not retried by the row: the
poll (:mod:`.reconcile`) asks about every open sale anyway.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings, get_settings
from csmarket.core.logging import get_logger
from csmarket.modules.sales.models import SALES_CHANNEL, Sale, SaleCheck
from csmarket.modules.sales.status import check_sale
from csmarket.modules.skinslink.api import DepositClient, deposit_client_for

log = get_logger("csmarket.sales.checks")


async def enqueue_sale_check(db: AsyncSession, merchant_tx_id: object) -> bool:
    """Queue a check of the sale ``merchant_tx_id`` names; delivered when the caller commits.

    Returns:
        Whether a check was queued (``False``: not a sale id of ours).
    """
    if not isinstance(merchant_tx_id, str):
        return False
    try:
        sale_id = str(uuid.UUID(merchant_tx_id))
    except ValueError:
        return False
    if await db.scalar(select(Sale.id).where(Sale.id == sale_id)) is None:
        return False
    db.add(SaleCheck(sale_id=sale_id))
    await db.flush()
    await db.execute(select(func.pg_notify(SALES_CHANNEL, sale_id)))
    return True


async def claim_sale_checks(db: AsyncSession, *, limit: int = 20) -> list[str]:
    """Take up to ``limit`` queued checks, oldest first, and delete them; the caller commits.

    Returns:
        The sale ids to ask about (a sale queued twice is asked once).
    """
    rows = (
        await db.execute(
            select(SaleCheck.id, SaleCheck.sale_id)
            .order_by(SaleCheck.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return []
    await db.execute(delete(SaleCheck).where(SaleCheck.id.in_([r[0] for r in rows])))
    return list(dict.fromkeys(str(r[1]) for r in rows))


async def drain_sale_checks(
    db: AsyncSession,
    *,
    client: DepositClient | None = None,
    settings: Settings | None = None,
    limit: int = 20,
) -> int:
    """The worker's ``sales`` drain: take queued checks and ask Skinslink about each.

    Returns:
        How many checks were taken (0 = the queue is dry).
    """
    settings = settings or get_settings()
    ids = await claim_sale_checks(db, limit=limit)
    await db.commit()
    # The key, not the switches: open sales still settle after selling is switched off.
    if not ids or (client is None and not settings.skinslink_api_key):
        return len(ids)
    client = client or deposit_client_for(
        settings, timeout_seconds=settings.skinslink_request_timeout_seconds
    )
    for sale_id in ids:
        try:
            await check_sale(db, client, sale_id=sale_id)
        except Exception as exc:  # noqa: BLE001 -- one bad check must not stop the batch
            await db.rollback()
            log.error("sales.check_crashed", error=type(exc).__name__)  # noqa: TRY400
    return len(ids)


__all__ = ["claim_sale_checks", "drain_sale_checks", "enqueue_sale_check"]
```

- [ ] **Step 4: The webhook routes deposits to the queue**

`skinslink/routes.py` — the module docstring's second sentence becomes "…a purchase webhook queues a purchase check, a deposit webhook (`trade_id`, spec 2026-10-08) a check of the sale its `merchant_tx_id` names (`sales.checks`); the worker asks Skinslink either way. 404 while neither Skinslink buying nor selling is active.", the import `from csmarket.modules.sales.api import enqueue_sale_check` is added, and the handler's gate and branch become:

```python
    settings = get_settings()
    if not (settings.skinslink_active or settings.sales_active):
        raise NotFoundError("not found")
```

```python
    kind = "purchase" if "purchase_id" in body else "deposit"
    if kind == "purchase":
        await enqueue_check(db, pid)
    else:
        await enqueue_sale_check(db, body.get("merchant_tx_id"))
    await db.commit()
    log.info("skinslink.webhook", kind=kind)
    return {"ok": True}
```

(The body's `steam_id`, `status` and `amount` are never read.)

`sales/api.py`: add `from csmarket.modules.sales.checks import drain_sale_checks, enqueue_sale_check` and `from csmarket.modules.sales.reconcile import poll_sales`, and the three names to `__all__`.

- [ ] **Step 5: The poll and the gauge**

`core/metrics.py`, beside the other scheduler gauges:

```python
SALE_PAYOUTS_OVERDUE = Gauge(
    "csmarket_sale_payouts_overdue",
    "Card payouts payable for over 48 h (alert: SalePayoutsOverdue; set by sales.poll).",
)
```

and beside `set_trades_attention`:

```python
def set_sale_payouts_overdue(count: int) -> None:
    """Set how many card payouts wait past 48 h. Never raises."""
    try:
        SALE_PAYOUTS_OVERDUE.set(count)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed", metric="csmarket_sale_payouts_overdue", error=type(exc).__name__
        )
```

```python
# apps/api/src/csmarket/modules/sales/reconcile.py
"""The sales poll (spec 2026-10-08 §6): the fallback for the webhooks Skinslink never sends.

No webhook comes before ``hold``, so ``creating`` and ``offered`` sales are asked about every
:data:`OPEN_POLL_EVERY`; a ``hold`` sale every :data:`HOLD_POLL_EVERY`, in case its webhook
was lost. Each sale is checked in its own session (``status.check_sale``): one failure never
stops the tick. The same tick exports how many card payouts wait past :data:`OVERDUE_AFTER`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_sale_payouts_overdue
from csmarket.modules.sales.models import PayoutRequest, Sale
from csmarket.modules.sales.status import check_sale
from csmarket.modules.skinslink.api import DepositClient

log = get_logger("csmarket.sales.reconcile")

OPEN_POLL_EVERY = timedelta(seconds=60)
HOLD_POLL_EVERY = timedelta(minutes=30)
OVERDUE_AFTER = timedelta(hours=48)
#: Sales per tick.
BATCH = 50

SessionFactory = Callable[[], AsyncSession]


def _due_since(every: timedelta, at: datetime) -> ColumnElement[bool]:
    """Never polled, or last polled ``every`` ago or longer."""
    return or_(Sale.last_polled_at.is_(None), Sale.last_polled_at <= at - every)


async def _due(db: AsyncSession, at: datetime) -> list[str]:
    """Ids of the open sales due a poll, least recently polled first."""
    rows = await db.scalars(
        select(Sale.id)
        .where(
            or_(
                and_(Sale.status.in_(("creating", "offered")), _due_since(OPEN_POLL_EVERY, at)),
                and_(Sale.status == "hold", _due_since(HOLD_POLL_EVERY, at)),
            )
        )
        .order_by(Sale.last_polled_at.asc().nulls_first(), Sale.created_at)
        .limit(BATCH)
    )
    return [str(x) for x in rows.all()]


async def payouts_overdue(db: AsyncSession, *, at: datetime) -> int:
    """Card payouts ``to_pay`` for longer than :data:`OVERDUE_AFTER`."""
    count = await db.scalar(
        select(func.count())
        .select_from(PayoutRequest)
        .where(PayoutRequest.status == "to_pay", PayoutRequest.to_pay_at <= at - OVERDUE_AFTER)
    )
    return int(count or 0)


async def poll_sales(
    db_factory: SessionFactory, client: DepositClient, *, at: datetime | None = None
) -> int:
    """One tick: ask about every due open sale; export the overdue payouts.

    Returns:
        How many sales the tick asked about.
    """
    moment = at or now()
    async with db_factory() as db:
        due = await _due(db, moment)
        set_sale_payouts_overdue(await payouts_overdue(db, at=moment))
        await db.commit()
    for sale_id in due:
        try:
            async with db_factory() as db:
                await check_sale(db, client, sale_id=sale_id)
        except Exception as exc:  # noqa: BLE001 -- one sale must not stop the tick
            log.error("sales.poll_failed", error=type(exc).__name__)  # noqa: TRY400
    return len(due)


__all__ = [
    "BATCH",
    "HOLD_POLL_EVERY",
    "OPEN_POLL_EVERY",
    "OVERDUE_AFTER",
    "payouts_overdue",
    "poll_sales",
]
```

- [ ] **Step 6: The worker queue and the scheduler job**

`apps/worker/src/csmarket_worker/consumer.py`: import `from csmarket.modules.sales.api import SALES_CHANNEL, drain_sale_checks`; add

```python
async def _drain_sale_checks(db: AsyncSession) -> int:
    """Ask Skinslink about the sales its deposit webhook named (``sales.drain_sale_checks``)."""
    return await drain_sale_checks(db)
```

and a fourth entry at the end of `_queues()`'s tuple (its docstring gains "`sales`: one drainer — a sale check is a single cheap read."):

```python
        Queue(name="sales", channel=SALES_CHANNEL, drain=_drain_sale_checks, concurrency=1),
```

```python
# apps/scheduler/src/csmarket_scheduler/jobs/sales_poll.py
"""Every 60 s: ask Skinslink about open sales (``sales.reconcile.poll_sales``).

The fallback for the statuses Skinslink sends no webhook for (spec 2026-10-08 §6); the logic
lives in ``sales``. Skipped without a Skinslink key; runs with selling switched off too, so
open sales still settle. ``max_instances=1`` and ``coalesce=True``. A failure is logged by
type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.sales.api import poll_sales
from csmarket.modules.skinslink.api import deposit_client_for

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.sales_poll")

JOB_ID = "sales.poll"
INTERVAL_SECONDS = 60


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    if not settings.skinslink_api_key:
        return
    client = deposit_client_for(
        settings, timeout_seconds=settings.skinslink_request_timeout_seconds
    )
    try:
        looked = await poll_sales(get_session_factory(), client)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("sales.poll.failed", error=type(exc).__name__)
        return
    if looked:
        log.info("sales.poll.tick", sales=looked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 125 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(125),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
```

`apps/scheduler/src/csmarket_scheduler/main.py`: `sales_poll` joins the `jobs` import, and `sales_poll.register(scheduler)` goes right after `lisskins_balance.register(scheduler)`.

- [ ] **Step 7: The alerts**

```yaml
# infra/prometheus/alerts/sales.yml
groups:
  - name: sales
    rules:
      # The gauge comes from the scheduler's `sales.poll` job (every minute), so the selector
      # is pinned to job="scheduler": the API and the worker expose it but never set it.

      # A card payout payable for 48 h and still not paid: a seller waits for their money.
      # Spec 2026-10-08 §7.
      - alert: SalePayoutsOverdue
        expr: max(csmarket_sale_payouts_overdue{job="scheduler"}) > 0
        for: 5m
        labels: { severity: warn }
        annotations:
          summary: '{{ $value | printf "%.0f" }} card payout(s) payable for over 48 h'
          description: >
            Open «Выкуп» → «Заявки на выплату» → «К выплате» in the admin and pay them by
            hand, or reject one with a reason (its money then goes to the seller's balance).
          runbook: "https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/sales.md#overdue"
```

`infra/prometheus/alerts/api.yml`: in both `ApiHighLatency` (`handler!~`) and `ApiWaxpeerLatency` (`handler=~`), the regex becomes

```
".*(/skins/.*/listings|/trade-?link/check|/v1/orders|/admin/orders/[^/]+/refund|/v1/sell(/inventory)?)"
```

and the comment above `ApiHighLatency` gains: "Selling (ADR-0016) asks Skinslink on `GET /sell/inventory` (6 s) and `POST /sell` (`create-deposit`, 10 s); `/sell/config` and the sale reads do not match."

- [ ] **Step 8: Run the tests and the linters**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_webhook.py tests/integration/test_sales_reconcile.py tests/integration/test_skinslink_webhook.py -q && cd ../scheduler && uv run pytest tests/test_sales_poll.py tests/test_main.py -q && cd ../worker && uv run pytest tests/test_consumer.py -q && cd ../api && uv run ruff check src/csmarket/modules/sales src/csmarket/modules/skinslink src/csmarket/core/metrics.py tests/integration/test_sales_webhook.py tests/integration/test_sales_reconcile.py ../scheduler ../worker && uv run mypy src/csmarket/modules/sales src/csmarket/modules/skinslink ../scheduler/src ../worker/src`
Expected: PASS (the purchase webhook tests unchanged); clean.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/modules/skinslink/routes.py apps/api/src/csmarket/core/metrics.py apps/api/tests/integration/test_sales_webhook.py apps/api/tests/integration/test_sales_reconcile.py apps/worker apps/scheduler infra/prometheus/alerts
git commit -m "feat(api/sales): the deposit webhook queues a check; the worker drains it; a poll and an overdue alert" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The seller's reads — my sales, one sale, money on its way; sale lines in the balance history

**Files:**

- Modify: `apps/api/src/csmarket/modules/sales/views.py` (`list_sales`, `pending_uzs`), `apps/api/src/csmarket/modules/sales/schemas.py` (`SalesPage`, `PendingOut`), `apps/api/src/csmarket/modules/sales/routes.py` (three reads)
- Modify: `apps/api/src/csmarket/modules/wallet/entries.py` (`_SALES` in `_NUMBERED`), `apps/api/src/csmarket/modules/wallet/schemas.py` (`EntryOut.kind`), `apps/api/src/csmarket/modules/admin/users_schemas.py` (its entry `kind`)
- Test: `apps/api/tests/integration/test_sales_reads.py`

**Interfaces:**

- Consumes: `rows_of`, `sale_out`, `owned_sale`, `SaleRow` (Task 9); `credit_sale` (Task 7); `core.cursor`.
- Produces in `views.py`: `PAGE_SIZE = 20`, `list_sales(db, user_id: str, cursor: str | None) -> tuple[list[SaleRow], str | None]` (newest first; a sale Skinslink refused at once — `closed` without a `trade_id` — is left out), `pending_uzs(db, user_id: str) -> Decimal` (Σ `payout_uzs` of `hold` sales paid to the balance).
- Produces routes: `GET /api/v1/sales?cursor=` → `SalesPage(items: list[SaleOut], next_cursor: str | None)`; `GET /api/v1/sales/pending` → `PendingOut(pending_uzs: str)`; `GET /api/v1/sales/{number}` → `SaleOut` (404 for anyone else's, unknown or malformed).
- Produces: `EntryOut.kind` admits `sale_credit` and `payout_return`; their `reference_number` is the sale's `S…` number.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_sales_reads.py
"""The seller's sales: newest first, one by number, the sum on its way to the balance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.sales.views import list_sales
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_sale
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]


async def _me(db: AsyncSession, customer_headers: Headers) -> tuple[dict[str, str], User]:
    headers = await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return headers, user


async def test_my_sales_newest_first_without_the_ones_refused_at_once(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    old = await make_sale(db_session, user=me, created_at=now() - timedelta(hours=2))
    await make_sale(db_session, user=me, status="closed", trade_id=None, fail_reason="trade_banned")
    new = await make_sale(db_session, user=me, status="hold", trade_id=7)
    await make_sale(db_session)  # someone else's
    r = await integration_client.get("/api/v1/sales", headers=headers)
    assert r.status_code == 200
    assert [s["number"] for s in r.json()["items"]] == [new.number, old.number]
    assert r.json()["next_cursor"] is None


async def test_pages_of_twenty(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    for n in range(21):
        await make_sale(db_session, user=me, created_at=now() - timedelta(minutes=n))
    first = (await integration_client.get("/api/v1/sales", headers=headers)).json()
    assert len(first["items"]) == 20 and first["next_cursor"]
    rest = await integration_client.get(
        "/api/v1/sales", params={"cursor": first["next_cursor"]}, headers=headers
    )
    assert len(rest.json()["items"]) == 1 and rest.json()["next_cursor"] is None
    bad = await integration_client.get("/api/v1/sales", params={"cursor": "x"}, headers=headers)
    assert (bad.status_code, bad.json()["code"]) == (422, "cursor")


async def test_a_page_costs_the_same_queries_for_any_number_of_sales(
    db_session: AsyncSession,
) -> None:
    async def _queries(count: int) -> int:
        user = await make_user(db_session)
        for n in range(count):
            sale = await make_sale(
                db_session, user=user, payout_to="card" if n % 2 else "balance", status="payout"
            )
            if n % 2:
                await make_request(db_session, sale)
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_session.bind.sync_engine  # type: ignore[union-attr]
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            rows, _ = await list_sales(db_session, user.id, None)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert len(rows) == count
        return len(statements)

    assert await _queries(2) == await _queries(10) > 0


async def test_one_sale_by_number_and_nobody_elses(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    mine = await make_sale(db_session, user=me, payout_to="card", status="payout")
    await make_request(db_session, mine, status="to_pay")
    r = await integration_client.get(f"/api/v1/sales/{mine.number}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert (body["payout_status"], body["card"]["last4"], body["offer"]) == ("to_pay", "9015", None)
    other = await make_sale(db_session)
    for number in (other.number, "S0000000", "nope", mine.number.lower()):
        r = await integration_client.get(f"/api/v1/sales/{number}", headers=headers)
        assert r.status_code == 404, number


async def test_the_offer_shows_only_while_offered_and_the_money_date_while_held(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    offered = await make_sale(db_session, user=me, status="offered", bot_name="Bot #3")
    held = await make_sale(db_session, user=me, status="hold", hold_end_at=now() + timedelta(days=7))
    a = (await integration_client.get(f"/api/v1/sales/{offered.number}", headers=headers)).json()
    b = (await integration_client.get(f"/api/v1/sales/{held.number}", headers=headers)).json()
    assert a["offer"]["url"] == "https://steamcommunity.com/tradeoffer/6912345678/"
    assert (a["money_at"], b["offer"]) == (None, None)
    assert b["money_at"] is not None


async def test_pending_is_the_held_balance_sales(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    await make_sale(db_session, user=me, status="hold", payout_uzs=Decimal(158_300))
    await make_sale(db_session, user=me, status="hold", payout_uzs=Decimal(10_200))
    await make_sale(db_session, user=me, status="hold", payout_to="card")
    await make_sale(db_session, user=me, status="offered", payout_uzs=Decimal(99_900))
    await make_sale(db_session, status="hold")  # someone else's
    r = await integration_client.get("/api/v1/sales/pending", headers=headers)
    assert (r.status_code, r.json()) == (200, {"pending_uzs": "168500"})


async def test_a_sale_credit_shows_in_the_balance_history_with_its_number(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    sale = await make_sale(db_session, user=me, status="credited", payout_uzs=Decimal(158_300))
    await credit_sale(db_session, user_id=me.id, sale_id=sale.id, amount=Decimal(158_300))
    await db_session.commit()
    r = await integration_client.get("/api/v1/wallet/entries", headers=headers)
    [entry] = r.json()["items"]
    assert (entry["kind"], entry["amount_uzs"], entry["reference_number"]) == (
        "sale_credit",
        "+158300",
        sale.number,
    )


async def test_signed_out_is_401(integration_client: AsyncClient) -> None:
    for url in ("/api/v1/sales", "/api/v1/sales/pending", "/api/v1/sales/S0000000"):
        assert (await integration_client.get(url)).status_code == 401
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_reads.py -q`
Expected: FAIL — `ImportError: cannot import name 'list_sales'`.

- [ ] **Step 3: The reads**

Append to `sales/views.py` (imports: `from sqlalchemy import and_, func, not_, or_`, `from csmarket.core.cursor import decode_cursor, encode_cursor`):

```python
#: Sales per page of «Продажи».
PAGE_SIZE = 20


async def list_sales(
    db: AsyncSession, user_id: str, cursor: str | None, *, limit: int = PAGE_SIZE
) -> tuple[list[SaleRow], str | None]:
    """One newest-first page of ``user_id``'s sales and the cursor of the next page.

    A sale Skinslink refused at once (``closed`` with no deposit) is left out: the seller saw
    the refusal on the spot.

    Raises:
        ValidationError: ``cursor`` is not one this API issued (``code="cursor"``).
    """
    stmt = (
        select(Sale)
        .where(Sale.user_id == user_id, not_(and_(Sale.status == "closed", Sale.trade_id.is_(None))))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stamp, sale_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Sale.created_at < stamp, and_(Sale.created_at == stamp, Sale.id < sale_id))
        )
    found = list((await db.scalars(stmt)).all())
    page = found[:limit]
    more = len(found) > limit
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if more else None
    return await rows_of(db, page), next_cursor


async def pending_uzs(db: AsyncSession, user_id: str) -> Decimal:
    """«Ожидает зачисления»: the payouts of ``user_id``'s balance sales still in ``hold``."""
    total = await db.scalar(
        select(func.coalesce(func.sum(Sale.payout_uzs), 0)).where(
            Sale.user_id == user_id, Sale.status == "hold", Sale.payout_to == "balance"
        )
    )
    return Decimal(total or 0)
```

and `"PAGE_SIZE", "list_sales", "pending_uzs"` in its `__all__`.

Append to `sales/schemas.py`:

```python
class SalesPage(BaseModel):
    """My sales, newest first; ``next_cursor`` is ``null`` on the last page."""

    items: list[SaleOut]
    next_cursor: str | None


class PendingOut(BaseModel):
    """What my balance sales still in Steam's protection will pay, whole soʻm."""

    pending_uzs: str
```

Append to `sales/routes.py` (imports: `PendingOut`, `SalesPage`; `list_sales`, `pending_uzs`):

```python
@router.get("/sales", response_model=SalesPage, summary="My sales")
async def get_my_sales(user: Me, db: Db, cursor: str | None = None) -> SalesPage:
    """My sales, newest first, 20 a page."""
    rows, next_cursor = await list_sales(db, user.id, cursor)
    return SalesPage(items=[sale_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/sales/pending", response_model=PendingOut, summary="Money on its way to my balance")
async def get_pending(user: Me, db: Db) -> PendingOut:
    """The sum my sales to the balance will credit once Steam's protection ends."""
    return PendingOut(pending_uzs=wire_uzs(await pending_uzs(db, user.id)))


@router.get(
    "/sales/{number}",
    response_model=SaleOut,
    responses={404: {"description": "Not my sale"}},
    summary="One of my sales",
)
async def get_my_sale(number: str, user: Me, db: Db) -> SaleOut:
    """The owner's sale; anyone else's, an unknown or a malformed number is a 404."""
    return await _owned_out(db, user.id, number)
```

(`/sales/pending` is declared before `/sales/{number}`.)

- [ ] **Step 4: Sale lines in the balance history**

`wallet/entries.py`:

```python
#: ``sales``' sales, as far as an entry needs them (id → public ``S…`` number).
_SALES = table("sales", column("id", UUID(as_uuid=False)), column("number", String))
#: The ``reference_type`` whose public number a line shows, and the table holding it.
_NUMBERED = {"topup": _TOPUPS, "order": _ORDERS, "sale": _SALES}
```

(and the module docstring's line about numbers gains "…the sale's number for `sale_credit`/`payout_return`").

`wallet/schemas.py` and `admin/users_schemas.py`, the entry's kind:

```python
    kind: Literal[
        "topup",
        "topup_reversal",
        "admin_adjust",
        "purchase",
        "refund",
        "sale_credit",
        "payout_return",
    ]
```

(`wallet/schemas.py`'s `reference_number` comment gains "the sale's number for `sale_credit`/`payout_return`".)

- [ ] **Step 5: Run the tests, the linters, regenerate the API**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_reads.py tests/integration/test_wallet_routes.py tests/integration/test_admin_users.py -q && uv run ruff format src/csmarket/modules/sales src/csmarket/modules/wallet tests/integration/test_sales_reads.py && uv run ruff check src/csmarket/modules/sales src/csmarket/modules/wallet src/csmarket/modules/admin tests/integration/test_sales_reads.py && uv run mypy src/csmarket/modules/sales src/csmarket/modules/wallet src/csmarket/modules/admin && cd ../.. && make gen-api`
Expected: PASS; clean; the client gains the three reads and the two entry kinds.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/modules/wallet apps/api/src/csmarket/modules/admin/users_schemas.py apps/api/tests/integration/test_sales_reads.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/sales): my sales, one sale, the sum on its way; sale lines in the balance history" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The admin API — payout requests, sales, the settings editor, the dashboard tile

**Files:**

- Create: `apps/api/src/csmarket/modules/sales/admin_schemas.py`, `apps/api/src/csmarket/modules/sales/admin_sales.py`, `apps/api/src/csmarket/modules/sales/admin_payouts.py`, `apps/api/src/csmarket/modules/sales/admin_routes.py`
- Modify: `apps/api/src/csmarket/modules/sales/api.py` (`PayoutsSummary`, `payouts_summary`)
- Modify: `apps/api/src/csmarket/modules/admin/dashboard_schemas.py`, `apps/api/src/csmarket/modules/admin/dashboard_routes.py`
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `sales.admin_routes.router`)
- Test: `apps/api/tests/integration/test_sales_admin_payouts.py`, `apps/api/tests/integration/test_sales_admin_sales.py`, `apps/api/tests/integration/test_admin_dashboard.py` (append)

**Interfaces:**

- Consumes: `admin.api.record`, `remember`, `replayed`, `require_admin`, `required_key`; `reveal_number`, `masked` (Task 6); `request_of` (Task 7); `lock_sale` (Task 7); `credit_payout_return` (Task 7); `enqueue_sale_letter` (Task 5); `realtime.api.nudge_sale`; `read_sale_settings`, `save_sale_settings`, `settings_row` (Task 4); `sale_rate`, `SaleSettings`; `schemas.plain`, `SaleStatusOut`, `PayoutStatusOut`.
- Produces in `admin_schemas.py`: `AdminUserOut`, `PayoutRowOut`, `PayoutCountsOut`, `PayoutsPageOut`, `AdminSaleItemOut`, `AdminSaleRowOut`, `AdminSalesPageOut`, `AdminSaleOut`, `PayoutDetailOut`, `RevealIn(purpose: Literal["show", "copy"])`, `RevealOut(number: str)`, `PaidIn(note: str | None)`, `RejectIn(reason: str)`, `SaleSettingsOut(settings, updated_at, updated_by, rate_uzs)`.
- Produces in `admin_payouts.py`: `list_payouts(db, *, status: PayoutStatusOut, cursor: str | None, limit: int) -> PayoutsPageOut`, `payout_detail(db, request_id: str) -> PayoutDetailOut`, `reveal(db, *, request_id: str, admin_id: str, purpose: Literal["show", "copy"]) -> str`, `mark_paid(db, *, request_id: str, admin_id: str, note: str | None) -> PayoutRequest`, `reject(db, *, request_id: str, admin_id: str, reason: str) -> PayoutRequest`, `@dataclass PayoutsSummary(to_pay_count: int, to_pay_uzs: Decimal)`, `payouts_summary(db) -> PayoutsSummary`; 409 `payout_not_payable`.
- Produces in `admin_sales.py`: `list_sales_admin(db, *, status: SaleStatusOut | None, q: str | None, cursor: str | None, limit: int) -> AdminSalesPageOut`, `sale_admin_out(db, sale: Sale) -> AdminSaleOut`, `sale_by_number(db, number: str) -> AdminSaleOut` (404), `settings_view(db) -> SaleSettingsOut`, `save_settings(db, *, doc: SaleSettings, admin_id: str) -> None` (audited `sales.settings.save`).
- Produces routes (admin only, prefix `/api/v1/admin/sales`): `GET /payouts?status=to_pay&cursor=&limit=` → `PayoutsPageOut`; `GET /payouts/{id}` → `PayoutDetailOut`; `POST /payouts/{id}/reveal` (keyless, audited `sales.card.show` / `sales.card.copy`) → `RevealOut`; `POST /payouts/{id}/paid` (key; audited `sales.payout.paid`) → `PayoutDetailOut`; `POST /payouts/{id}/reject` (key; audited `sales.payout.reject`) → `PayoutDetailOut`; `GET /settings` → `SaleSettingsOut`; `PUT /settings` (key) → `SaleSettingsOut`; `GET ""?status=&q=&cursor=` → `AdminSalesPageOut`; `GET /{number}` → `AdminSaleOut`.
- Produces: `DashboardOut.payouts: PayoutsOut(to_pay_count: int, to_pay_uzs: str)`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_sales_admin_payouts.py
"""«Заявки на выплату»: the queue, a request's page, the audited reveal, paid and reject."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.sales.models import PayoutRequest
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.sales_factory import HUMO, make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales/payouts"


def _key(n: int) -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-payout-{n:06d}"}


async def _payable(db: AsyncSession) -> PayoutRequest:
    sale = await make_sale(
        db, status="payout", payout_to="card", payout_uzs=Decimal(147_400)
    )
    return await make_request(db, sale, status="to_pay")


async def _audit(db: AsyncSession) -> list[tuple[str, dict[str, object]]]:
    rows = await db.execute(
        select(AdminAuditLog.action, AdminAuditLog.payload).order_by(AdminAuditLog.created_at)
    )
    return [(a, p) for a, p in rows.all()]


async def test_the_queue_has_tabs_with_counts_and_masks_the_card(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    waiting = await make_sale(db_session, status="hold", payout_to="card")
    await make_request(db_session, waiting, status="waiting_hold")
    r = await integration_client.get(BASE, params={"status": "to_pay"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {"waiting_hold": 1, "to_pay": 1, "paid": 0, "rejected": 0, "canceled": 0}
    [row] = body["items"]
    assert (row["id"], row["card_masked"], row["card_type"], row["amount_uzs"]) == (
        request.id,
        "•••• 9015",
        "humo",
        "147400",
    )
    assert HUMO not in r.text


async def test_the_card_number_leaves_only_through_the_audited_reveal(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    page = await integration_client.get(f"{BASE}/{request.id}", headers=headers)
    assert page.status_code == 200 and HUMO not in page.text
    with capture_logs() as logs:
        shown = await integration_client.post(
            f"{BASE}/{request.id}/reveal", json={"purpose": "show"}, headers=headers
        )
        copied = await integration_client.post(
            f"{BASE}/{request.id}/reveal", json={"purpose": "copy"}, headers=headers
        )
        paid = await integration_client.post(
            f"{BASE}/{request.id}/paid", json={"note": "Click"}, headers={**headers, **_key(1)}
        )
    assert shown.json() == copied.json() == {"number": HUMO}
    assert paid.status_code == 200 and HUMO not in paid.text
    assert HUMO not in repr(logs)
    assert [a for a, _ in await _audit(db_session)] == [
        "sales.card.show",
        "sales.card.copy",
        "sales.payout.paid",
    ]
    assert HUMO not in repr(await _audit(db_session))
    replays = (await db_session.execute(text("SELECT response_body::text FROM idempotent_responses"))).scalars()
    assert all(HUMO not in body for body in replays)


async def test_paid_stamps_the_request_writes_a_letter_and_replays(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}/paid"
    first = await integration_client.post(url, json={"note": "Click #1"}, headers={**headers, **_key(2)})
    again = await integration_client.post(url, json={"note": "Click #1"}, headers={**headers, **_key(2)})
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert (first.json()["request"]["status"], first.json()["note"], first.json()["can_decide"]) == (
        "paid",
        "Click #1",
        False,
    )
    letter = await db_session.scalar(select(EmailOutbox).where(EmailOutbox.kind == "sale_paid"))
    assert letter is not None and letter.payload["to"] == "card" and letter.payload["last4"] == "9015"
    other_key = await integration_client.post(url, json={"note": "x"}, headers={**headers, **_key(3)})
    assert (other_key.status_code, other_key.json()["code"]) == (409, "payout_not_payable")


async def test_reject_credits_the_amount_before_the_fee_to_the_balance(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)  # items 155 200, fee 7 800, card 147 400
    r = await integration_client.post(
        f"{BASE}/{request.id}/reject", json={"reason": "Карта заблокирована"}, headers={**headers, **_key(4)}
    )
    assert r.status_code == 200, r.text
    assert (r.json()["request"]["status"], r.json()["reject_reason"]) == ("rejected", "Карта заблокирована")
    assert await user_balance(db_session, request.user_id) == Decimal(155_200)
    again = await integration_client.post(
        f"{BASE}/{request.id}/reject", json={"reason": "again"}, headers={**headers, **_key(5)}
    )
    assert (again.status_code, again.json()["code"]) == (409, "payout_not_payable")
    assert await user_balance(db_session, request.user_id) == Decimal(155_200)


async def test_a_request_still_waiting_for_its_money_cannot_be_paid_or_rejected(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(db_session, status="hold", payout_to="card")
    request = await make_request(db_session, sale, status="waiting_hold")
    for n, (action, body) in enumerate((("paid", {}), ("reject", {"reason": "x"}))):
        r = await integration_client.post(
            f"{BASE}/{request.id}/{action}", json=body, headers={**headers, **_key(10 + n)}
        )
        assert (r.status_code, r.json()["code"]) == (409, "payout_not_payable")
    assert await user_balance(db_session, sale.user_id) == 0


async def test_reject_needs_a_reason_and_writes_need_a_key(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    no_reason = await integration_client.post(
        f"{BASE}/{request.id}/reject", json={"reason": ""}, headers={**headers, **_key(6)}
    )
    no_key = await integration_client.post(f"{BASE}/{request.id}/paid", json={}, headers=headers)
    assert (no_reason.status_code, no_key.status_code) == (422, 422)


async def test_the_page_shows_the_breakdown_items_and_history(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    body = (await integration_client.get(f"{BASE}/{request.id}", headers=headers)).json()
    sale = body["sale"]
    assert (sale["items_uzs"], sale["fee_uzs"], sale["payout_uzs"]) == ("155200", "7800", "147400")
    assert [i["asset_id"] for i in sale["items"]] == ["100", "101"]
    assert [s["number"] for s in body["history_sales"]] == [sale["number"]]
    assert [p["id"] for p in body["history_payouts"]] == [request.id]
    assert body["can_decide"] is True


async def test_customers_are_403(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    request = await _payable(db_session)
    headers = await customer_headers()
    assert (await integration_client.get(BASE, headers=headers)).status_code == 403
    r = await integration_client.post(
        f"{BASE}/{request.id}/reveal", json={"purpose": "show"}, headers=headers
    )
    assert r.status_code == 403
```

```python
# apps/api/tests/integration/test_sales_admin_sales.py
"""«Продажи» and «Настройки выкупа»: the list, a sale's page, the audited settings save."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_sale
from tests.integration.sales_kit import add_rate

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales"
KEY = {"Idempotency-Key": "test-admin-sale-settings-01"}


async def test_the_list_filters_by_status_and_number(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    hold = await make_sale(db_session, status="hold")
    await make_sale(db_session, status="credited")
    r = await integration_client.get(BASE, params={"status": "hold"}, headers=headers)
    assert [s["number"] for s in r.json()["items"]] == [hold.number]
    r = await integration_client.get(BASE, params={"q": hold.number[:5].lower()}, headers=headers)
    assert [s["number"] for s in r.json()["items"]] == [hold.number]


async def test_a_sales_page_shows_skinslinks_amount_our_payout_and_margin(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(
        db_session, status="credited", amount_usd=Decimal("12.83"), trade_id=178
    )
    body = (await integration_client.get(f"{BASE}/{sale.number}", headers=headers)).json()
    assert (body["quoted_usd"], body["amount_usd"], body["margin_usd"], body["trade_id"]) == (
        "12.95",
        "12.83",
        "0.6735",
        178,
    )
    assert (await integration_client.get(f"{BASE}/S0000000", headers=headers)).status_code == 404


async def test_the_settings_save_is_audited_and_replayed(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    await add_rate(db_session)
    view = (await integration_client.get(f"{BASE}/settings", headers=headers)).json()
    assert view["settings"]["enabled"] is False and view["rate_uzs"] == "12650.5"
    doc = {**DEFAULT_SALE_SETTINGS.model_dump(mode="json"), "enabled": True, "card_min_uzs": 50_000}
    first = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    again = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    assert first.status_code == again.status_code == 200
    assert first.json()["settings"]["card_min_uzs"] == 50_000
    assert first.json()["updated_by"] is not None
    actions = (await db_session.scalars(select(AdminAuditLog.action))).all()
    assert list(actions) == ["sales.settings.save"]


async def test_a_bad_settings_document_is_422(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    doc = {**DEFAULT_SALE_SETTINGS.model_dump(mode="json"), "margin": [{"from_usd": "1", "percent": "5"}]}
    r = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    assert r.status_code == 422
```

Append to `apps/api/tests/integration/test_admin_dashboard.py`:

```python
async def test_the_dashboard_counts_the_payouts_to_pay(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    from tests.integration.sales_factory import make_request, make_sale

    for _ in range(2):
        sale = await make_sale(db_session, status="payout", payout_to="card")
        await make_request(db_session, sale, status="to_pay")
    r = await integration_client.get("/api/v1/admin/dashboard", headers=headers)
    assert r.json()["payouts"] == {"to_pay_count": 2, "to_pay_uzs": "310400"}
```

(`headers` is that file's admin-headers fixture.)

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_admin_payouts.py tests/integration/test_sales_admin_sales.py tests/integration/test_admin_dashboard.py -q`
Expected: FAIL — 404 on `/api/v1/admin/sales/payouts` and a `KeyError: 'payouts'`.

- [ ] **Step 3: The admin shapes**

```python
# apps/api/src/csmarket/modules/sales/admin_schemas.py
"""Admin wire shapes of ``sales`` (spec 2026-10-08 §7). Money as strings; a card by its last
four — the full number only in :class:`RevealOut`, which is never stored as a replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings
from csmarket.modules.sales.schemas import PayoutStatusOut, SaleStatusOut


class AdminUserOut(BaseModel):
    id: str
    display_name: str | None


class PayoutRowOut(BaseModel):
    """A payout request in the queue."""

    id: str
    sale_number: str
    user: AdminUserOut
    card_type: CardType
    #: ``•••• 9015``.
    card_masked: str
    amount_uzs: str
    fee_uzs: str
    status: PayoutStatusOut
    #: Since when it is payable.
    to_pay_at: datetime | None
    paid_at: datetime | None
    created_at: datetime


class PayoutCountsOut(BaseModel):
    """Requests per status (the tabs)."""

    waiting_hold: int = 0
    to_pay: int = 0
    paid: int = 0
    rejected: int = 0
    canceled: int = 0


class PayoutsPageOut(BaseModel):
    items: list[PayoutRowOut]
    counts: PayoutCountsOut
    next_cursor: str | None


class AdminSaleItemOut(BaseModel):
    asset_id: str
    name: str
    #: Skinslink's price.
    price_usd: str
    #: Ours.
    price_uzs: str


class AdminSaleRowOut(BaseModel):
    number: str
    status: SaleStatusOut
    user: AdminUserOut
    payout_to: PayoutTo
    quoted_usd: str
    payout_uzs: str
    margin_usd: str
    attention_reason: str | None
    created_at: datetime


class AdminSalesPageOut(BaseModel):
    items: list[AdminSaleRowOut]
    next_cursor: str | None


class AdminSaleOut(BaseModel):
    """A sale's page: Skinslink's side, our payout, our margin."""

    number: str
    status: SaleStatusOut
    user: AdminUserOut
    payout_to: PayoutTo
    card_type: CardType | None
    card_masked: str | None
    quoted_usd: str
    amount_usd: str | None
    items_uzs: str
    bonus_uzs: str
    fee_uzs: str
    payout_uzs: str
    rate: str
    margin_usd: str
    trade_id: int | None
    trade_offer_id: str | None
    bot_name: str | None
    offer_expiry_at: datetime | None
    hold_end_at: datetime | None
    fail_reason: str | None
    attention_reason: str | None
    credited_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[AdminSaleItemOut]
    payout: PayoutRowOut | None


class PayoutDetailOut(BaseModel):
    """A request's page: the request, its sale, the seller's history, what may be done."""

    request: PayoutRowOut
    note: str | None
    reject_reason: str | None
    decided_by: AdminUserOut | None
    sale: AdminSaleOut
    history_sales: list[AdminSaleRowOut]
    history_payouts: list[PayoutRowOut]
    #: «Выплачено» and «Отклонить» are possible (the request is ``to_pay``).
    can_decide: bool


class RevealIn(BaseModel):
    purpose: Literal["show", "copy"]


class RevealOut(BaseModel):
    #: The full card number. PII: shown to the admin, never stored or logged.
    number: str


class PaidIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SaleSettingsOut(BaseModel):
    settings: SaleSettings
    updated_at: datetime | None
    updated_by: AdminUserOut | None
    #: The CBU rate now (no uplift), before ``rate_cut_pct``; ``null`` without one.
    rate_uzs: str | None
```

- [ ] **Step 4: `admin_sales.py`**

```python
# apps/api/src/csmarket/modules/sales/admin_sales.py
"""The admin's «Продажи» and «Настройки выкупа» (spec 2026-10-08 §7).

A page of rows loads its users in one query. A settings save affects new sales only (each
sale keeps its own numbers) and is audited ``sales.settings.save`` in the caller's
transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import NotFoundError
from csmarket.core.money import wire_uzs
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import record
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.admin_schemas import (
    AdminSaleItemOut,
    AdminSaleOut,
    AdminSaleRowOut,
    AdminSalesPageOut,
    AdminUserOut,
    PayoutRowOut,
    SaleSettingsOut,
)
from csmarket.modules.sales.cards import masked
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale, SaleItem
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.schemas import SaleStatusOut, plain
from csmarket.modules.sales.settings_store import (
    read_sale_settings,
    save_sale_settings,
    settings_row,
)
from csmarket.modules.users.api import User


async def users_by_id(db: AsyncSession, ids: Iterable[str]) -> dict[str, AdminUserOut]:
    """``id → AdminUserOut`` for ``ids``, one query."""
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
    return {uid: AdminUserOut(id=uid, display_name=name) for uid, name in rows.all()}


def _user(users: dict[str, AdminUserOut], uid: str) -> AdminUserOut:
    return users.get(uid) or AdminUserOut(id=uid, display_name=None)


def payout_row(
    request: PayoutRequest, *, number: str, card: PayoutCard, user: AdminUserOut
) -> PayoutRowOut:
    """A request as the queue shows it."""
    return PayoutRowOut(
        id=request.id,
        sale_number=number,
        user=user,
        card_type=card.type,  # type: ignore[arg-type]  # the column's check
        card_masked=masked(card.last4),
        amount_uzs=wire_uzs(request.amount_uzs),
        fee_uzs=wire_uzs(request.fee_uzs),
        status=request.status,  # type: ignore[arg-type]
        to_pay_at=request.to_pay_at,
        paid_at=request.paid_at,
        created_at=request.created_at,
    )


def sale_row(sale: Sale, user: AdminUserOut) -> AdminSaleRowOut:
    """A sale as the list shows it."""
    return AdminSaleRowOut(
        number=sale.number,
        status=sale.status,  # type: ignore[arg-type]
        user=user,
        payout_to=sale.payout_to,  # type: ignore[arg-type]
        quoted_usd=plain(sale.quoted_usd),
        payout_uzs=wire_uzs(sale.payout_uzs),
        margin_usd=plain(sale.margin_usd),
        attention_reason=sale.attention_reason,
        created_at=sale.created_at,
    )


async def sale_admin_out(db: AsyncSession, sale: Sale) -> AdminSaleOut:
    """A sale's full page."""
    items = (
        await db.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.asset_id)
        )
    ).all()
    card = await db.get(PayoutCard, sale.payout_card_id) if sale.payout_card_id else None
    request = await db.scalar(select(PayoutRequest).where(PayoutRequest.sale_id == sale.id))
    users = await users_by_id(db, [sale.user_id])
    user = _user(users, sale.user_id)
    to_card = sale.payout_to == "card"
    zero = Decimal(0)
    return AdminSaleOut(
        number=sale.number,
        status=sale.status,  # type: ignore[arg-type]
        user=user,
        payout_to=sale.payout_to,  # type: ignore[arg-type]
        card_type=card.type if card else None,  # type: ignore[arg-type]
        card_masked=masked(card.last4) if card else None,
        quoted_usd=plain(sale.quoted_usd),
        amount_usd=plain(sale.amount_usd) if sale.amount_usd is not None else None,
        items_uzs=wire_uzs(sale.items_uzs),
        bonus_uzs=wire_uzs(zero if to_card else sale.payout_uzs - sale.items_uzs),
        fee_uzs=wire_uzs(sale.items_uzs - sale.payout_uzs if to_card else zero),
        payout_uzs=wire_uzs(sale.payout_uzs),
        rate=plain(sale.rate),
        margin_usd=plain(sale.margin_usd),
        trade_id=sale.trade_id,
        trade_offer_id=sale.trade_offer_id,
        bot_name=sale.bot_name,
        offer_expiry_at=sale.offer_expiry_at,
        hold_end_at=sale.hold_end_at,
        fail_reason=sale.fail_reason,
        attention_reason=sale.attention_reason,
        credited_at=sale.credited_at,
        created_at=sale.created_at,
        updated_at=sale.updated_at,
        items=[
            AdminSaleItemOut(
                asset_id=i.asset_id,
                name=i.name,
                price_usd=plain(i.price_usd),
                price_uzs=wire_uzs(i.price_uzs),
            )
            for i in items
        ],
        payout=payout_row(request, number=sale.number, card=card, user=user)
        if request is not None and card is not None
        else None,
    )


async def sale_by_number(db: AsyncSession, number: str) -> AdminSaleOut:
    """Sale ``number``'s page.

    Raises:
        NotFoundError: Unknown.
    """
    sale = await db.scalar(
        select(Sale).where(Sale.number == number).execution_options(populate_existing=True)
    )
    if sale is None:
        raise NotFoundError("sale not found")
    return await sale_admin_out(db, sale)


async def list_sales_admin(
    db: AsyncSession,
    *,
    status: SaleStatusOut | None,
    q: str | None,
    cursor: str | None,
    limit: int,
) -> AdminSalesPageOut:
    """Sales newest first; ``q`` is a number prefix in any case."""
    stmt = select(Sale).order_by(Sale.created_at.desc(), Sale.id.desc()).limit(limit + 1)
    if status is not None:
        stmt = stmt.where(Sale.status == status)
    if q:
        stmt = stmt.where(Sale.number.startswith(q.strip().upper(), autoescape=True))
    if cursor is not None:
        stamp, sale_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Sale.created_at < stamp, and_(Sale.created_at == stamp, Sale.id < sale_id))
        )
    found = list((await db.scalars(stmt)).all())
    page = found[:limit]
    users = await users_by_id(db, (s.user_id for s in page))
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(found) > limit else None
    return AdminSalesPageOut(
        items=[sale_row(s, _user(users, s.user_id)) for s in page], next_cursor=next_cursor
    )


async def settings_view(db: AsyncSession) -> SaleSettingsOut:
    """The saved document, who saved it and when, and the CBU rate now."""
    row = await settings_row(db)
    users = await users_by_id(db, [row.updated_by] if row and row.updated_by else [])
    fx = await current_usd_uzs(
        db, get_redis(), max_age_days=get_settings().fx_max_age_days, uplift_pct=Decimal(0)
    )
    return SaleSettingsOut(
        settings=await read_sale_settings(db),
        updated_at=row.updated_at if row else None,
        updated_by=_user(users, row.updated_by) if row and row.updated_by else None,
        rate_uzs=plain(fx.rate) if fx is not None else None,
    )


async def save_settings(db: AsyncSession, *, doc: SaleSettings, admin_id: str) -> None:
    """Replace the document; audited ``sales.settings.save``. Flushes, never commits."""
    await save_sale_settings(db, settings=doc, admin_id=admin_id)
    await record(
        db,
        actor_id=admin_id,
        action="sales.settings.save",
        target_type="sale_settings",
        target_id="1",
        payload={"enabled": doc.enabled, "card_min_uzs": doc.card_min_uzs},
    )


__all__ = [
    "list_sales_admin",
    "payout_row",
    "sale_admin_out",
    "sale_by_number",
    "sale_row",
    "save_settings",
    "settings_view",
    "users_by_id",
]
```

- [ ] **Step 5: `admin_payouts.py`**

```python
# apps/api/src/csmarket/modules/sales/admin_payouts.py
"""The admin's card payouts (spec 2026-10-08 §7): the queue, a request's page, reveal, paid,
reject, and the dashboard's «К выплате».

Writes lock the sale, then its request (the order :mod:`.status` takes), re-check under the
locks and flush; the route writes the audit row and the replay and commits. Only a ``to_pay``
request may be decided (409 ``payout_not_payable``): before ``completed`` no money is ours to
give. «Отклонить» credits the balance with the amount before the card fee
(``credit_payout_return``, keyed by the request). The full number leaves only through
:func:`reveal`, audited each time; it is never part of a page or a replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.admin.api import record
from csmarket.modules.realtime.api import nudge_sale
from csmarket.modules.sales.admin_sales import (
    payout_row,
    sale_admin_out,
    sale_row,
    users_by_id,
)
from csmarket.modules.sales.admin_schemas import (
    AdminUserOut,
    PayoutCountsOut,
    PayoutDetailOut,
    PayoutRowOut,
    PayoutsPageOut,
)
from csmarket.modules.sales.cards import reveal_number
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale
from csmarket.modules.sales.payouts import request_of
from csmarket.modules.sales.schemas import PayoutStatusOut
from csmarket.modules.sales.status import lock_sale
from csmarket.modules.wallet.api import credit_payout_return

log = get_logger("csmarket.sales.admin")

#: How many of the seller's sales and payouts a request's page shows.
HISTORY = 20


def _not_payable() -> ConflictError:
    return ConflictError("this payout cannot be decided now", code="payout_not_payable")


def _who(users: dict[str, AdminUserOut], uid: str) -> AdminUserOut:
    """The user row of ``uid`` (a bare id if the users table no longer names it)."""
    return users.get(uid) or AdminUserOut(id=uid, display_name=None)


async def _rows(db: AsyncSession, requests: list[PayoutRequest]) -> list[PayoutRowOut]:
    """Queue rows for ``requests``: sales, cards and users in one query each."""
    if not requests:
        return []
    numbers = dict(
        (
            await db.execute(
                select(Sale.id, Sale.number).where(Sale.id.in_({r.sale_id for r in requests}))
            )
        ).all()
    )
    cards = {
        c.id: c
        for c in await db.scalars(
            select(PayoutCard).where(PayoutCard.id.in_({r.card_id for r in requests}))
        )
    }
    users = await users_by_id(db, (r.user_id for r in requests))
    return [
        payout_row(
            r,
            number=numbers[r.sale_id],
            card=cards[r.card_id],
            user=_who(users, r.user_id),
        )
        for r in requests
    ]


async def list_payouts(
    db: AsyncSession, *, status: PayoutStatusOut, cursor: str | None, limit: int
) -> PayoutsPageOut:
    """One status tab, newest first, and the count of every tab."""
    stmt = (
        select(PayoutRequest)
        .where(PayoutRequest.status == status)
        .order_by(PayoutRequest.created_at.desc(), PayoutRequest.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stamp, rid = decode_cursor(cursor)
        stmt = stmt.where(
            (PayoutRequest.created_at < stamp)
            | ((PayoutRequest.created_at == stamp) & (PayoutRequest.id < rid))
        )
    found = list((await db.scalars(stmt)).all())
    page = found[:limit]
    counts = dict(
        (
            await db.execute(
                select(PayoutRequest.status, func.count()).group_by(PayoutRequest.status)
            )
        ).all()
    )
    return PayoutsPageOut(
        items=await _rows(db, page),
        counts=PayoutCountsOut(**{k: int(v) for k, v in counts.items()}),
        next_cursor=encode_cursor(page[-1].created_at, page[-1].id) if len(found) > limit else None,
    )


async def _request(db: AsyncSession, request_id: str) -> PayoutRequest:
    request = await db.get(PayoutRequest, request_id, populate_existing=True)
    if request is None:
        raise NotFoundError("payout request not found")
    return request


async def payout_detail(db: AsyncSession, request_id: str) -> PayoutDetailOut:
    """A request's page.

    Raises:
        NotFoundError: Unknown.
    """
    request = await _request(db, request_id)
    sale = await db.get(Sale, request.sale_id, populate_existing=True)
    if sale is None:  # the foreign key forbids it
        raise NotFoundError("sale not found")
    [row] = await _rows(db, [request])
    sales = (
        await db.scalars(
            select(Sale)
            .where(Sale.user_id == request.user_id)
            .order_by(Sale.created_at.desc())
            .limit(HISTORY)
        )
    ).all()
    payouts = (
        await db.scalars(
            select(PayoutRequest)
            .where(PayoutRequest.user_id == request.user_id)
            .order_by(PayoutRequest.created_at.desc())
            .limit(HISTORY)
        )
    ).all()
    users = await users_by_id(
        db, [request.user_id, *([request.paid_by] if request.paid_by else [])]
    )
    return PayoutDetailOut(
        request=row,
        note=request.note,
        reject_reason=request.reject_reason,
        decided_by=_who(users, request.paid_by) if request.paid_by else None,
        sale=await sale_admin_out(db, sale),
        history_sales=[sale_row(s, _who(users, s.user_id)) for s in sales],
        history_payouts=await _rows(db, list(payouts)),
        can_decide=request.status == "to_pay",
    )


async def reveal(
    db: AsyncSession, *, request_id: str, admin_id: str, purpose: Literal["show", "copy"]
) -> str:
    """The request's full card number, audited ``sales.card.<purpose>``; flushes.

    PII: the caller returns it to the admin and nowhere else.
    """
    request = await _request(db, request_id)
    card = await db.get(PayoutCard, request.card_id)
    if card is None:  # the foreign key forbids it
        raise NotFoundError("card not found")
    await record(
        db,
        actor_id=admin_id,
        action=f"sales.card.{purpose}",
        target_type="payout_request",
        target_id=request.id,
        payload={"last4": card.last4},
    )
    return reveal_number(card)


async def _locked(db: AsyncSession, request_id: str) -> tuple[Sale, PayoutRequest]:
    """The request's sale, then the request, ``FOR UPDATE``; a ``to_pay`` request only."""
    first = await _request(db, request_id)
    sale = await lock_sale(db, first.sale_id)
    request = await request_of(db, first.sale_id, lock=True)
    if sale is None or request is None:
        raise NotFoundError("payout request not found")
    if request.status != "to_pay":
        raise _not_payable()
    return sale, request


async def mark_paid(
    db: AsyncSession, *, request_id: str, admin_id: str, note: str | None
) -> PayoutRequest:
    """«Выплачено»: the admin paid the card by hand. Flushes.

    Raises:
        ConflictError: ``payout_not_payable``.
    """
    sale, request = await _locked(db, request_id)
    request.status, request.paid_by, request.paid_at, request.note = "paid", admin_id, now(), note
    card = await db.get(PayoutCard, request.card_id)
    await enqueue_sale_letter(
        db,
        sale,
        "sale_paid",
        amount_uzs=request.amount_uzs,
        to="card",
        last4=card.last4 if card else None,
    )
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.paid", number=sale.number, amount_uzs=str(request.amount_uzs))
    return request


async def reject(
    db: AsyncSession, *, request_id: str, admin_id: str, reason: str
) -> PayoutRequest:
    """«Отклонить»: the amount before the card fee goes to the seller's balance. Flushes.

    Raises:
        ConflictError: ``payout_not_payable``.
    """
    sale, request = await _locked(db, request_id)
    amount = request.amount_uzs + request.fee_uzs
    request.status, request.paid_by = "rejected", admin_id
    request.rejected_at, request.reject_reason = now(), reason
    await credit_payout_return(
        db,
        user_id=sale.user_id,
        sale_id=sale.id,
        request_id=request.id,
        amount=amount,
        actor=f"admin:{admin_id}",
    )
    await enqueue_sale_letter(db, sale, "sale_paid", amount_uzs=amount, to="balance")
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.rejected", number=sale.number, amount_uzs=str(amount))
    return request


@dataclass(frozen=True)
class PayoutsSummary:
    """The dashboard's «К выплате»."""

    to_pay_count: int
    to_pay_uzs: Decimal


async def payouts_summary(db: AsyncSession) -> PayoutsSummary:
    """How many card payouts are payable now, and their sum."""
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(PayoutRequest.amount_uzs), 0)).where(
                PayoutRequest.status == "to_pay"
            )
        )
    ).one()
    return PayoutsSummary(to_pay_count=int(count), to_pay_uzs=Decimal(total))


__all__ = [
    "PayoutsSummary",
    "list_payouts",
    "mark_paid",
    "payout_detail",
    "payouts_summary",
    "reject",
    "reveal",
]
```

- [ ] **Step 6: The admin routes, the dashboard tile, the mounts**

```python
# apps/api/src/csmarket/modules/sales/admin_routes.py
"""``/api/v1/admin/sales*`` — «Выкуп»: payout requests, sales, the settings (spec §7).

Admin only. Every write requires an ``Idempotency-Key`` (16..160): replay lookup → the change
(:mod:`.admin_payouts` / :mod:`.admin_sales`) → audit → replay row → commit; the same key on
another body is 409 ``idempotency_mismatch``. The reveal is keyless on purpose: it changes
nothing but the audit trail, each reveal is its own audit row, and a replay would have to
store the card number.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.sales.admin_payouts import (
    list_payouts,
    mark_paid,
    payout_detail,
    reject,
    reveal,
)
from csmarket.modules.sales.admin_sales import (
    list_sales_admin,
    sale_by_number,
    save_settings,
    settings_view,
)
from csmarket.modules.sales.admin_schemas import (
    AdminSaleOut,
    AdminSalesPageOut,
    PaidIn,
    PayoutDetailOut,
    PayoutsPageOut,
    RejectIn,
    RevealIn,
    RevealOut,
    SaleSettingsOut,
)
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.schemas import PayoutStatusOut, SaleStatusOut
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/sales", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


async def _finish(db: AsyncSession, rid: str, *, scope: str, key: str, request: dict[str, object]) -> PayoutDetailOut:
    detail = await payout_detail(db, rid)
    await remember(db, scope=scope, key=key, request=request, response=detail.model_dump(mode="json"))
    await db.commit()
    return detail


@router.get("/payouts", response_model=PayoutsPageOut, summary="Card payout requests")
async def get_payouts(
    db: Db,
    status: PayoutStatusOut = "to_pay",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PayoutsPageOut:
    """One status tab (``to_pay`` by default), newest first, with every tab's count."""
    return await list_payouts(db, status=status, cursor=cursor, limit=limit)


@router.get("/payouts/{request_id}", response_model=PayoutDetailOut, summary="A payout request")
async def get_payout(request_id: uuid.UUID, db: Db) -> PayoutDetailOut:
    """The request, its sale, the seller's history; the card masked."""
    return await payout_detail(db, str(request_id))


@router.post("/payouts/{request_id}/reveal", response_model=RevealOut, summary="The card number")
async def post_reveal(request_id: uuid.UUID, body: RevealIn, admin: Admin, db: Db) -> RevealOut:
    """The full card number to pay by hand; audited ``sales.card.show`` / ``sales.card.copy``.

    Keyless on purpose: it changes nothing but the audit trail, every reveal is its own audit
    row, and storing a replay would store the number.
    """
    number = await reveal(db, request_id=str(request_id), admin_id=admin.id, purpose=body.purpose)
    await db.commit()
    return RevealOut(number=number)


@router.post(
    "/payouts/{request_id}/paid",
    response_model=PayoutDetailOut,
    responses={409: {"description": "`payout_not_payable` or `idempotency_mismatch`"}},
    summary="Mark a payout paid",
)
async def post_paid(
    request_id: uuid.UUID, body: PaidIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Выплачено» (an optional note); the seller gets a letter."""
    rid, scope = str(request_id), "admin.sales.payout.paid"
    request = {"id": rid, "note": body.note}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done = await mark_paid(db, request_id=rid, admin_id=admin.id, note=body.note)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.paid",
        target_type="payout_request",
        target_id=rid,
        payload={"amount_uzs": int(done.amount_uzs)},
    )
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/payouts/{request_id}/reject",
    response_model=PayoutDetailOut,
    responses={409: {"description": "`payout_not_payable` or `idempotency_mismatch`"}},
    summary="Reject a payout to the balance",
)
async def post_reject(
    request_id: uuid.UUID, body: RejectIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Отклонить» (a reason is required): the amount before the card fee goes to the balance."""
    rid, scope = str(request_id), "admin.sales.payout.reject"
    request = {"id": rid, "reason": body.reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done = await reject(db, request_id=rid, admin_id=admin.id, reason=body.reason)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.reject",
        target_type="payout_request",
        target_id=rid,
        payload={"amount_uzs": int(done.amount_uzs + done.fee_uzs)},
    )
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.get("/settings", response_model=SaleSettingsOut, summary="The sale settings")
async def get_sale_settings(db: Db) -> SaleSettingsOut:
    """The document, who saved it and when, and the CBU rate now."""
    return await settings_view(db)


@router.put("/settings", response_model=SaleSettingsOut, summary="Save the sale settings")
async def put_sale_settings(body: SaleSettings, admin: Admin, db: Db, key: Key) -> SaleSettingsOut:
    """Replace the document; new sales use it, existing ones keep their numbers."""
    scope, request = "admin.sales.settings", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return SaleSettingsOut.model_validate(hit)
    await save_settings(db, doc=body, admin_id=admin.id)
    out = await settings_view(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("", response_model=AdminSalesPageOut, summary="Sales")
async def get_sales(
    db: Db,
    status: SaleStatusOut | None = None,
    q: Annotated[str | None, Query(max_length=8)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminSalesPageOut:
    """Newest first; ``q`` is a number prefix in any case."""
    return await list_sales_admin(db, status=status, q=q, cursor=cursor, limit=limit)


@router.get(
    "/{number}",
    response_model=AdminSaleOut,
    responses={404: {"description": "No such sale"}},
    summary="A sale",
)
async def get_sale(number: str, db: Db) -> AdminSaleOut:
    """Statuses, Skinslink's amount, our payout and margin, the items, the payout request."""
    return await sale_by_number(db, number)


__all__ = ["router"]
```

(`/settings` and `/payouts…` are declared before `/{number}`.)

`sales/api.py`: add `from csmarket.modules.sales.admin_payouts import PayoutsSummary, payouts_summary` and both names to `__all__`.

`admin/dashboard_schemas.py`:

```python
class PayoutsOut(BaseModel):
    """«К выплате»: card payouts payable now (spec 2026-10-08)."""

    to_pay_count: int
    to_pay_uzs: str
```

`DashboardOut` gains the field `payouts: PayoutsOut`; `of` becomes `def of(cls, d: Dashboard, payouts: PayoutsSummary) -> DashboardOut:` (import `PayoutsSummary` from `csmarket.modules.sales.api`) and its `cls(...)` call gains `payouts=PayoutsOut(to_pay_count=payouts.to_pay_count, to_pay_uzs=_money(payouts.to_pay_uzs)),`.

`admin/dashboard_routes.py`: import `payouts_summary` from `csmarket.modules.sales.api`; the return becomes

```python
    summary = await dashboard_summary(db, get_redis(), days=window, at=now())
    return DashboardOut.of(summary, await payouts_summary(db))
```

`api/v1/router.py`: `from csmarket.modules.sales.admin_routes import router as sales_admin_router` and `router.include_router(sales_admin_router)` beside the other admin routers.

- [ ] **Step 7: Run the tests, the linters, regenerate the API**

Run: `cd apps/api && uv run pytest tests/integration/test_sales_admin_payouts.py tests/integration/test_sales_admin_sales.py tests/integration/test_admin_dashboard.py tests/integration/test_admin_gate.py -q && uv run ruff format src/csmarket/modules/sales src/csmarket/modules/admin tests/integration/test_sales_admin_payouts.py tests/integration/test_sales_admin_sales.py && uv run ruff check src/csmarket/modules/sales src/csmarket/modules/admin src/csmarket/api tests/integration/test_sales_admin_payouts.py tests/integration/test_sales_admin_sales.py && uv run mypy src/csmarket/modules/sales src/csmarket/modules/admin && cd ../.. && make gen-api`
Expected: PASS; clean; the client gains `/admin/sales/*` and `payouts` on the dashboard.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/csmarket/modules/sales apps/api/src/csmarket/modules/admin apps/api/src/csmarket/api/v1/router.py apps/api/tests/integration/test_sales_admin_payouts.py apps/api/tests/integration/test_sales_admin_sales.py apps/api/tests/integration/test_admin_dashboard.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/sales): admin payout queue, audited card reveal, paid and reject, sales, settings, dashboard tile" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Storefront `/sell` — the real inventory, the payout choice, «Продать»

**Files:**

- Rewrite: `apps/web/src/lib/sell.ts`, `apps/web/src/lib/sell.test.ts`
- Create: `apps/web/src/lib/sales.ts` (the sale and card shapes, the cards calls)
- Delete: `apps/web/src/lib/sell-demo.ts`, `apps/web/src/lib/sell-demo.test.ts`
- Modify: `apps/web/src/lib/paths.ts` (`salePath`, `CARDS`)
- Rewrite: `apps/web/src/app/[locale]/sell/page.tsx`, `apps/web/src/app/[locale]/sell/page.test.tsx`
- Rewrite: `apps/web/src/components/sell/SellView.tsx`, `SellCart.tsx`, `PayoutPicker.tsx`, `SellItemCard.tsx`, `SellView.test.tsx`; modify `SellToolbar.tsx` (the refresh button works)
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (the `sell` section)

**Interfaces:**

- Consumes: `GET /api/v1/sell/config`, `GET /api/v1/sell/inventory`, `POST /api/v1/sell`, `GET /api/v1/payout-cards` (Tasks 6, 8, 9); `server-api.apiGet`; `session` (`@/lib/api`); `useAuth`; `TradeLinkForm`; `useRouter` from `@/i18n/navigation`.
- Produces in `lib/sell.ts`: `CardType`, `CARD_TYPES`, `SellConfig`, `SellItem`, `Inventory`, `Payout = {to:"balance"} | {to:"saved"; cardId; type} | {to:"new"; type; digits}`, `SellSummary`, `sellSummary(prices, payout, config)`, `payoutCardType(p)`, `cardDigits`, `formatCard`, `luhnOk`, `cardFits(type, digits)`, `nameParts(name) -> {weapon, skin, stattrak}`, `SELL_CONFIG_KEY`, `INVENTORY_KEY`, `getSellConfig()`, `getInventory(refresh?)`, `SellBody`, `sellBody(assetIds, payout, expected)`, `mintSellKey()`, `createSale(body, key) -> Promise<SaleOut>`, `SellErrorCode`, `SellError(code, reason)`, `sellError(err) -> SellError | null`.
- Produces in `lib/sales.ts`: `SaleStatus`, `PayoutStatus`, `SaleOut` (mirrors the API's `SaleOut`), `SavedCard`, `CARDS_KEY`, `listCards()`, `deleteCard(id, key)`, `mintCardKey()`.
- Produces in `lib/paths.ts`: `salePath(number) -> "/account/sales/{number}"`, `CARDS = "/account/cards"`.

- [ ] **Step 1: Write the failing tests**

```ts
// apps/web/src/lib/sell.test.ts
import { describe, expect, it } from "vitest";

import {
  cardDigits,
  cardFits,
  formatCard,
  luhnOk,
  nameParts,
  sellBody,
  sellSummary,
  type SellConfig,
} from "./sell";

const CONFIG: SellConfig = {
  enabled: true,
  balance_bonus_pct: "2",
  card_fee_pct: { uzcard: "5", humo: "5", uzum_visa: "1.5" },
  card_min_uzs: "30000",
  min_sum_uzs: "11300",
  max_cards: 3,
};

describe("sellSummary", () => {
  it("adds the balance bonus and rounds down to 100, like the API", () => {
    expect(sellSummary([149_600, 5_600], { to: "balance" }, CONFIG)).toEqual({
      items: 155_200,
      bonus: 3_100,
      fee: 0,
      payout: 158_300,
    });
  });

  it("takes the card type's fee, rounded down to 100", () => {
    const saved = { to: "saved", cardId: "c", type: "humo" } as const;
    expect(sellSummary([149_600, 5_600], saved, CONFIG)).toEqual({
      items: 155_200,
      bonus: 0,
      fee: 7_800,
      payout: 147_400,
    });
    const visa = { to: "new", type: "uzum_visa", digits: "" } as const;
    expect(sellSummary([155_200], visa, CONFIG).payout).toBe(152_800); // 152 872 → 152 800
  });
});

describe("cards", () => {
  it("keeps 16 digits and groups them by four", () => {
    expect(cardDigits("9860 1234-5678 90151234")).toBe("9860123456789015");
    expect(formatCard("98601234")).toBe("9860 1234");
  });

  it("checks the type's prefix and Luhn", () => {
    expect(luhnOk("9860123456789015")).toBe(true);
    expect(luhnOk("9860123456789016")).toBe(false);
    expect(cardFits("humo", "9860123456789015")).toBe(true);
    expect(cardFits("uzcard", "9860123456789015")).toBe(false);
    expect(cardFits("uzum_visa", "4000000000000002")).toBe(true);
    expect(cardFits("humo", "986012345678901")).toBe(false);
  });
});

describe("nameParts", () => {
  it("splits a market name into weapon and skin", () => {
    expect(nameParts("StatTrak™ AK-47 | Redline (Field-Tested)")).toEqual({
      weapon: "AK-47",
      skin: "Redline",
      stattrak: true,
    });
    expect(nameParts("★ Karambit | Fade (Factory New)")).toEqual({
      weapon: "Karambit",
      skin: "Fade",
      stattrak: false,
    });
    expect(nameParts("Sticker Capsule")).toEqual({
      weapon: null,
      skin: "Sticker Capsule",
      stattrak: false,
    });
  });
});

describe("sellBody", () => {
  it("names the card the API's way", () => {
    expect(sellBody(["1"], { to: "balance" }, 10)).toEqual({
      asset_ids: ["1"],
      payout: { to: "balance" },
      expected_payout_uzs: 10,
    });
    expect(sellBody(["1"], { to: "saved", cardId: "c1", type: "humo" }, 10).payout).toEqual({
      to: "card",
      card_id: "c1",
    });
    expect(
      sellBody(["1"], { to: "new", type: "humo", digits: "9860123456789015" }, 10).payout,
    ).toEqual({ to: "card", new_card: { type: "humo", number: "9860123456789015" } });
  });
});
```

```tsx
// apps/web/src/app/[locale]/sell/page.test.tsx
// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import SellPage from "./page";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => key),
  setRequestLocale: () => undefined,
}));
const server = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/server-api", () => server);
vi.mock("@/components/ComingSoon", () => ({ ComingSoon: () => null }));
vi.mock("@/components/sell/SellView", () => ({ SellView: () => null }));

import { ComingSoon } from "@/components/ComingSoon";
import { SellView } from "@/components/sell/SellView";

const page = () => SellPage({ params: Promise.resolve({ locale: "ru" }) });

describe("sell page", () => {
  it("is «Скоро» while selling is switched off", async () => {
    server.apiGet.mockResolvedValue({ enabled: false });
    expect((await page()).type).toBe(ComingSoon);
  });

  it("is «Скоро» when the API cannot say", async () => {
    server.apiGet.mockRejectedValue(new Error("down"));
    expect((await page()).type).toBe(ComingSoon);
  });

  it("shows the sell page with the config when selling is on", async () => {
    const config = { enabled: true, balance_bonus_pct: "2" };
    server.apiGet.mockResolvedValue(config);
    const out = await page();
    expect(server.apiGet).toHaveBeenCalledWith("/sell/config", { noStore: true });
    const view = out.props.children as { type: unknown; props: { config: unknown } };
    expect(view.type).toBe(SellView);
    expect(view.props.config).toBe(config);
  });
});
```

```tsx
// apps/web/src/components/sell/SellView.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { SessionApiError } from "@csmarket/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SellView } from "./SellView";

import type { Inventory, SellConfig } from "@/lib/sell";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  api: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ session: api }));
const push = vi.hoisted(() => vi.fn());
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push }),
}));

const CONFIG: SellConfig = {
  enabled: true,
  balance_bonus_pct: "2",
  card_fee_pct: { uzcard: "5", humo: "5", uzum_visa: "5" },
  card_min_uzs: "30000",
  min_sum_uzs: "11300",
  max_cards: 3,
};
const INVENTORY: Inventory = {
  items: [
    {
      asset_id: "101",
      name: "P250 | Sand Dune (Field-Tested)",
      image_url: "https://img.test/101.png",
      exterior: "Field-Tested",
      rarity_color: null,
      category: null,
      price_uzs: "5600",
    },
    {
      asset_id: "100",
      name: "AK-47 | Redline (Field-Tested)",
      image_url: "https://img.test/100.png",
      exterior: "Field-Tested",
      rarity_color: "#d32ce6",
      category: "rifles",
      price_uzs: "149600",
    },
  ],
  max_items: 50,
  min_sum_uzs: "11300",
  fetched_at: "2026-10-08T10:00:00Z",
};
const SIGNED_IN = {
  status: "signed_in",
  user: {
    id: "u1",
    trade_link: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE",
  },
  signInHref: () => "/auth",
  refreshMe: vi.fn(),
};

function routeGets(inventory: () => Promise<unknown> = () => Promise.resolve(INVENTORY)) {
  api.apiGet.mockImplementation((path: string) =>
    path.startsWith("/api/v1/sell/inventory")
      ? inventory()
      : path === "/api/v1/payout-cards"
        ? Promise.resolve({ items: [] })
        : Promise.reject(new Error(path)),
  );
}

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SellView locale="ru" config={CONFIG} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const card = (name: RegExp) => screen.getByRole("button", { name });

describe("SellView", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    push.mockReset();
    auth.value = SIGNED_IN;
    routeGets();
  });

  it("asks a visitor to sign in", () => {
    auth.value = { status: "signed_out", user: null, signInHref: () => "/auth" };
    view();
    expect(screen.getByText("Войдите через Steam, чтобы продать скины.")).toBeInTheDocument();
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it("asks for a trade link first", () => {
    auth.value = { ...SIGNED_IN, user: { id: "u1", trade_link: null } };
    view();
    expect(screen.getByText(/Добавьте ссылку на обмен/)).toBeInTheDocument();
  });

  it("lists the items we buy, dearest first, and says what is shown", async () => {
    view();
    const names = await screen.findAllByText(/Redline|Sand Dune/);
    expect(names[0]).toHaveTextContent("Redline");
    expect(
      screen.getByText("Показаны предметы, которые можно продать сейчас."),
    ).toBeInTheDocument();
  });

  it("adds the balance bonus to the payout", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(card(/Sand Dune/));
    expect(screen.getAllByTestId("sell-payout")[0]).toHaveTextContent(/158\s300/);
  });

  it("keeps «Продать» off under the minimum and says how much to add", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Sand Dune/ }));
    const submit = screen.getAllByRole("button", { name: /Добавьте ещё на 5\s700/ })[0];
    expect(submit).toBeDisabled();
  });

  it("sells with a key and the payout it showed, then opens the sale", async () => {
    api.apiPost.mockResolvedValue({ number: "S7K2M9QX" });
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Продать за 152\s500/ })[0]);
    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/account/sales/S7K2M9QX");
    });
    const [path, body, options] = api.apiPost.mock.calls[0] as [
      string,
      unknown,
      { idempotencyKey: string },
    ];
    expect(path).toBe("/api/v1/sell");
    expect(body).toEqual({
      asset_ids: ["100"],
      payout: { to: "balance" },
      expected_payout_uzs: 152_500,
    });
    expect(options.idempotencyKey).toMatch(/^web-sell-/);
  });

  it("re-reads the inventory when the prices moved", async () => {
    api.apiPost.mockRejectedValue(new SessionApiError(409, "Conflict", { code: "prices_changed" }));
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Продать за/ })[0]);
    expect(await screen.findAllByText(/Цены обновились/)).not.toHaveLength(0);
    await waitFor(() => {
      expect(api.apiGet).toHaveBeenCalledWith("/api/v1/sell/inventory?refresh=1");
    });
  });

  it("explains a Steam refusal of the account", async () => {
    routeGets(() =>
      Promise.reject(
        new SessionApiError(409, "Conflict", { code: "steam_refused", reason: "profile_private" }),
      ),
    );
    view();
    expect(await screen.findByText(/Профиль Steam скрыт/)).toBeInTheDocument();
  });

  it("checks a new card's number against its type", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(screen.getAllByRole("radio", { name: /Новая карта Humo/ })[0]);
    fireEvent.change(screen.getAllByLabelText(/Номер карты Humo/)[0], {
      target: { value: "8600 1234 5678 9012" },
    });
    expect(screen.getAllByText("Это не карта Humo")[0]).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Продать за/ })[0]).toBeDisabled();
  });
});
```

(`SessionApiError(status, statusText, body)` — its `code` getter reads `body.code`, which is what `sellError` reads.)

- [ ] **Step 2: Run them**

Run: `pnpm --filter @csmarket/web exec vitest run src/lib/sell.test.ts "src/app/[locale]/sell/page.test.tsx" src/components/sell/SellView.test.tsx`
Expected: FAIL — `sellBody` / `luhnOk` / `nameParts` not exported, the page still renders the demo.

- [ ] **Step 3: `lib/sell.ts`, `lib/sales.ts`, `lib/paths.ts`**

```ts
// apps/web/src/lib/sell.ts
/**
 * Selling skins to us: wire shapes and calls for `/api/v1/sell*`, and the cart's arithmetic.
 *
 * The API decides every number. The cart computes the payout the same way — each soʻm figure
 * rounded down to 100, percents to two places — only to show it before the click, and sends
 * it as `expected_payout_uzs`: another server figure is 409 `prices_changed`. A card number is
 * typed here and sent once, with the sale; it is never logged or stored in the browser.
 */
import { SessionApiError } from "@csmarket/api-client";
import { assertNever } from "@csmarket/utils";

import { session } from "./api";

import type { SaleOut } from "./sales";

export type CardType = "uzcard" | "humo" | "uzum_visa";
export const CARD_TYPES: readonly CardType[] = ["uzcard", "humo", "uzum_visa"];

/** `SellConfigOut`: public, read by the page before anything is chosen. */
export interface SellConfig {
  enabled: boolean;
  balance_bonus_pct: string;
  card_fee_pct: Record<CardType, string>;
  card_min_uzs: string;
  /** The minimum sum in soʻm, a hint (the API decides); `null` without a rate. */
  min_sum_uzs: string | null;
  max_cards: number;
}

/** `SellItemOut`: an item we buy now, at our price. */
export interface SellItem {
  asset_id: string;
  /** Steam's market name; skin names stay English. */
  name: string;
  image_url: string | null;
  exterior: string | null;
  rarity_color: string | null;
  /** Our catalogue's category, for the chips; `null` when we do not list the item. */
  category: string | null;
  price_uzs: string;
}

/** `InventoryOut`. */
export interface Inventory {
  items: SellItem[];
  max_items: number;
  min_sum_uzs: string;
  fetched_at: string;
}

/** Where the money goes: the balance, a saved card, or a card typed in the cart. */
export type Payout =
  | { to: "balance" }
  | { to: "saved"; cardId: string; type: CardType }
  | { to: "new"; type: CardType; digits: string };

export interface SellSummary {
  items: number;
  bonus: number;
  fee: number;
  payout: number;
}

const floor100 = (n: number): number => Math.floor(n / 100) * 100;
/** A percent with up to two decimals in hundredths of a percent («1.5» → 150), so the
 * arithmetic stays on integers as the API's `Decimal` does. */
const basisPoints = (pct: string): number => Math.round(Number(pct) * 100);

/** The payout's card type; `null` for the balance. */
export function payoutCardType(p: Payout): CardType | null {
  return p.to === "balance" ? null : p.type;
}

/** The cart's money: the balance gets the bonus, a card pays its type's fee. */
export function sellSummary(
  prices: readonly number[],
  payout: Payout,
  config: SellConfig,
): SellSummary {
  const items = prices.reduce((a, b) => a + b, 0);
  const type = payoutCardType(payout);
  if (type === null) {
    const total = floor100((items * (10_000 + basisPoints(config.balance_bonus_pct))) / 10_000);
    return { items, bonus: total - items, fee: 0, payout: total };
  }
  const total = floor100((items * (10_000 - basisPoints(config.card_fee_pct[type]))) / 10_000);
  return { items, bonus: 0, fee: items - total, payout: total };
}

/** At most 16 digits out of whatever was typed or pasted. */
export function cardDigits(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, 16);
}

/** Digits grouped by four: «9860 1234 5678 9015». */
export function formatCard(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

/** The first digits of each card type we pay to (Uzcard has two ranges). */
export const CARD_PREFIX: Readonly<Record<CardType, readonly string[]>> = {
  uzcard: ["8600", "5614"],
  humo: ["9860"],
  uzum_visa: ["4"],
};

/** Whether `digits` start with one of `type`'s prefixes. */
export function hasPrefix(type: CardType, digits: string): boolean {
  return CARD_PREFIX[type].some((p) => digits.startsWith(p));
}

/** The Luhn check: every second digit from the right doubled. */
export function luhnOk(digits: string): boolean {
  let total = 0;
  [...digits].reverse().forEach((ch, i) => {
    const d = Number(ch);
    total += i % 2 === 1 ? (d * 2 > 9 ? d * 2 - 9 : d * 2) : d;
  });
  return total % 10 === 0;
}

/** A complete number of `type` that passes Luhn. */
export function cardFits(type: CardType, digits: string): boolean {
  return digits.length === 16 && hasPrefix(type, digits) && luhnOk(digits);
}

/** «StatTrak™ AK-47 | Redline (Field-Tested)» → AK-47, Redline, StatTrak. */
export function nameParts(name: string): {
  weapon: string | null;
  skin: string;
  stattrak: boolean;
} {
  const stattrak = name.includes("StatTrak™");
  const bare = name
    .replace(/^★\s*/, "")
    .replace("StatTrak™ ", "")
    .replace(/\s*\([^)]*\)\s*$/, "");
  const [weapon, skin] = bare.split(" | ");
  return skin === undefined
    ? { weapon: null, skin: bare, stattrak }
    : { weapon: weapon ?? null, skin, stattrak };
}

export const SELL_CONFIG_KEY = ["sell", "config"] as const;
export const INVENTORY_KEY = ["sell", "inventory"] as const;

/** `GET /sell/config` (public). */
export function getSellConfig(): Promise<SellConfig> {
  return session.apiGet<SellConfig>("/api/v1/sell/config", { anonymous: true });
}

/** `GET /sell/inventory`; `refresh` asks Skinslink again instead of the kept copy. */
export function getInventory(refresh = false): Promise<Inventory> {
  return session.apiGet<Inventory>(`/api/v1/sell/inventory${refresh ? "?refresh=1" : ""}`);
}

/** `SellIn`. */
export interface SellBody {
  asset_ids: string[];
  payout:
    | { to: "balance" }
    | { to: "card"; card_id: string }
    | { to: "card"; new_card: { type: CardType; number: string } };
  /** Whole soʻm the cart showed, a JSON integer. */
  expected_payout_uzs: number;
}

/** The request body for the chosen items and payout. */
export function sellBody(assetIds: readonly string[], payout: Payout, expected: number): SellBody {
  const base = { asset_ids: [...assetIds], expected_payout_uzs: expected };
  switch (payout.to) {
    case "balance":
      return { ...base, payout: { to: "balance" } };
    case "saved":
      return { ...base, payout: { to: "card", card_id: payout.cardId } };
    case "new":
      return {
        ...base,
        payout: { to: "card", new_card: { type: payout.type, number: payout.digits } },
      };
    default:
      return assertNever(payout);
  }
}

/** A fresh `POST /sell` key (16–160 chars on the API side): one per cart sent. */
export function mintSellKey(): string {
  return `web-sell-${crypto.randomUUID()}`;
}

export type SellErrorCode =
  | "prices_changed"
  | "below_minimum"
  | "below_card_minimum"
  | "too_many_items"
  | "steam_refused"
  | "sales_disabled"
  | "cards_limit"
  | "card_invalid"
  | "trade_link_missing"
  | "trade_link_bad"
  | "sales_unavailable";

const SELL_ERRORS: ReadonlySet<string> = new Set<SellErrorCode>([
  "prices_changed",
  "below_minimum",
  "below_card_minimum",
  "too_many_items",
  "steam_refused",
  "sales_disabled",
  "cards_limit",
  "card_invalid",
  "trade_link_missing",
  "trade_link_bad",
  "sales_unavailable",
]);

/** A refusal the sell page explains; `reason` is the Steam account code of `steam_refused`. */
export class SellError extends Error {
  constructor(
    public readonly code: SellErrorCode,
    public readonly reason: string | null,
  ) {
    super(code);
    this.name = "SellError";
  }
}

/** The API's 409 / 422 / 503 of the sell routes as a {@link SellError}; anything else `null`. */
export function sellError(err: unknown): SellError | null {
  if (!(err instanceof SessionApiError)) return null;
  const code = err.code ?? "";
  if (!SELL_ERRORS.has(code)) return null;
  // A problem+json body: read its `reason` field only.
  const body =
    typeof err.body === "object" && err.body !== null ? (err.body as Record<string, unknown>) : {};
  // Narrowed by the set above.
  return new SellError(code as SellErrorCode, typeof body.reason === "string" ? body.reason : null);
}

/** `POST /sell`; a refusal comes back as a {@link SellError}. */
export async function createSale(body: SellBody, key: string): Promise<SaleOut> {
  try {
    return await session.apiPost<SaleOut>("/api/v1/sell", body, { idempotencyKey: key });
  } catch (err) {
    throw sellError(err) ?? err;
  }
}
```

```ts
// apps/web/src/lib/sales.ts
/**
 * A seller's sales and saved cards: wire shapes and calls for `/api/v1/sales*` and
 * `/api/v1/payout-cards`. A card is shown by its type and last four digits only.
 */
import { session } from "./api";

import type { CardType } from "./sell";

export type SaleStatus =
  "creating" | "offered" | "hold" | "credited" | "payout" | "closed" | "reverted";

export type PayoutStatus = "waiting_hold" | "to_pay" | "paid" | "rejected" | "canceled";

/** `SaleOut`. Money in whole soʻm, as strings. */
export interface SaleOut {
  number: string;
  status: SaleStatus;
  payout_to: "balance" | "card";
  card: { type: CardType; last4: string } | null;
  items_uzs: string;
  bonus_uzs: string;
  fee_uzs: string;
  payout_uzs: string;
  items: { asset_id: string; name: string; image_url: string | null; price_uzs: string }[];
  /** The Steam offer to accept, while `offered`. */
  offer: { url: string; bot_name: string | null; expires_at: string | null } | null;
  /** When the money is due, while `hold`. */
  money_at: string | null;
  payout_status: PayoutStatus | null;
  created_at: string;
}

/** `CardOut`. */
export interface SavedCard {
  id: string;
  type: CardType;
  last4: string;
  created_at: string;
}

export const CARDS_KEY = ["payout-cards"] as const;

/** `GET /payout-cards`. */
export function listCards(): Promise<{ items: SavedCard[] }> {
  return session.apiGet<{ items: SavedCard[] }>("/api/v1/payout-cards");
}

/** `DELETE /payout-cards/{id}` (204). */
export function deleteCard(id: string, key: string): Promise<undefined> {
  return session.api<undefined>(`/api/v1/payout-cards/${encodeURIComponent(id)}`, {
    method: "DELETE",
    idempotencyKey: key,
  });
}

/** A fresh `DELETE /payout-cards/{id}` key. */
export function mintCardKey(): string {
  return `web-card-${crypto.randomUUID()}`;
}
```

`lib/paths.ts`, after `orderPath`:

```ts
/** A sale's page; the number is escaped (it is a path segment). */
export function salePath(number: string): string {
  return `/account/sales/${encodeURIComponent(number)}`;
}
```

and after `TRANSACTIONS`:

```ts
/** «Мои карты»: the saved payout cards. */
export const CARDS = "/account/cards";
```

(`SELL` stays in the "on their way" block's neighbour list; move its comment line so it no longer says «Скоро» about selling: `/** «Продать скины». */ export const SELL = "/sell";`.)

Delete `lib/sell-demo.ts` and `lib/sell-demo.test.ts` (`git rm`).

- [ ] **Step 4: The page**

```tsx
// apps/web/src/app/[locale]/sell/page.tsx
import { HandCoins } from "lucide-react";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ComingSoon } from "@/components/ComingSoon";
import { SellView } from "@/components/sell/SellView";
import { routing } from "@/i18n/routing";
import { apiGet } from "@/lib/server-api";

import type { SellConfig } from "@/lib/sell";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.nav" });
  return { title: t("sell"), robots: { index: false, follow: true } };
}

/** The switches as the API reports them now; `null` when it cannot say (then «Скоро»). */
async function sellConfig(): Promise<SellConfig | null> {
  try {
    return await apiGet<SellConfig>("/sell/config", { noStore: true });
  } catch {
    return null;
  }
}

/** «Продать скины»: the seller's inventory and the cart while selling is on, «Скоро» otherwise. */
export default async function SellPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const config = await sellConfig();
  if (config === null || !config.enabled) {
    return <ComingSoon section="sell" icon={HandCoins} />;
  }
  return (
    <main id="main-content" className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6">
      <SellView locale={locale} config={config} />
    </main>
  );
}
```

- [ ] **Step 5: The components**

`SellToolbar.tsx`: the props gain `onRefresh: () => void;` and `refreshing: boolean;`, and the refresh button becomes

```tsx
<button
  type="button"
  aria-label={t("refresh")}
  title={t("refresh")}
  onClick={p.onRefresh}
  disabled={p.refreshing}
  className="bg-surface-2 hover:bg-border-strong grid size-10 shrink-0 place-items-center rounded-lg disabled:opacity-60"
>
  <RefreshCw className={cn("size-4", p.refreshing && "animate-spin")} aria-hidden />
</button>
```

```tsx
// apps/web/src/components/sell/SellItemCard.tsx
"use client";

import { cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { Check } from "lucide-react";

import { nameParts, type SellItem } from "@/lib/sell";

interface SellItemCardProps {
  item: SellItem;
  locale: string;
  selected: boolean;
  onToggle: () => void;
}

/** An item we buy now: a toggle (an accent frame and a tick when chosen). */
export function SellItemCard({ item, locale, selected, onToggle }: SellItemCardProps) {
  const parts = nameParts(item.name);
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      title={item.name}
      className={cn(
        "bg-surface group relative flex flex-col rounded-xl border-2 p-3 text-left transition-colors",
        "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
        selected ? "border-accent" : "hover:border-border-strong border-transparent",
      )}
    >
      <span className="text-fg-dim flex items-center gap-1.5 text-[11px] font-semibold">
        {item.exterior}
        {parts.stattrak ? <span className="text-stattrak">ST™</span> : null}
      </span>
      <span
        aria-hidden
        className={cn(
          "absolute right-2.5 top-2.5 grid size-5 place-items-center rounded-md border",
          selected ? "bg-accent border-accent text-accent-fg" : "border-border-strong",
        )}
      >
        {selected ? <Check className="size-3.5" strokeWidth={3} /> : null}
      </span>
      <span className="relative my-2 grid h-24 place-items-center">
        {item.rarity_color ? (
          <span
            aria-hidden
            className="absolute inset-x-4 bottom-1 h-10 rounded-full opacity-30 blur-xl"
            style={{ background: item.rarity_color }}
          />
        ) : null}
        {item.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images, as on the catalogue cards
          <img src={item.image_url} alt="" loading="lazy" className="relative max-h-24 w-auto" />
        ) : null}
      </span>
      <span className="text-fg-dim truncate text-xs">{parts.weapon}</span>
      <span className="truncate text-[13px] font-medium">{parts.skin}</span>
      <span className="text-accent num mt-1.5 text-sm font-semibold">
        {formatUzs(locale, item.price_uzs)}
      </span>
    </button>
  );
}
```

```tsx
// apps/web/src/components/sell/PayoutPicker.tsx
"use client";

import { cn, LogoMark } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import type { SavedCard } from "@/lib/sales";

import { CARD_TYPES, type CardType, type Payout, type SellConfig } from "@/lib/sell";

/** The card brands' names, never translated, and their logos in `public/payout/`. */
export const CARD_BRANDS: Readonly<Record<CardType, string>> = {
  uzcard: "Uzcard",
  humo: "Humo",
  uzum_visa: "Uzum Visa",
};
const LOGO: Readonly<Record<CardType, string>> = {
  uzcard: "/payout/uzcard.png",
  humo: "/payout/humo.png",
  uzum_visa: "/payout/uzum-visa.png",
};

interface PayoutPickerProps {
  config: SellConfig;
  cards: SavedCard[];
  value: Payout;
  onPick: (payout: Payout) => void;
}

interface Option {
  key: string;
  payout: Payout;
  name: string;
  note: string;
  type: CardType | null;
}

const same = (a: Payout, b: Payout): boolean =>
  a.to === b.to &&
  (a.to !== "saved" || (b.to === "saved" && a.cardId === b.cardId)) &&
  (a.to !== "new" || (b.to === "new" && a.type === b.type));

/** Where the money goes: the balance (a bonus), a saved card or a new one (a fee). Radios. */
export function PayoutPicker({ config, cards, value, onPick }: PayoutPickerProps) {
  const t = useTranslations("web.sell.payout");
  const fee = (type: CardType) => t("cardNote", { percent: config.card_fee_pct[type] });
  const options: Option[] = [
    {
      key: "balance",
      payout: { to: "balance" },
      name: t("balance"),
      note: t("balanceNote", { percent: config.balance_bonus_pct }),
      type: null,
    },
    ...cards.map((c) => ({
      key: c.id,
      payout: { to: "saved", cardId: c.id, type: c.type } as const,
      name: `${CARD_BRANDS[c.type]} •••• ${c.last4}`,
      note: fee(c.type),
      type: c.type,
    })),
    ...(cards.length < config.max_cards
      ? CARD_TYPES.map((type) => ({
          key: `new-${type}`,
          payout: {
            to: "new",
            type,
            digits: value.to === "new" && value.type === type ? value.digits : "",
          } as const,
          name: `${t("newCard")} ${CARD_BRANDS[type]}`,
          note: fee(type),
          type,
        }))
      : []),
  ];
  return (
    <fieldset>
      <legend className="text-fg-muted mb-2 text-sm font-semibold">{t("title")}</legend>
      <div role="radiogroup" className="grid grid-cols-2 gap-2">
        {options.map((o) => {
          const on = same(o.payout, value);
          return (
            <button
              key={o.key}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={`${o.name}. ${o.note}`}
              onClick={() => {
                onPick(o.payout);
              }}
              className={cn(
                "flex flex-col items-start gap-2 rounded-lg border-2 p-2.5 text-left transition-colors",
                "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
                on
                  ? "border-accent bg-accent/10"
                  : "border-border bg-surface-2 hover:border-border-strong",
                o.type === null && "col-span-2 flex-row items-center",
              )}
            >
              {o.type === null ? (
                <span className="bg-bg grid size-10 shrink-0 place-items-center rounded-lg">
                  <LogoMark className="text-accent size-6" />
                </span>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element -- static brand logos from /public
                <img
                  src={LOGO[o.type]}
                  alt=""
                  width={60}
                  height={36}
                  className="h-9 w-auto rounded"
                />
              )}
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{o.name}</span>
                <span
                  className={cn("block text-xs", o.type === null ? "text-accent" : "text-fg-dim")}
                >
                  {o.note}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {cards.length >= config.max_cards ? (
        <p className="text-fg-dim mt-2 text-xs">{t("cardsLimit")}</p>
      ) : null}
    </fieldset>
  );
}
```

```tsx
// apps/web/src/components/sell/SellCart.tsx
"use client";

import { Button, cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";

import { CARD_BRANDS, PayoutPicker } from "./PayoutPicker";

import { useRouter } from "@/i18n/navigation";
import { salePath } from "@/lib/paths";
import { CARDS_KEY, listCards } from "@/lib/sales";
import {
  cardDigits,
  cardFits,
  createSale,
  formatCard,
  hasPrefix,
  mintSellKey,
  payoutCardType,
  sellBody,
  sellError,
  sellSummary,
  type Inventory,
  type Payout,
  type SellBody,
  type SellConfig,
  type SellErrorCode,
  type SellItem,
} from "@/lib/sell";

interface SellCartProps {
  locale: string;
  config: SellConfig;
  inventory: Inventory;
  chosen: SellItem[];
  onRemove: (assetId: string) => void;
  payout: Payout;
  onPayout: (p: Payout) => void;
  /** The API said the prices moved: read the inventory again. */
  onPricesChanged: () => void;
}

interface RowProps {
  label: string;
  value: string;
  strong?: boolean;
}

const Row = ({ label, value, strong }: RowProps) => (
  <p className={cn("flex items-baseline gap-3", strong ? "text-base font-bold" : "text-sm")}>
    <span className={strong ? "text-fg" : "text-fg-muted"}>{label}</span>
    <span aria-hidden className="border-border flex-1 border-b border-dashed" />
    <span
      className={cn("num", strong && "text-accent")}
      {...(strong ? { "data-testid": "sell-payout" } : {})}
    >
      {value}
    </span>
  </p>
);

/** The chosen skins, where the money goes, what reaches the seller, and «Продать». */
export function SellCart(p: SellCartProps) {
  const t = useTranslations("web.sell");
  const router = useRouter();
  const cardId = useId();
  const cards = useQuery({ queryKey: CARDS_KEY, queryFn: listCards });
  const [error, setError] = useState<SellErrorCode | "generic" | null>(null);
  const key = useRef<{ body: string; key: string } | null>(null);
  const sum = sellSummary(
    p.chosen.map((x) => Number(x.price_uzs)),
    p.payout,
    p.config,
  );
  const uzs = (n: number) => formatUzs(p.locale, n);
  const min = Number(p.inventory.min_sum_uzs);
  const cardMin = Number(p.config.card_min_uzs);
  const cardType = payoutCardType(p.payout);
  const toCard = cardType !== null;
  const newCard = p.payout.to === "new" ? p.payout : null;
  // A partial number is wrong once its first digits leave the type's prefix; a full one when
  // it fails Luhn.
  const wrongCard =
    newCard !== null &&
    newCard.digits.length >= 4 &&
    (!hasPrefix(newCard.type, newCard.digits) ||
      (newCard.digits.length === 16 && !cardFits(newCard.type, newCard.digits)));
  const belowMin = p.chosen.length > 0 && sum.items < min;
  const belowCardMin = toCard && sum.payout > 0 && sum.payout < cardMin;
  const sell = useMutation({
    mutationFn: (body: SellBody) => {
      const text = JSON.stringify(body);
      if (key.current?.body !== text) key.current = { body: text, key: mintSellKey() };
      return createSale(body, key.current.key);
    },
    onSuccess: (sale) => {
      key.current = null;
      router.push(salePath(sale.number));
    },
    onError: (err) => {
      const refusal = sellError(err);
      setError(refusal?.code ?? "generic");
      if (refusal?.code === "prices_changed") p.onPricesChanged();
    },
  });
  const blocked =
    p.chosen.length === 0 ||
    belowMin ||
    belowCardMin ||
    (newCard !== null && !cardFits(newCard.type, newCard.digits)) ||
    sell.isPending;
  const title = t("cart.title", { count: p.chosen.length });
  return (
    <aside aria-label={title} className="bg-surface flex flex-col gap-5 rounded-xl p-5">
      <h2 className="text-lg font-bold">
        {title}
        {p.chosen.length > 0 ? <span className="text-accent num"> · {uzs(sum.items)}</span> : null}
      </h2>
      {p.chosen.length === 0 ? (
        <p className="text-fg-muted text-sm">{t("cart.hint")}</p>
      ) : (
        <ul className="-mr-2 flex max-h-56 flex-col gap-1.5 overflow-y-auto pr-2">
          {p.chosen.map((x) => (
            <li key={x.asset_id} className="bg-surface-2 flex items-center gap-3 rounded-lg p-2">
              {x.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images
                <img src={x.image_url} alt="" className="h-8 w-12 shrink-0 object-contain" />
              ) : null}
              <span className="min-w-0 flex-1 truncate text-[13px]">{x.name}</span>
              <span className="num shrink-0 text-[13px] font-semibold">
                {uzs(Number(x.price_uzs))}
              </span>
              <button
                type="button"
                aria-label={t("cart.remove", { name: x.name })}
                onClick={() => {
                  p.onRemove(x.asset_id);
                }}
                className="text-fg-dim hover:text-fg rounded p-0.5"
              >
                <X className="size-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <PayoutPicker
        config={p.config}
        cards={cards.data?.items ?? []}
        value={p.payout}
        onPick={(next) => {
          setError(null);
          p.onPayout(next);
        }}
      />
      {newCard !== null ? (
        <div>
          <label htmlFor={cardId} className="text-fg-muted mb-2 block text-sm font-semibold">
            {t("card.label", { method: CARD_BRANDS[newCard.type] })}
          </label>
          <input
            id={cardId}
            inputMode="numeric"
            autoComplete="cc-number"
            placeholder="0000 0000 0000 0000"
            value={formatCard(newCard.digits)}
            onChange={(e) => {
              p.onPayout({ ...newCard, digits: cardDigits(e.target.value) });
            }}
            aria-invalid={wrongCard}
            className={cn(
              "bg-bg num h-12 w-full rounded-lg border px-4 text-lg tracking-wider outline-none",
              wrongCard ? "border-danger" : "border-border focus:border-accent",
            )}
          />
          {wrongCard ? (
            <p className="text-danger mt-2 text-sm">
              {t("card.wrong", { method: CARD_BRANDS[newCard.type] })}
            </p>
          ) : null}
        </div>
      ) : null}
      {toCard ? (
        <p className={cn("text-sm", belowCardMin ? "text-danger" : "text-fg-dim")}>
          {t("card.min", { sum: uzs(cardMin) })}
        </p>
      ) : null}
      <div className="flex flex-col gap-2">
        <Row label={t("summary.items")} value={uzs(sum.items)} />
        {cardType !== null ? (
          <Row
            label={t("summary.fee", { percent: p.config.card_fee_pct[cardType] })}
            value={`−${uzs(sum.fee)}`}
          />
        ) : (
          <Row
            label={t("summary.bonus", { percent: p.config.balance_bonus_pct })}
            value={`+${uzs(sum.bonus)}`}
          />
        )}
        <Row label={t("summary.payout")} value={uzs(sum.payout)} strong />
      </div>
      <p className="text-fg-dim text-xs">{t("when")}</p>
      {error ? <p className="text-danger text-sm">{t(`errors.${error}`)}</p> : null}
      <Button
        size="lg"
        disabled={blocked}
        onClick={() => {
          setError(null);
          sell.mutate(
            sellBody(
              p.chosen.map((x) => x.asset_id),
              p.payout,
              sum.payout,
            ),
          );
        }}
      >
        {sell.isPending
          ? t("sending")
          : belowMin
            ? t("addMore", { sum: uzs(min - sum.items) })
            : t("submit", { sum: uzs(sum.payout) })}
      </Button>
    </aside>
  );
}
```

```tsx
// apps/web/src/components/sell/SellView.tsx
"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { SellCart } from "./SellCart";
import { SellItemCard } from "./SellItemCard";
import { SellToolbar, type SellSort } from "./SellToolbar";

import { TradeLinkForm } from "@/components/account/TradeLinkForm";
import { useAuth } from "@/lib/auth";
import {
  getInventory,
  INVENTORY_KEY,
  sellError,
  sellSummary,
  type Inventory,
  type Payout,
  type SellConfig,
  type SellItem,
} from "@/lib/sell";

interface SellViewProps {
  locale: string;
  config: SellConfig;
}

const price = (x: SellItem): number => Number(x.price_uzs);
const ORDER: Record<SellSort, (a: SellItem, b: SellItem) => number> = {
  expensive: (a, b) => price(b) - price(a),
  cheap: (a, b) => price(a) - price(b),
  name: (a, b) => a.name.localeCompare(b.name),
};
const NO_ITEMS: SellItem[] = [];

/** «Продайте скины»: the items we buy now, and a cart with the payout beside them. */
export function SellView({ locale, config }: SellViewProps) {
  const t = useTranslations("web.sell");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref, refreshMe } = useAuth();
  const ready = status === "signed_in" && user !== null && Boolean(user.trade_link);
  const qc = useQueryClient();
  const inventory = useQuery({
    queryKey: INVENTORY_KEY,
    queryFn: () => getInventory(),
    enabled: ready,
    retry: false,
  });
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SellSort>("expensive");
  const [category, setCategory] = useState<string | null>(null);
  const [payout, setPayout] = useState<Payout>({ to: "balance" });
  const [sheet, setSheet] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const items = inventory.data?.items ?? NO_ITEMS;
  const maxItems = inventory.data?.max_items ?? 0;
  const categories = useMemo(
    () => [...new Set(items.flatMap((x) => (x.category ? [x.category] : [])))],
    [items],
  );
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items
      .filter(
        (x) => (category === null || x.category === category) && x.name.toLowerCase().includes(q),
      )
      .sort(ORDER[sort]);
  }, [items, query, category, sort]);
  const picked = items.filter((x) => chosen.has(x.asset_id));
  const allChosen = items.length > 0 && picked.length === Math.min(items.length, maxItems);
  const toggle = (id: string) => {
    setChosen((cur) => {
      const next = new Set(cur);
      if (!next.delete(id) && next.size < maxItems) next.add(id);
      return next;
    });
  };
  const reload = async () => {
    setRefreshing(true);
    try {
      const fresh: Inventory = await getInventory(true);
      qc.setQueryData(INVENTORY_KEY, fresh);
      setChosen(
        (cur) => new Set([...cur].filter((id) => fresh.items.some((x) => x.asset_id === id))),
      );
    } catch {
      await inventory.refetch();
    } finally {
      setRefreshing(false);
    }
  };
  const uzs = (n: number) => formatUzs(locale, n);

  let body;
  if (status === "loading" || (ready && inventory.isPending)) {
    body = <div aria-busy className="bg-surface h-96 animate-pulse rounded-xl" />;
  } else if (status !== "signed_in" || !user) {
    body = (
      <div className="bg-surface flex flex-col items-start gap-4 rounded-xl p-6">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold"
        >
          {nav("signIn")}
        </a>
      </div>
    );
  } else if (!user.trade_link) {
    body = (
      <div className="flex max-w-2xl flex-col gap-3">
        <p className="text-fg-muted">{t("needTradeLink")}</p>
        <TradeLinkForm
          initial={{ trade_link: null, verdict: null, reason: null }}
          onChange={() => {
            void refreshMe();
          }}
        />
      </div>
    );
  } else if (inventory.isError || !inventory.data) {
    const refusal = sellError(inventory.error);
    const reason = refusal?.reason ?? "other";
    body = (
      <div className="bg-surface flex flex-col items-start gap-4 rounded-xl p-6">
        <p className="text-fg-muted">
          {refusal?.code === "steam_refused"
            ? t.has(`steam.${reason}`)
              ? t(`steam.${reason}`)
              : t("steam.other")
            : t("loadFailed")}
        </p>
        <Button variant="secondary" onClick={() => void reload()}>
          {t("retry")}
        </Button>
      </div>
    );
  } else {
    const cart = (
      <SellCart
        locale={locale}
        config={config}
        inventory={inventory.data}
        chosen={picked}
        onRemove={toggle}
        payout={payout}
        onPayout={setPayout}
        onPricesChanged={() => void reload()}
      />
    );
    body = (
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-4">
          <SellToolbar
            query={query}
            onQuery={setQuery}
            sort={sort}
            onSort={setSort}
            categories={categories}
            category={category}
            onCategory={setCategory}
            allChosen={allChosen}
            onToggleAll={() => {
              setChosen(
                allChosen ? new Set() : new Set(shown.slice(0, maxItems).map((x) => x.asset_id)),
              );
            }}
            onRefresh={() => void reload()}
            refreshing={refreshing}
          />
          <p className="text-fg-muted text-sm">
            {t("total", { count: items.length, sum: uzs(items.reduce((a, x) => a + price(x), 0)) })}
          </p>
          {shown.length === 0 ? (
            <p className="text-fg-muted py-16 text-center">
              {items.length === 0 ? t("emptyInventory") : t("empty")}
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">
              {shown.map((x) => (
                <SellItemCard
                  key={x.asset_id}
                  item={x}
                  locale={locale}
                  selected={chosen.has(x.asset_id)}
                  onToggle={() => {
                    toggle(x.asset_id);
                  }}
                />
              ))}
            </div>
          )}
          <p className="text-fg-dim text-sm">{t("shownNote")}</p>
          {picked.length >= maxItems && maxItems > 0 ? (
            <p className="text-fg-dim text-sm">{t("cart.max", { count: maxItems })}</p>
          ) : null}
        </div>
        <div className="hidden lg:sticky lg:top-4 lg:block">{cart}</div>
        {picked.length > 0 ? (
          <div className="bg-surface border-border fixed inset-x-0 bottom-0 z-30 flex items-center gap-3 border-t p-3 lg:hidden">
            <span className="flex-1 text-sm font-semibold">
              {t("cart.title", { count: picked.length })}
              <span className="text-accent num block">
                {uzs(sellSummary(picked.map(price), payout, config).payout)}
              </span>
            </span>
            <Button
              onClick={() => {
                setSheet(true);
              }}
            >
              {t("continue")}
            </Button>
          </div>
        ) : null}
        {sheet ? (
          <div className="bg-bg/80 fixed inset-0 z-40 overflow-y-auto p-3 backdrop-blur lg:hidden">
            <div className="mb-2 flex justify-end">
              <button
                type="button"
                aria-label={t("close")}
                onClick={() => {
                  setSheet(false);
                }}
                className="bg-surface grid size-10 place-items-center rounded-lg"
              >
                <X className="size-5" aria-hidden />
              </button>
            </div>
            {cart}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 pb-24 lg:pb-0">
      <h1 className="text-center text-3xl font-bold">{t("title")}</h1>
      {body}
    </div>
  );
}
```

- [ ] **Step 6: The copy**

In each `packages/i18n/locales/<locale>/web.json`, replace the whole `sell` object (the demo's `available`, `unavailable.*` and `soon` go; the keys below are all three locales' complete set).

`ru`:

```json
"sell": {
  "title": "Продайте скины КС2 (CS2)",
  "search": "Поиск по названию",
  "sortLabel": "Сортировка",
  "sort": { "expensive": "Сначала дороже", "cheap": "Сначала дешевле", "name": "По названию" },
  "all": "Все",
  "selectAll": "Выбрать все",
  "clearAll": "Снять выбор",
  "refresh": "Обновить инвентарь",
  "total": "{count, plural, one {# предмет} few {# предмета} many {# предметов} other {# предмета}} на {sum}",
  "shownNote": "Показаны предметы, которые можно продать сейчас.",
  "empty": "Ничего не нашлось.",
  "emptyInventory": "Сейчас нечего продать: в инвентаре нет предметов, которые мы покупаем.",
  "needTradeLink": "Добавьте ссылку на обмен — по ней мы покажем ваш инвентарь и пришлём предложение.",
  "signedOut": "Войдите через Steam, чтобы продать скины.",
  "loadFailed": "Не получилось загрузить инвентарь. Попробуйте ещё раз.",
  "retry": "Повторить",
  "steam": {
    "trade_link_revoked": "Ссылка на обмен сброшена в Steam. Добавьте новую в профиле.",
    "trade_link_invalid": "Ссылка на обмен не работает. Проверьте её в профиле.",
    "trade_banned": "На аккаунте Steam запрет обменов — продать скины сейчас нельзя.",
    "profile_private": "Профиль Steam скрыт. Откройте его, чтобы мы увидели инвентарь.",
    "limited_account": "Аккаунт Steam ограничен: обмены откроются после покупок в Steam на 5 $.",
    "hold": "На аккаунте Steam временный запрет обменов. Попробуйте позже.",
    "permissions": "Инвентарь CS2 скрыт. Откройте его в настройках приватности Steam.",
    "hold_and_permissions": "Инвентарь CS2 скрыт, и на аккаунте временный запрет обменов.",
    "other": "Steam не разрешает обмен с этим аккаунтом."
  },
  "cart": {
    "title": "{count, plural, =0 {Ничего не выбрано} one {Выбран # скин} few {Выбрано # скина} many {Выбрано # скинов} other {Выбрано # скина}}",
    "hint": "Нажмите на скины, чтобы добавить их сюда.",
    "remove": "Убрать {name}",
    "max": "За раз — не больше {count} предметов."
  },
  "payout": {
    "title": "Куда получить",
    "balance": "Баланс csmarket",
    "balanceNote": "+{percent}% к сумме",
    "cardNote": "Комиссия {percent}%",
    "newCard": "Новая карта",
    "cardsLimit": "Сохранено 3 карты — удалите одну в профиле, чтобы добавить новую."
  },
  "card": {
    "label": "Номер карты {method}",
    "wrong": "Это не карта {method}",
    "min": "Минимум на карту — {sum}"
  },
  "summary": {
    "items": "Стоимость предметов",
    "fee": "Комиссия {percent}%",
    "bonus": "Бонус за баланс +{percent}%",
    "payout": "Вы получите"
  },
  "when": "Деньги придут через 7 дней после обмена.",
  "submit": "Продать за {sum}",
  "addMore": "Добавьте ещё на {sum}",
  "sending": "Отправляем…",
  "errors": {
    "prices_changed": "Цены обновились — проверьте сумму и нажмите ещё раз.",
    "below_minimum": "Сумма меньше минимальной — добавьте предметы.",
    "below_card_minimum": "На карту можно от минимальной суммы. Выберите баланс или добавьте предметы.",
    "too_many_items": "Слишком много предметов за раз — уберите часть.",
    "steam_refused": "Steam не разрешает обмен с этим аккаунтом.",
    "sales_disabled": "Продажа сейчас закрыта. Загляните позже.",
    "cards_limit": "Сохранено 3 карты — удалите одну в профиле.",
    "card_invalid": "Проверьте номер карты.",
    "trade_link_missing": "Добавьте ссылку на обмен.",
    "trade_link_bad": "Ссылка на обмен не работает. Проверьте её в профиле.",
    "sales_unavailable": "Не получилось. Попробуйте через минуту.",
    "generic": "Не получилось. Попробуйте ещё раз."
  },
  "continue": "Продолжить",
  "close": "Закрыть"
}
```

`uz`:

```json
"sell": {
  "title": "CS2 skinlaringizni soting",
  "search": "Nomi boʻyicha qidirish",
  "sortLabel": "Saralash",
  "sort": { "expensive": "Avval qimmatlari", "cheap": "Avval arzonlari", "name": "Nomi boʻyicha" },
  "all": "Hammasi",
  "selectAll": "Hammasini tanlash",
  "clearAll": "Tanlovni bekor qilish",
  "refresh": "Inventarni yangilash",
  "total": "{count, plural, other {# ta buyum}} — {sum}",
  "shownNote": "Hozir sotish mumkin boʻlgan buyumlar koʻrsatilgan.",
  "empty": "Hech narsa topilmadi.",
  "emptyInventory": "Hozir sotadigan narsa yoʻq: inventarda biz sotib oladigan buyumlar yoʻq.",
  "needTradeLink": "Almashuv havolasini qoʻshing — u orqali inventaringizni koʻrsatamiz va taklif yuboramiz.",
  "signedOut": "Skin sotish uchun Steam orqali kiring.",
  "loadFailed": "Inventarni yuklab boʻlmadi. Yana urinib koʻring.",
  "retry": "Qayta urinish",
  "steam": {
    "trade_link_revoked": "Almashuv havolasi Steamʼda yangilangan. Profilda yangisini qoʻshing.",
    "trade_link_invalid": "Almashuv havolasi ishlamayapti. Profilda tekshiring.",
    "trade_banned": "Steam akkauntida almashuv taqiqlangan — hozir skin sotib boʻlmaydi.",
    "profile_private": "Steam profili yopiq. Inventarni koʻrishimiz uchun uni oching.",
    "limited_account": "Steam akkaunti cheklangan: Steamʼda 5 $ xariddan keyin almashuvlar ochiladi.",
    "hold": "Steam akkauntida vaqtinchalik almashuv taqiqi bor. Keyinroq urinib koʻring.",
    "permissions": "CS2 inventari yopiq. Uni Steam maxfiylik sozlamalarida oching.",
    "hold_and_permissions": "CS2 inventari yopiq va akkauntda vaqtinchalik almashuv taqiqi bor.",
    "other": "Steam bu akkaunt bilan almashuvga ruxsat bermayapti."
  },
  "cart": {
    "title": "{count, plural, =0 {Hech narsa tanlanmagan} other {# ta skin tanlandi}}",
    "hint": "Skinlarni bu yerga qoʻshish uchun ustiga bosing.",
    "remove": "{name} ni olib tashlash",
    "max": "Bir martada {count} tadan koʻp boʻlmagan buyum."
  },
  "payout": {
    "title": "Qayerga olish",
    "balance": "csmarket balansi",
    "balanceNote": "Summaga +{percent}%",
    "cardNote": "Komissiya {percent}%",
    "newCard": "Yangi karta",
    "cardsLimit": "3 ta karta saqlangan — yangisini qoʻshish uchun profilda bittasini oʻchiring."
  },
  "card": {
    "label": "{method} karta raqami",
    "wrong": "Bu {method} karta emas",
    "min": "Kartaga eng kami — {sum}"
  },
  "summary": {
    "items": "Buyumlar qiymati",
    "fee": "Komissiya {percent}%",
    "bonus": "Balans uchun bonus +{percent}%",
    "payout": "Siz olasiz"
  },
  "when": "Pul almashuvdan 7 kun keyin tushadi.",
  "submit": "{sum} ga sotish",
  "addMore": "Yana {sum} qoʻshing",
  "sending": "Yuborilmoqda…",
  "errors": {
    "prices_changed": "Narxlar yangilandi — summani tekshirib, yana bosing.",
    "below_minimum": "Summa eng kam miqdordan kam — buyum qoʻshing.",
    "below_card_minimum": "Kartaga eng kam summadan boshlab. Balansni tanlang yoki buyum qoʻshing.",
    "too_many_items": "Bir martada juda koʻp buyum — bir qismini olib tashlang.",
    "steam_refused": "Steam bu akkaunt bilan almashuvga ruxsat bermayapti.",
    "sales_disabled": "Sotish hozir yopiq. Keyinroq kiring.",
    "cards_limit": "3 ta karta saqlangan — profilda bittasini oʻchiring.",
    "card_invalid": "Karta raqamini tekshiring.",
    "trade_link_missing": "Almashuv havolasini qoʻshing.",
    "trade_link_bad": "Almashuv havolasi ishlamayapti. Profilda tekshiring.",
    "sales_unavailable": "Boʻlmadi. Bir daqiqadan keyin urinib koʻring.",
    "generic": "Boʻlmadi. Yana urinib koʻring."
  },
  "continue": "Davom etish",
  "close": "Yopish"
}
```

`en`:

```json
"sell": {
  "title": "Sell your CS2 skins",
  "search": "Search by name",
  "sortLabel": "Sort",
  "sort": { "expensive": "Most expensive", "cheap": "Cheapest", "name": "By name" },
  "all": "All",
  "selectAll": "Select all",
  "clearAll": "Clear selection",
  "refresh": "Refresh inventory",
  "total": "{count, plural, one {# item} other {# items}} worth {sum}",
  "shownNote": "Showing the items you can sell now.",
  "empty": "Nothing found.",
  "emptyInventory": "Nothing to sell right now: your inventory has no items we buy.",
  "needTradeLink": "Add your trade link — we use it to show your inventory and send the offer.",
  "signedOut": "Sign in with Steam to sell skins.",
  "loadFailed": "Could not load your inventory. Try again.",
  "retry": "Try again",
  "steam": {
    "trade_link_revoked": "Your trade link was reset in Steam. Add the new one in your profile.",
    "trade_link_invalid": "Your trade link does not work. Check it in your profile.",
    "trade_banned": "Your Steam account is trade banned — selling is not possible now.",
    "profile_private": "Your Steam profile is private. Make it public so we can see your inventory.",
    "limited_account": "Your Steam account is limited: trading opens after 5 $ of Steam purchases.",
    "hold": "Your Steam account has a temporary trade restriction. Try later.",
    "permissions": "Your CS2 inventory is private. Make it public in Steam's privacy settings.",
    "hold_and_permissions": "Your CS2 inventory is private and the account has a temporary trade restriction.",
    "other": "Steam does not allow trading with this account."
  },
  "cart": {
    "title": "{count, plural, =0 {Nothing selected} one {# skin selected} other {# skins selected}}",
    "hint": "Tap skins to add them here.",
    "remove": "Remove {name}",
    "max": "Up to {count} items at a time."
  },
  "payout": {
    "title": "Get paid to",
    "balance": "csmarket balance",
    "balanceNote": "+{percent}% on top",
    "cardNote": "Fee {percent}%",
    "newCard": "New card",
    "cardsLimit": "3 cards saved — delete one in your profile to add another."
  },
  "card": {
    "label": "{method} card number",
    "wrong": "This is not a {method} card",
    "min": "Minimum to a card — {sum}"
  },
  "summary": {
    "items": "Items",
    "fee": "Fee {percent}%",
    "bonus": "Balance bonus +{percent}%",
    "payout": "You get"
  },
  "when": "The money arrives 7 days after the trade.",
  "submit": "Sell for {sum}",
  "addMore": "Add {sum} more",
  "sending": "Sending…",
  "errors": {
    "prices_changed": "Prices changed — check the sum and press again.",
    "below_minimum": "The sum is under the minimum — add items.",
    "below_card_minimum": "A card needs at least the minimum sum. Choose the balance or add items.",
    "too_many_items": "Too many items at a time — remove some.",
    "steam_refused": "Steam does not allow trading with this account.",
    "sales_disabled": "Selling is closed right now. Come back later.",
    "cards_limit": "3 cards saved — delete one in your profile.",
    "card_invalid": "Check the card number.",
    "trade_link_missing": "Add your trade link.",
    "trade_link_bad": "Your trade link does not work. Check it in your profile.",
    "sales_unavailable": "That did not work. Try again in a minute.",
    "generic": "That did not work. Try again."
  },
  "continue": "Continue",
  "close": "Close"
}
```

- [ ] **Step 7: Run the tests and the checks**

Run: `pnpm --filter @csmarket/web exec vitest run src/lib/sell.test.ts "src/app/[locale]/sell/page.test.tsx" src/components/sell && pnpm --filter @csmarket/i18n exec vitest run && pnpm --filter @csmarket/web exec tsc --noEmit && pnpm --filter @csmarket/web exec eslint src/lib/sell.ts src/lib/sales.ts src/lib/paths.ts "src/app/[locale]/sell" src/components/sell --max-warnings 0 && npx prettier --write apps/web/src/lib/sell.ts apps/web/src/lib/sales.ts apps/web/src/lib/paths.ts "apps/web/src/app/[locale]/sell" apps/web/src/components/sell packages/i18n/locales`
Expected: PASS (the locale-parity test included); tsc and eslint clean.

- [ ] **Step 8: Commit**

```bash
git rm apps/web/src/lib/sell-demo.ts apps/web/src/lib/sell-demo.test.ts
git add apps/web/src/lib/sell.ts apps/web/src/lib/sell.test.ts apps/web/src/lib/sales.ts apps/web/src/lib/paths.ts "apps/web/src/app/[locale]/sell" apps/web/src/components/sell packages/i18n/locales
git commit -m "feat(web/sell): the real inventory, payout to the balance or a card, «Продать»" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Storefront account — the sale page, «Продажи» in «Обмены», «Мои карты», money on its way, the socket

**Files:**

- Modify: `apps/web/src/lib/sales.ts` (reads, keys, `salePollInterval`); create `apps/web/src/lib/sales.test.ts`
- Create: `apps/web/src/app/[locale]/account/sales/[number]/page.tsx`, `apps/web/src/components/sale/SaleView.tsx`, `apps/web/src/components/sale/SaleView.test.tsx`
- Create: `apps/web/src/components/account/SalesList.tsx`, `SalesList.test.tsx`; modify `apps/web/src/components/trades/TradesView.tsx`, `TradesView.test.tsx`
- Create: `apps/web/src/app/[locale]/account/cards/page.tsx`, `apps/web/src/components/account/CardsList.tsx`, `CardsList.test.tsx`
- Modify: `apps/web/src/components/header/nav.ts` (+ «Мои карты»); `components/header/AccountMenu.test.tsx`, `MobileMenu.test.tsx`, `components/account/AccountSidebar.test.tsx` (the expected lists)
- Modify: `apps/web/src/components/balance/BalanceView.tsx`, `BalanceView.test.tsx`; `apps/web/src/lib/balance.ts` (`EntryKind`)
- Modify: `apps/web/src/lib/realtime.ts`, `realtime.test.ts`, `apps/web/src/hooks/useOrderSocket.ts`
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (`sales`, `cards`, `nav.cards`, `balance.pending`, `balance.kind.*`)

**Interfaces:**

- Consumes: `GET /api/v1/sales`, `/sales/pending`, `/sales/{number}`, `GET`/`DELETE /api/v1/payout-cards` (Tasks 6, 11); `SaleOut`, `SavedCard`, `CARDS_KEY`, `listCards`, `deleteCard`, `mintCardKey` (Task 13); the socket frame `{"type": "sale.updated", "number"}` (Task 7).
- Produces in `lib/sales.ts`: `saleKey(number)`, `SALES_KEY`, `PENDING_KEY`, `getSale(number)`, `listSales(cursor?) -> Promise<SalesPage>`, `getPendingSales() -> Promise<{pending_uzs: string}>`, `SalesPage`, `salePollInterval(sale) -> number | false` (5 s while `creating` / `offered`, 60 s while `hold` or a card payout `to_pay`, else stop).
- Produces in `lib/realtime.ts`: `OrderSocketOptions.onSaleChanged?: (number: string) => void`.
- Produces: `ACCOUNT_NAV` gains `{ key: "cards", href: CARDS, icon: CreditCard }` after «Обмены».

- [ ] **Step 1: Write the failing tests**

```ts
// apps/web/src/lib/sales.test.ts
import { describe, expect, it } from "vitest";

import { salePollInterval, type SaleOut } from "./sales";

const sale = (over: Partial<SaleOut>): SaleOut => ({
  number: "S7K2M9QX",
  status: "offered",
  payout_to: "balance",
  card: null,
  items_uzs: "155200",
  bonus_uzs: "3100",
  fee_uzs: "0",
  payout_uzs: "158300",
  items: [],
  offer: null,
  money_at: null,
  payout_status: null,
  created_at: "2026-10-08T10:00:00Z",
  ...over,
});

describe("salePollInterval", () => {
  it("asks often while the offer is out, rarely while the money waits, never once settled", () => {
    expect(salePollInterval(sale({ status: "creating" }))).toBe(5_000);
    expect(salePollInterval(sale({ status: "offered" }))).toBe(5_000);
    expect(salePollInterval(sale({ status: "hold" }))).toBe(60_000);
    expect(salePollInterval(sale({ status: "payout", payout_status: "to_pay" }))).toBe(60_000);
    expect(salePollInterval(sale({ status: "payout", payout_status: "paid" }))).toBe(false);
    expect(salePollInterval(sale({ status: "credited" }))).toBe(false);
    expect(salePollInterval(undefined)).toBe(false);
  });
});
```

```tsx
// apps/web/src/components/sale/SaleView.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { SessionApiError } from "@csmarket/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SaleView } from "./SaleView";

import type * as SalesModule from "@/lib/sales";
import type { SaleOut } from "@/lib/sales";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ getSale: vi.fn() }));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  ...api,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const SALE: SaleOut = {
  number: "S7K2M9QX",
  status: "offered",
  payout_to: "balance",
  card: null,
  items_uzs: "155200",
  bonus_uzs: "3100",
  fee_uzs: "0",
  payout_uzs: "158300",
  items: [
    {
      asset_id: "100",
      name: "AK-47 | Redline (Field-Tested)",
      image_url: null,
      price_uzs: "149600",
    },
  ],
  offer: {
    url: "https://steamcommunity.com/tradeoffer/6912345678/",
    bot_name: "Bot #3",
    expires_at: "2026-10-08T12:30:00Z",
  },
  money_at: null,
  payout_status: null,
  created_at: "2026-10-08T10:00:00Z",
};

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SaleView locale="ru" number="S7K2M9QX" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("SaleView", () => {
  beforeEach(() => {
    api.getSale.mockReset();
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("asks to accept the trade with the offer's link and the bot", async () => {
    api.getSale.mockResolvedValue(SALE);
    view();
    expect(await screen.findByText("Примите обмен")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть обмен в Steam" })).toHaveAttribute(
      "href",
      SALE.offer?.url,
    );
    expect(screen.getByText(/Bot #3/)).toBeInTheDocument();
    expect(screen.getByText(/158\s300/)).toBeInTheDocument();
  });

  it("while the money waits, says when it comes and never says hold", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "hold",
      offer: null,
      money_at: "2026-10-15T10:00:00Z",
    });
    view();
    expect(await screen.findByText("Скины получены")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/холд|hold/i);
  });

  it("names the card by its last four once paid", async () => {
    api.getSale.mockResolvedValue({
      ...SALE,
      status: "payout",
      payout_to: "card",
      card: { type: "humo", last4: "9015" },
      offer: null,
      payout_status: "paid",
      payout_uzs: "147400",
    });
    view();
    expect(await screen.findByText("Деньги отправлены")).toBeInTheDocument();
    expect(screen.getByText(/•••• 9015/)).toBeInTheDocument();
  });

  it("says a sale it does not know is not found", async () => {
    api.getSale.mockRejectedValue(new SessionApiError(404, "Not Found", null));
    view();
    expect(await screen.findByText("Продажа не найдена.")).toBeInTheDocument();
  });
});
```

```tsx
// apps/web/src/components/account/SalesList.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SalesList } from "./SalesList";

import type * as SalesModule from "@/lib/sales";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ listSales: vi.fn() }));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  ...api,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SalesList locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("SalesList", () => {
  beforeEach(() => {
    api.listSales.mockReset();
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("links each sale with its first item, payout and status", async () => {
    api.listSales.mockResolvedValue({
      items: [
        {
          number: "S7K2M9QX",
          status: "hold",
          payout_to: "balance",
          card: null,
          items_uzs: "155200",
          bonus_uzs: "3100",
          fee_uzs: "0",
          payout_uzs: "158300",
          items: [
            {
              asset_id: "100",
              name: "AK-47 | Redline (Field-Tested)",
              image_url: null,
              price_uzs: "149600",
            },
            {
              asset_id: "101",
              name: "P250 | Sand Dune (Field-Tested)",
              image_url: null,
              price_uzs: "5600",
            },
          ],
          offer: null,
          money_at: "2026-10-15T10:00:00Z",
          payout_status: null,
          created_at: "2026-10-08T10:00:00Z",
        },
      ],
      next_cursor: null,
    });
    view();
    const link = await screen.findByRole("link", { name: /AK-47 \| Redline/ });
    expect(link).toHaveAttribute("href", "/account/sales/S7K2M9QX");
    expect(link).toHaveTextContent("+1");
    expect(link).toHaveTextContent(/158\s300/);
    expect(link).toHaveTextContent("Ждём 7 дней");
  });

  it("says when there are none", async () => {
    api.listSales.mockResolvedValue({ items: [], next_cursor: null });
    view();
    expect(await screen.findByText("Продаж пока нет.")).toBeInTheDocument();
  });
});
```

```tsx
// apps/web/src/components/account/CardsList.test.tsx
// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CardsList } from "./CardsList";

import type * as SalesModule from "@/lib/sales";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ listCards: vi.fn(), deleteCard: vi.fn() }));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  ...api,
}));

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <CardsList locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("CardsList", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("lists cards by brand and last four, and forgets one with a key", async () => {
    api.listCards.mockResolvedValue({
      items: [{ id: "c1", type: "humo", last4: "9015", created_at: "2026-10-08T10:00:00Z" }],
    });
    api.deleteCard.mockResolvedValue(undefined);
    view();
    expect(await screen.findByText("Humo •••• 9015")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Удалить Humo •••• 9015" }));
    await waitFor(() => {
      expect(api.deleteCard).toHaveBeenCalledWith("c1", expect.stringMatching(/^web-card-/));
    });
  });

  it("says where a card comes from when there is none", async () => {
    api.listCards.mockResolvedValue({ items: [] });
    view();
    expect(await screen.findByText(/Карту можно добавить при продаже/)).toBeInTheDocument();
  });
});
```

`TradesView.test.tsx`: mock `SalesList` like `OrdersList` (`vi.mock("@/components/account/SalesList", () => ({ SalesList: () => <p>sales-list</p> }))`); "filters" expects both `orders-list` and `sales-list` on «Все»; "purchases" expects `orders-list` and no `sales-list`; the third test becomes:

```tsx
it("sales are the sales list", () => {
  view("sales");
  expect(screen.queryByText("orders-list")).toBeNull();
  expect(screen.getByText("sales-list")).toBeInTheDocument();
});
```

`AccountMenu.test.tsx`, `MobileMenu.test.tsx`, `AccountSidebar.test.tsx`: the expected list gains `["Мои карты", "/account/cards"],` after `["Обмены", "/account/trades"],` (the AccountMenu test's name becomes "lists profile, transactions, trades, cards, referral with icons and signs out").

`BalanceView.test.tsx`: add beside the `@/lib/balance` mock

```tsx
const sales = vi.hoisted(() => ({ getPendingSales: vi.fn() }));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  ...sales,
}));
```

(with `import type * as SalesModule from "@/lib/sales";` beside the file's `BalanceModule` import)

in `beforeEach`: `sales.getPendingSales.mockReset().mockResolvedValue({ pending_uzs: "0" });`, and the test:

```tsx
it("shows the money on its way from sales, only when there is some", async () => {
  auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/s" };
  sales.getPendingSales.mockResolvedValue({ pending_uzs: "158300" });
  renderView();
  expect(await screen.findByText(/Ожидает зачисления: 158\s300/)).toBeInTheDocument();
});
```

`realtime.test.ts`, a new case:

```ts
it("reports a changed sale apart from orders", async () => {
  const sales: string[] = [];
  const changed: string[] = [];
  const socket = new OrderSocket({
    url: "ws://api.test/api/v1/realtime/orders",
    getToken: () => Promise.resolve("t1"),
    onChanged: (n) => changed.push(n),
    onSaleChanged: (n) => sales.push(n),
    // The fake's shape is what OrderSocket uses of a WebSocket.
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
    random: () => 0,
  });
  socket.start();
  await flush();
  last().open();
  last().message({ type: "sale.updated", number: "S7K2M9QX" });
  last().message({ type: "sale.updated" });
  expect([sales, changed]).toEqual([["S7K2M9QX"], []]);
  socket.stop();
});
```

- [ ] **Step 2: Run them**

Run: `pnpm --filter @csmarket/web exec vitest run src/lib/sales.test.ts src/components/sale src/components/account src/components/trades src/components/header src/components/balance/BalanceView.test.tsx src/lib/realtime.test.ts`
Expected: FAIL — `salePollInterval` not exported, `SaleView` / `SalesList` / `CardsList` missing, the nav lists one entry short.

- [ ] **Step 3: `lib/sales.ts` reads**

Append to `apps/web/src/lib/sales.ts`:

```ts
/** `SalesPage`: newest first; `next_cursor` is `null` on the last page. */
export interface SalesPage {
  items: SaleOut[];
  next_cursor: string | null;
}

export const SALES_KEY = ["sales", "list"] as const;
export const PENDING_KEY = ["sales", "pending"] as const;
export const saleKey = (number: string) => ["sales", "one", number] as const;

/** `GET /sales/{number}`. */
export function getSale(number: string): Promise<SaleOut> {
  return session.apiGet<SaleOut>(`/api/v1/sales/${encodeURIComponent(number)}`);
}

/** `GET /sales?cursor=`. */
export function listSales(cursor?: string): Promise<SalesPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return session.apiGet<SalesPage>(`/api/v1/sales${query}`);
}

/** `GET /sales/pending`: what balance sales will credit once the 7 days pass. */
export function getPendingSales(): Promise<{ pending_uzs: string }> {
  return session.apiGet<{ pending_uzs: string }>("/api/v1/sales/pending");
}

/** How often the sale page asks again: often while the offer is out, rarely while the money
 * waits, never once nothing can change. A socket nudge asks sooner. */
export function salePollInterval(sale: SaleOut | undefined): number | false {
  if (!sale) return false;
  if (sale.status === "creating" || sale.status === "offered") return 5_000;
  if (sale.status === "hold" || (sale.status === "payout" && sale.payout_status === "to_pay")) {
    return 60_000;
  }
  return false;
}
```

- [ ] **Step 4: The sale page**

```tsx
// apps/web/src/app/[locale]/account/sales/[number]/page.tsx
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { SaleView } from "@/components/sale/SaleView";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string; number: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale, number } = await params;
  const t = await getTranslations({ locale, namespace: "web.sales" });
  return { title: t("number", { number }), robots: { index: false, follow: false } };
}

/** A sale's page: per-account, so the body renders client-side (an unknown number says so
 * there; no `notFound()`, so no `loading.tsx`). */
export default async function SalePage({ params }: Props) {
  const { locale, number } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <SaleView locale={locale} number={number} />
    </main>
  );
}
```

```tsx
// apps/web/src/components/sale/SaleView.tsx
"use client";

import { SessionApiError } from "@csmarket/api-client";
import { buttonVariants } from "@csmarket/ui";
import { assertNever, formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CARD_BRANDS } from "@/components/sell/PayoutPicker";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { TRADES } from "@/lib/paths";
import { getSale, saleKey, salePollInterval, type SaleOut } from "@/lib/sales";

interface SaleViewProps {
  locale: string;
  number: string;
}

const notFound = (err: unknown): boolean => err instanceof SessionApiError && err.status === 404;

/** What the sale's state means to the seller: a headline and one sentence. */
function useStateText(sale: SaleOut, locale: string): { title: string; text: string } {
  const t = useTranslations("web.sales.state");
  const amount = formatUzs(locale, sale.payout_uzs);
  const card = sale.card ? `${CARD_BRANDS[sale.card.type]} •••• ${sale.card.last4}` : "";
  const when = (iso: string | null) =>
    iso
      ? new Intl.DateTimeFormat(locale, { day: "numeric", month: "long" }).format(new Date(iso))
      : "";
  switch (sale.status) {
    case "creating":
      return { title: t("creating.title"), text: t("creating.text") };
    case "offered":
      return {
        title: t("offered.title"),
        text: t("offered.text", {
          bot: sale.offer?.bot_name ?? "",
          time: sale.offer?.expires_at
            ? new Intl.DateTimeFormat(locale, { timeStyle: "short", dateStyle: "short" }).format(
                new Date(sale.offer.expires_at),
              )
            : "",
        }),
      };
    case "hold":
      return {
        title: t("hold.title"),
        text: t("hold.text", { amount, date: when(sale.money_at) }),
      };
    case "credited":
      return { title: t("credited.title"), text: t("credited.text", { amount }) };
    case "payout":
      if (sale.payout_status === "paid")
        return { title: t("paid.title"), text: t("paid.text", { amount, card }) };
      if (sale.payout_status === "rejected") {
        return {
          title: t("rejected.title"),
          text: t("rejected.text", { amount: formatUzs(locale, sale.items_uzs) }),
        };
      }
      return { title: t("payout.title"), text: t("payout.text", { amount, card }) };
    case "closed":
      return { title: t("closed.title"), text: t("closed.text") };
    case "reverted":
      return { title: t("reverted.title"), text: t("reverted.text") };
    default:
      return assertNever(sale.status);
  }
}

function SaleBody({ sale, locale }: { sale: SaleOut; locale: string }) {
  const t = useTranslations("web.sales");
  const sell = useTranslations("web.sell");
  const state = useStateText(sale, locale);
  const uzs = (v: string) => formatUzs(locale, v);
  return (
    <div className="flex flex-col gap-6">
      <section
        className="bg-surface flex flex-col items-start gap-3 rounded-xl p-5"
        data-state={sale.status}
      >
        <h2 className="text-xl font-bold">{state.title}</h2>
        <p className="text-fg-muted">{state.text}</p>
        {sale.offer ? (
          <a
            href={sale.offer.url}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonVariants({ size: "lg" })}
          >
            {t("openOffer")}
          </a>
        ) : null}
      </section>
      <ul className="flex flex-col gap-1.5">
        {sale.items.map((i) => (
          <li key={i.asset_id} className="bg-surface flex items-center gap-3 rounded-lg p-2">
            {i.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images
              <img src={i.image_url} alt="" className="h-8 w-12 shrink-0 object-contain" />
            ) : null}
            <span className="min-w-0 flex-1 truncate text-sm">{i.name}</span>
            <span className="num text-sm font-semibold">{uzs(i.price_uzs)}</span>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
        <dt className="text-fg-muted">{sell("summary.items")}</dt>
        <dd className="num text-right">{uzs(sale.items_uzs)}</dd>
        {sale.payout_to === "card" ? (
          <>
            <dt className="text-fg-muted">{t("fee")}</dt>
            <dd className="num text-right">−{uzs(sale.fee_uzs)}</dd>
          </>
        ) : (
          <>
            <dt className="text-fg-muted">{t("bonus")}</dt>
            <dd className="num text-right">+{uzs(sale.bonus_uzs)}</dd>
          </>
        )}
        <dt className="font-bold">{sell("summary.payout")}</dt>
        <dd className="num text-accent text-right font-bold">{uzs(sale.payout_uzs)}</dd>
      </dl>
    </div>
  );
}

/** A sale's page: what to do now (accept the offer), then the money's way, live. */
export function SaleView({ locale, number }: SaleViewProps) {
  const t = useTranslations("web.sales");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const sale = useQuery({
    queryKey: saleKey(number),
    queryFn: () => getSale(number),
    enabled: signedIn,
    refetchInterval: (q) => salePollInterval(q.state.data),
  });
  let body;
  if (status === "loading" || (signedIn && sale.isPending)) {
    body = <div aria-busy className="bg-surface h-48 animate-pulse rounded-xl" />;
  } else if (!signedIn) {
    body = (
      <a href={signInHref(locale)} className={buttonVariants({ size: "lg" })}>
        {nav("signIn")}
      </a>
    );
  } else if (sale.isError || !sale.data) {
    body = (
      <p className="text-fg-muted">{notFound(sale.error) ? t("notFound") : t("loadFailed")}</p>
    );
  } else {
    body = <SaleBody sale={sale.data} locale={locale} />;
  }
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <Link href={`${TRADES}?type=sales`} className="text-fg-muted text-sm hover:underline">
        ← {t("back")}
      </Link>
      <h1 className="text-3xl font-bold">{t("number", { number })}</h1>
      {body}
    </div>
  );
}
```

- [ ] **Step 5: «Продажи» in «Обмены»**

```tsx
// apps/web/src/components/account/SalesList.tsx
"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { salePath } from "@/lib/paths";
import { listSales, SALES_KEY, type SaleOut, type SalesPage } from "@/lib/sales";

interface SalesListProps {
  locale: string;
}

/** The status word of a sale; a card sale's payout refines «payout». */
export function saleLabel(sale: SaleOut): string {
  return sale.status === "payout" && sale.payout_status
    ? `payout.${sale.payout_status}`
    : `status.${sale.status}`;
}

/** «Продажи»: the seller's sales, newest first, one page at a time. */
export function SalesList({ locale }: SalesListProps) {
  const t = useTranslations("web.sales");
  const trades = useTranslations("web.trades");
  const { status, user } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const sales = useInfiniteQuery<
    SalesPage,
    Error,
    InfiniteData<SalesPage, string | null>,
    typeof SALES_KEY,
    string | null
  >({
    queryKey: SALES_KEY,
    queryFn: ({ pageParam }) => listSales(pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: signedIn,
  });
  const when = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: "medium" }), [locale]);
  if (!signedIn || sales.isPending)
    return <div aria-busy className="bg-surface h-24 animate-pulse rounded-lg" />;
  if (sales.isError) return <p className="text-fg-muted">{t("loadFailed")}</p>;
  const items = sales.data.pages.flatMap((p) => p.items);
  if (items.length === 0) return <p className="text-fg-muted">{trades("salesEmpty")}</p>;
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-3">
        {items.map((s) => {
          const [first] = s.items;
          return (
            <li key={s.number}>
              <Link
                href={salePath(s.number)}
                data-testid="sale-card"
                data-state={s.status}
                className="border-border hover:border-border-strong flex flex-col gap-2 rounded-lg border p-4"
              >
                <span className="flex justify-between gap-3">
                  <span className="min-w-0 truncate font-medium">
                    {first?.name}
                    {s.items.length > 1 ? (
                      <span className="text-fg-dim"> +{s.items.length - 1}</span>
                    ) : null}
                  </span>
                  <span className="num text-accent shrink-0 font-semibold">
                    {formatUzs(locale, s.payout_uzs)}
                  </span>
                </span>
                <span className="text-fg-dim flex justify-between text-sm">
                  <span className="text-fg-muted font-semibold">{t(saleLabel(s))}</span>
                  <span>
                    {t("number", { number: s.number })} ·{" "}
                    <time dateTime={s.created_at}>{when.format(new Date(s.created_at))}</time>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {sales.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          disabled={sales.isFetchingNextPage}
          onClick={() => void sales.fetchNextPage()}
        >
          {t("more")}
        </Button>
      ) : null}
    </div>
  );
}
```

`components/trades/TradesView.tsx`: import `SalesList`; the docstring becomes "«Обмены»: the buyer's orders and the seller's sales."; the body after `HistoryFilter`:

```tsx
{
  type === "purchases" ? <OrdersList locale={locale} /> : null;
}
{
  type === "sales" ? <SalesList locale={locale} /> : null;
}
{
  type === "all" ? (
    <>
      <OrdersList locale={locale} />
      <h2 className="mt-4 text-xl font-bold">{t("sales")}</h2>
      <SalesList locale={locale} />
    </>
  ) : null;
}
```

- [ ] **Step 6: «Мои карты»**

```tsx
// apps/web/src/components/account/CardsList.tsx
"use client";

import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CARD_BRANDS } from "@/components/sell/PayoutPicker";
import { useAuth } from "@/lib/auth";
import { CARDS_KEY, deleteCard, listCards, mintCardKey } from "@/lib/sales";

interface CardsListProps {
  locale: string;
}

/** «Мои карты»: saved payout cards by brand and last four; a card is added with a sale. */
export function CardsList({ locale }: CardsListProps) {
  const t = useTranslations("web.cards");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const qc = useQueryClient();
  const cards = useQuery({ queryKey: CARDS_KEY, queryFn: listCards, enabled: signedIn });
  const forget = useMutation({
    mutationFn: (id: string) => deleteCard(id, mintCardKey()),
    onSuccess: () => qc.invalidateQueries({ queryKey: CARDS_KEY }),
  });
  if (!signedIn) {
    return status === "loading" ? (
      <div aria-busy className="bg-surface h-24 animate-pulse rounded-lg" />
    ) : (
      <a
        href={signInHref(locale)}
        className="bg-accent text-accent-fg w-fit rounded-md px-5 py-3 font-semibold"
      >
        {nav("signIn")}
      </a>
    );
  }
  if (cards.isPending)
    return <div aria-busy className="bg-surface h-24 animate-pulse rounded-lg" />;
  if (cards.isError) return <p className="text-fg-muted">{t("loadFailed")}</p>;
  if (cards.data.items.length === 0) return <p className="text-fg-muted">{t("empty")}</p>;
  return (
    <ul className="flex max-w-xl flex-col gap-2">
      {cards.data.items.map((c) => {
        const name = `${CARD_BRANDS[c.type]} •••• ${c.last4}`;
        return (
          <li
            key={c.id}
            className="bg-surface flex items-center justify-between gap-3 rounded-lg p-4"
          >
            <span className="num font-medium">{name}</span>
            <Button
              variant="secondary"
              aria-label={t("delete", { name })}
              disabled={forget.isPending}
              onClick={() => {
                forget.mutate(c.id);
              }}
            >
              {t("deleteShort")}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
```

```tsx
// apps/web/src/app/[locale]/account/cards/page.tsx
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CardsList } from "@/components/account/CardsList";
import { routing } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.cards" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

/** «Мои карты»: per-account, so it renders client-side. */
export default async function CardsPage({ params }: Props) {
  const { locale } = await params;
  if (hasLocale(routing.locales, locale)) {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    setRequestLocale(locale);
  }
  const t = await getTranslations("web.cards");
  return (
    <main id="main-content" className="min-w-0 flex-1">
      <h1 className="mb-6 text-3xl font-bold">{t("title")}</h1>
      <CardsList locale={locale} />
    </main>
  );
}
```

`components/header/nav.ts`: `CreditCard` joins the lucide import, `CARDS` the paths import, `"cards"` the `key` union, and `ACCOUNT_NAV` becomes

```ts
export const ACCOUNT_NAV: NavEntry[] = [
  { key: "profile", href: ACCOUNT, icon: User },
  { key: "transactions", href: TRANSACTIONS, icon: ReceiptText },
  { key: "trades", href: TRADES, icon: ArrowLeftRight },
  { key: "cards", href: CARDS, icon: CreditCard },
  { key: "referral", href: REFERRAL, icon: Gift },
];
```

- [ ] **Step 7: Money on its way, the entry kinds, the socket**

`components/balance/BalanceView.tsx`: import `useQuery` is there; add `import { getPendingSales, PENDING_KEY } from "@/lib/sales";`, the query

```tsx
const pending = useQuery({ queryKey: PENDING_KEY, queryFn: getPendingSales, enabled: signedIn });
```

and under the balance figure (inside the first `<div>`):

```tsx
{
  pending.data && Number(pending.data.pending_uzs) > 0 ? (
    <p className="text-fg-dim mt-1 text-sm">
      {t("pending", { sum: formatUzs(locale, pending.data.pending_uzs) })}
    </p>
  ) : null;
}
```

`lib/balance.ts`: `export type EntryKind = "topup" | "topup_reversal" | "admin_adjust" | "purchase" | "refund" | "sale_credit" | "payout_return";` and the `reference_number` comment adds "the sale's number for `sale_credit` / `payout_return`".

`lib/realtime.ts`: in `OrderSocketOptions`, after `onChanged`:

```ts
  /** A sale of the signed-in seller changed (`sale.updated`). */
  onSaleChanged?: (number: string) => void;
```

the module docstring's protocol line gains "`{"type":"sale.updated","number"}`", and in `dispatch`, after the `order.changed` branch:

```ts
if (type === "sale.updated" && typeof number === "string" && number) {
  this.opts.onSaleChanged?.(number);
}
```

`hooks/useOrderSocket.ts`: import `PENDING_KEY, saleKey, SALES_KEY` from `@/lib/sales`, and the `OrderSocket` options gain

```ts
      onSaleChanged: (number) => {
        void qc.invalidateQueries({ queryKey: saleKey(number) });
        void qc.invalidateQueries({ queryKey: SALES_KEY });
        void qc.invalidateQueries({ queryKey: PENDING_KEY });
        void qc.invalidateQueries({ queryKey: BALANCE_KEY });
        void qc.invalidateQueries({ queryKey: ENTRIES_KEY });
      },
```

- [ ] **Step 8: The copy**

Add to each `web.json` (top level, beside `sell`), and the listed keys inside `nav` and `balance`.

`ru`:

```json
"sales": {
  "number": "Продажа #{number}",
  "back": "К обменам",
  "openOffer": "Открыть обмен в Steam",
  "fee": "Комиссия за перевод на карту",
  "bonus": "Бонус за баланс",
  "more": "Показать ещё",
  "notFound": "Продажа не найдена.",
  "loadFailed": "Не получилось загрузить продажу. Обновите страницу.",
  "status": {
    "creating": "Готовим обмен",
    "offered": "Примите обмен",
    "hold": "Ждём 7 дней",
    "credited": "На балансе",
    "payout": "Отправляем на карту",
    "closed": "Не состоялась",
    "reverted": "Обмен отменён"
  },
  "payout": {
    "waiting_hold": "Ждём 7 дней",
    "to_pay": "Отправляем на карту",
    "paid": "Отправлено на карту",
    "rejected": "На балансе",
    "canceled": "Не состоялась"
  },
  "state": {
    "creating": { "title": "Готовим обмен", "text": "Через минуту в Steam придёт предложение обмена." },
    "offered": { "title": "Примите обмен", "text": "{bot} прислал предложение в Steam. Примите его до {time}." },
    "hold": { "title": "Скины получены", "text": "{amount} поступят {date}." },
    "credited": { "title": "Деньги на балансе", "text": "{amount} зачислены на баланс csmarket." },
    "payout": { "title": "Отправляем деньги", "text": "Скоро отправим {amount} на карту {card}." },
    "paid": { "title": "Деньги отправлены", "text": "{amount} отправлены на карту {card}." },
    "rejected": { "title": "Деньги на балансе", "text": "Перевод на карту не прошёл — {amount} зачислены на баланс csmarket." },
    "closed": { "title": "Продажа не состоялась", "text": "Обмен не состоялся, скины остались у вас." },
    "reverted": { "title": "Обмен отменён", "text": "Обмен отменили в Steam — деньги за эту продажу не начисляются." }
  }
},
"cards": {
  "title": "Мои карты",
  "empty": "Карт пока нет. Карту можно добавить при продаже скинов.",
  "loadFailed": "Не получилось загрузить карты. Обновите страницу.",
  "delete": "Удалить {name}",
  "deleteShort": "Удалить"
}
```

`nav.cards`: «Мои карты»; `balance.pending`: «Ожидает зачисления: {sum}»; `balance.kind.sale_credit`: «Продажа скинов»; `balance.kind.payout_return`: «Выплата на баланс».

`uz`:

```json
"sales": {
  "number": "#{number} sotuv",
  "back": "Almashuvlarga",
  "openOffer": "Steamʼda almashuvni ochish",
  "fee": "Kartaga oʻtkazish komissiyasi",
  "bonus": "Balans uchun bonus",
  "more": "Yana koʻrsatish",
  "notFound": "Sotuv topilmadi.",
  "loadFailed": "Sotuvni yuklab boʻlmadi. Sahifani yangilang.",
  "status": {
    "creating": "Almashuv tayyorlanmoqda",
    "offered": "Almashuvni qabul qiling",
    "hold": "7 kun kutamiz",
    "credited": "Balansda",
    "payout": "Kartaga yuborilmoqda",
    "closed": "Amalga oshmadi",
    "reverted": "Almashuv bekor qilindi"
  },
  "payout": {
    "waiting_hold": "7 kun kutamiz",
    "to_pay": "Kartaga yuborilmoqda",
    "paid": "Kartaga yuborildi",
    "rejected": "Balansda",
    "canceled": "Amalga oshmadi"
  },
  "state": {
    "creating": { "title": "Almashuv tayyorlanmoqda", "text": "Bir daqiqada Steamʼga almashuv taklifi keladi." },
    "offered": { "title": "Almashuvni qabul qiling", "text": "{bot} Steamʼda taklif yubordi. Uni {time} gacha qabul qiling." },
    "hold": { "title": "Skinlar qabul qilindi", "text": "{amount} {date} tushadi." },
    "credited": { "title": "Pul balansda", "text": "{amount} csmarket balansiga oʻtkazildi." },
    "payout": { "title": "Pul yuborilmoqda", "text": "Tez orada {amount} ni {card} kartasiga yuboramiz." },
    "paid": { "title": "Pul yuborildi", "text": "{amount} {card} kartasiga yuborildi." },
    "rejected": { "title": "Pul balansda", "text": "Kartaga oʻtkazma oʻtmadi — {amount} csmarket balansiga oʻtkazildi." },
    "closed": { "title": "Sotuv amalga oshmadi", "text": "Almashuv amalga oshmadi, skinlar sizda qoldi." },
    "reverted": { "title": "Almashuv bekor qilindi", "text": "Almashuv Steamʼda bekor qilindi — bu sotuv uchun pul hisoblanmaydi." }
  }
},
"cards": {
  "title": "Kartalarim",
  "empty": "Hozircha karta yoʻq. Kartani skin sotishda qoʻshish mumkin.",
  "loadFailed": "Kartalarni yuklab boʻlmadi. Sahifani yangilang.",
  "delete": "{name} ni oʻchirish",
  "deleteShort": "Oʻchirish"
}
```

`nav.cards`: «Kartalarim»; `balance.pending`: «Tushishi kutilmoqda: {sum}»; `balance.kind.sale_credit`: «Skin sotuvi»; `balance.kind.payout_return`: «Balansga toʻlov».

`en`:

```json
"sales": {
  "number": "Sale #{number}",
  "back": "To trades",
  "openOffer": "Open the trade in Steam",
  "fee": "Card transfer fee",
  "bonus": "Balance bonus",
  "more": "Show more",
  "notFound": "Sale not found.",
  "loadFailed": "Could not load the sale. Refresh the page.",
  "status": {
    "creating": "Preparing the trade",
    "offered": "Accept the trade",
    "hold": "Waiting 7 days",
    "credited": "On the balance",
    "payout": "Sending to the card",
    "closed": "Did not go through",
    "reverted": "Trade reversed"
  },
  "payout": {
    "waiting_hold": "Waiting 7 days",
    "to_pay": "Sending to the card",
    "paid": "Sent to the card",
    "rejected": "On the balance",
    "canceled": "Did not go through"
  },
  "state": {
    "creating": { "title": "Preparing the trade", "text": "A trade offer will arrive in Steam within a minute." },
    "offered": { "title": "Accept the trade", "text": "{bot} sent you an offer in Steam. Accept it by {time}." },
    "hold": { "title": "Skins received", "text": "{amount} will arrive on {date}." },
    "credited": { "title": "Money on your balance", "text": "{amount} is on your csmarket balance." },
    "payout": { "title": "Sending the money", "text": "We will send {amount} to the card {card} soon." },
    "paid": { "title": "Money sent", "text": "{amount} was sent to the card {card}." },
    "rejected": { "title": "Money on your balance", "text": "The card transfer failed — {amount} is on your csmarket balance." },
    "closed": { "title": "The sale did not go through", "text": "The trade did not happen; your skins stay with you." },
    "reverted": { "title": "Trade reversed", "text": "The trade was reversed in Steam — nothing is paid for this sale." }
  }
},
"cards": {
  "title": "My cards",
  "empty": "No cards yet. You can add one when you sell skins.",
  "loadFailed": "Could not load your cards. Refresh the page.",
  "delete": "Delete {name}",
  "deleteShort": "Delete"
}
```

`nav.cards`: «My cards»; `balance.pending`: «On its way: {sum}»; `balance.kind.sale_credit`: «Skins sold»; `balance.kind.payout_return`: «Payout to balance».

- [ ] **Step 9: Run the tests and the checks**

Run: `pnpm --filter @csmarket/web exec vitest run src/lib/sales.test.ts src/components/sale src/components/account src/components/trades src/components/header src/components/balance src/lib/realtime.test.ts src/hooks && pnpm --filter @csmarket/i18n exec vitest run && pnpm --filter @csmarket/web exec tsc --noEmit && pnpm --filter @csmarket/web exec eslint src/lib src/components/sale src/components/account src/components/trades src/components/header src/components/balance src/hooks "src/app/[locale]/account" --max-warnings 0 && npx prettier --write apps/web/src packages/i18n/locales`
Expected: PASS; clean.

- [ ] **Step 10: Commit**

```bash
git add apps/web/src packages/i18n/locales
git commit -m "feat(web/account): the sale page, sales in «Обмены», «Мои карты», money on its way, live updates" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Admin SPA — «Выкуп»: payout requests, sales, the settings editor, the dashboard tile

**Files:**

- Create: `apps/admin/src/features/sales/api.ts`, `keys.ts`, `labels.ts`, `fixtures.ts`, `PayoutsPage.tsx`, `PayoutDetail.tsx`, `SalesPage.tsx`, `SaleDetail.tsx`, `SaleSettingsPage.tsx`, `PayoutsPage.test.tsx`, `PayoutDetail.test.tsx`, `SaleSettingsPage.test.tsx`
- Modify: `apps/admin/src/app/router.tsx`, `apps/admin/src/app/Layout.tsx` (a «Выкуп» group), `apps/admin/src/app/Layout.test.tsx` (the nav list)
- Modify: `apps/admin/src/features/dashboard/api.ts`, `DashboardPage.tsx`, `DashboardPage.test.tsx` (the «К выплате» tile)
- Modify: `apps/admin/src/features/users/labels.ts` (the two entry kinds)

**Interfaces:**

- Consumes: the `/api/v1/admin/sales*` routes and `DashboardOut.payouts` (Task 12); `session` (`@/lib/api`), `useIdempotencyKey` (`@/features/users/useIdempotencyKey`), `errorText` (`@/features/users/labels`), `formatSum`, `formatDateTime`, `useUrlParams`, `pick`.
- Produces routes: `/payouts`, `/payouts/:id`, `/sales`, `/sales/:number`, `/sale-settings`.

- [ ] **Step 1: Write the failing tests**

```ts
// apps/admin/src/features/sales/fixtures.ts
import { type PayoutDetail, type PayoutRow, type SaleSettingsOut } from "./api";

export const PAYOUT_ROW: PayoutRow = {
  id: "p-1",
  sale_number: "S7K2M9QX",
  user: { id: "u-1", display_name: "Ivan" },
  card_type: "humo",
  card_masked: "•••• 9015",
  amount_uzs: "147400",
  fee_uzs: "7800",
  status: "to_pay",
  to_pay_at: "2026-10-15T10:00:00Z",
  paid_at: null,
  created_at: "2026-10-08T10:00:00Z",
};

export const PAYOUT_DETAIL: PayoutDetail = {
  request: PAYOUT_ROW,
  note: null,
  reject_reason: null,
  decided_by: null,
  sale: {
    number: "S7K2M9QX",
    status: "payout",
    user: { id: "u-1", display_name: "Ivan" },
    payout_to: "card",
    card_type: "humo",
    card_masked: "•••• 9015",
    quoted_usd: "12.95",
    amount_usd: "12.83",
    items_uzs: "155200",
    bonus_uzs: "0",
    fee_uzs: "7800",
    payout_uzs: "147400",
    rate: "12650.5",
    margin_usd: "0.6735",
    trade_id: 178,
    trade_offer_id: "6912345678",
    bot_name: "Bot #3",
    offer_expiry_at: null,
    hold_end_at: "2026-10-15T10:00:00Z",
    fail_reason: null,
    attention_reason: null,
    credited_at: null,
    created_at: "2026-10-08T10:00:00Z",
    updated_at: "2026-10-15T10:00:00Z",
    items: [
      {
        asset_id: "100",
        name: "AK-47 | Redline (Field-Tested)",
        price_usd: "12.45",
        price_uzs: "149600",
      },
      {
        asset_id: "101",
        name: "P250 | Sand Dune (Field-Tested)",
        price_usd: "0.5",
        price_uzs: "5600",
      },
    ],
    payout: PAYOUT_ROW,
  },
  history_sales: [],
  history_payouts: [PAYOUT_ROW],
  can_decide: true,
};

export const SETTINGS: SaleSettingsOut = {
  settings: {
    enabled: false,
    margin: [
      { from_usd: "0", percent: "10" },
      { from_usd: "1", percent: "5" },
      { from_usd: "10", percent: "3" },
      { from_usd: "100", percent: "2" },
    ],
    rate_cut_pct: "0",
    balance_bonus_pct: "2",
    card_fee_pct: { uzcard: "5", humo: "5", uzum_visa: "5" },
    card_min_uzs: 30000,
    min_sum_usd: "1",
  },
  updated_at: null,
  updated_by: null,
  rate_uzs: "12650.5",
};
```

```tsx
// apps/admin/src/features/sales/PayoutsPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_ROW } from "./fixtures";
import { PayoutsPage } from "./PayoutsPage";

const api = vi.hoisted(() => ({ listPayouts: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderPage(url = "/payouts") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <PayoutsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PayoutsPage", () => {
  beforeEach(() => {
    api.listPayouts.mockReset().mockResolvedValue({
      items: [PAYOUT_ROW],
      counts: { to_pay: 1, waiting_hold: 2, paid: 5, rejected: 0, canceled: 1 },
      next_cursor: null,
    });
  });

  it("opens on «К выплате» with every tab's count", async () => {
    renderPage();
    expect(await screen.findByRole("link", { name: "К выплате 1" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Ждут 7 дней 2" })).toHaveAttribute(
      "href",
      "/payouts?status=waiting_hold",
    );
    expect(api.listPayouts).toHaveBeenCalledWith("to_pay", undefined);
  });

  it("shows the sale, the user, the masked card, the amount and since when", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(link).toHaveAttribute("href", "/payouts/p-1");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("Humo •••• 9015")).toBeInTheDocument();
    expect(within(row).getByText(/147\s400 сум/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
  });

  it("reads the tab from the URL", async () => {
    renderPage("/payouts?status=paid");
    await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(api.listPayouts).toHaveBeenCalledWith("paid", undefined);
  });
});
```

```tsx
// apps/admin/src/features/sales/PayoutDetail.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL } from "./fixtures";
import { PayoutDetail } from "./PayoutDetail";

const api = vi.hoisted(() => ({
  getPayout: vi.fn(),
  revealCard: vi.fn(),
  markPaid: vi.fn(),
  rejectPayout: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/payouts/p-1"]}>
        <Routes>
          <Route path="/payouts/:id" element={<PayoutDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PayoutDetail", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getPayout.mockResolvedValue(PAYOUT_DETAIL);
    api.revealCard.mockResolvedValue({ number: "9860123456789015" });
  });

  it("shows the masked card and the money breakdown, never the number by itself", async () => {
    renderPage();
    expect(await screen.findByText("Humo •••• 9015")).toBeInTheDocument();
    expect(screen.getByText(/155\s200 сум/)).toBeInTheDocument();
    expect(screen.getByText(/−7\s800 сум/)).toBeInTheDocument();
    expect(screen.queryByText(/9860 1234 5678 9015/)).toBeNull();
  });

  it("«Показать» asks the audited reveal", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    expect(await screen.findByText("9860 1234 5678 9015")).toBeInTheDocument();
    expect(api.revealCard).toHaveBeenCalledWith("p-1", "show");
  });

  it("«Скопировать» reveals for a copy and puts the digits on the clipboard", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Скопировать номер" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("9860123456789015");
    });
    expect(api.revealCard).toHaveBeenCalledWith("p-1", "copy");
  });

  it("«Выплачено» sends the note with a key after a confirm", async () => {
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Выплачено" }));
    fireEvent.change(screen.getByLabelText("Комментарий"), { target: { value: "Click #1" } });
    fireEvent.click(screen.getByRole("button", { name: "Да, выплачено" }));
    await waitFor(() => {
      expect(api.markPaid).toHaveBeenCalledWith(
        "p-1",
        "Click #1",
        expect.stringMatching(/^admin-payout-paid-/),
      );
    });
  });

  it("«Отклонить» needs a reason", async () => {
    api.rejectPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отклонить" }));
    const confirm = screen.getByRole("button", { name: "Да, отклонить" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина"), {
      target: { value: "Карта заблокирована" },
    });
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(api.rejectPayout).toHaveBeenCalledWith(
        "p-1",
        "Карта заблокирована",
        expect.stringMatching(/^admin-payout-reject-/),
      );
    });
  });

  it("hides the actions when the request can no longer be decided", async () => {
    api.getPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    await screen.findByText("Humo •••• 9015");
    expect(screen.queryByRole("button", { name: "Выплачено" })).toBeNull();
  });
});
```

```tsx
// apps/admin/src/features/sales/SaleSettingsPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SETTINGS } from "./fixtures";
import { SaleSettingsPage } from "./SaleSettingsPage";

const api = vi.hoisted(() => ({ getSaleSettings: vi.fn(), saveSaleSettings: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SaleSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SaleSettingsPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getSaleSettings.mockResolvedValue(SETTINGS);
    api.saveSaleSettings.mockResolvedValue(SETTINGS);
  });

  it("saves the edited document with a key after a confirm", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Выкуп включён"));
    fireEvent.change(screen.getByLabelText("Минимум на карту, сум"), {
      target: { value: "50000" },
    });
    fireEvent.change(screen.getByLabelText("Комиссия Humo, %"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, сохранить" }));
    await waitFor(() => {
      expect(api.saveSaleSettings).toHaveBeenCalledOnce();
    });
    const [doc, key] = api.saveSaleSettings.mock.calls[0] as [Record<string, unknown>, string];
    expect(doc).toMatchObject({
      enabled: true,
      card_min_uzs: 50000,
      card_fee_pct: { uzcard: "5", humo: "1.5", uzum_visa: "5" },
    });
    expect(key).toMatch(/^admin-sale-settings-/);
  });

  it("adds and removes a margin bracket", async () => {
    renderPage();
    await screen.findByLabelText("Выкуп включён");
    expect(screen.getAllByLabelText(/^От, \$/)).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Добавить диапазон" }));
    expect(screen.getAllByLabelText(/^От, \$/)).toHaveLength(5);
    fireEvent.click(screen.getAllByRole("button", { name: "Убрать диапазон" })[4] as HTMLElement);
    expect(screen.getAllByLabelText(/^От, \$/)).toHaveLength(4);
  });
});
```

In `features/dashboard/DashboardPage.test.tsx`, `DATA` gains `payouts: { to_pay_count: 2, to_pay_uzs: "310400" },` and a test:

```tsx
it("shows the card payouts to pay as a link to the queue", async () => {
  api.getDashboard.mockResolvedValue(DATA);
  renderPage();
  const tile = await screen.findByTestId("tile-К выплате");
  expect(within(tile).getByRole("link")).toHaveAttribute("href", "/payouts");
  expect(tile).toHaveTextContent(/2/);
  expect(tile).toHaveTextContent(/310\s400 сум/);
});
```

(`renderPage` is that file's render helper.)

- [ ] **Step 2: Run them**

Run: `pnpm --filter @csmarket/admin exec vitest run src/features/sales src/features/dashboard`
Expected: FAIL — `./api` and the pages do not exist; the dashboard has no «К выплате».

- [ ] **Step 3: `api.ts`, `keys.ts`, `labels.ts`**

```ts
// apps/admin/src/features/sales/api.ts
/** Admin «Выкуп» API: thin typed wrappers over `/api/v1/admin/sales`. Mirrors the API's schemas. */
import { session } from "@/lib/api";

const BASE = "/api/v1/admin/sales";

export type CardType = "uzcard" | "humo" | "uzum_visa";
export type SaleStatus =
  "creating" | "offered" | "hold" | "credited" | "payout" | "closed" | "reverted";
export type PayoutStatus = "to_pay" | "waiting_hold" | "paid" | "rejected" | "canceled";

/** The card types in the order the settings form lists them. */
export const CARD_TYPES_ORDER: readonly CardType[] = ["uzcard", "humo", "uzum_visa"];

/** The tabs, in the order the queue shows them; «К выплате» first. */
export const PAYOUT_STATUSES: readonly PayoutStatus[] = [
  "to_pay",
  "waiting_hold",
  "paid",
  "rejected",
  "canceled",
];
export const SALE_STATUSES: readonly SaleStatus[] = [
  "creating",
  "offered",
  "hold",
  "credited",
  "payout",
  "closed",
  "reverted",
];

export interface AdminUser {
  id: string;
  display_name: string | null;
}

export interface PayoutRow {
  id: string;
  sale_number: string;
  user: AdminUser;
  card_type: CardType;
  /** `•••• 9015` — never the number. */
  card_masked: string;
  amount_uzs: string;
  fee_uzs: string;
  status: PayoutStatus;
  to_pay_at: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface PayoutsPage {
  items: PayoutRow[];
  counts: Record<PayoutStatus, number>;
  next_cursor: string | null;
}

export interface AdminSaleItem {
  asset_id: string;
  name: string;
  price_usd: string;
  price_uzs: string;
}

export interface AdminSaleRow {
  number: string;
  status: SaleStatus;
  user: AdminUser;
  payout_to: "balance" | "card";
  quoted_usd: string;
  payout_uzs: string;
  margin_usd: string;
  attention_reason: string | null;
  created_at: string;
}

export interface AdminSalesPage {
  items: AdminSaleRow[];
  next_cursor: string | null;
}

export interface AdminSale {
  number: string;
  status: SaleStatus;
  user: AdminUser;
  payout_to: "balance" | "card";
  card_type: CardType | null;
  card_masked: string | null;
  quoted_usd: string;
  amount_usd: string | null;
  items_uzs: string;
  bonus_uzs: string;
  fee_uzs: string;
  payout_uzs: string;
  rate: string;
  margin_usd: string;
  trade_id: number | null;
  trade_offer_id: string | null;
  bot_name: string | null;
  offer_expiry_at: string | null;
  hold_end_at: string | null;
  fail_reason: string | null;
  attention_reason: string | null;
  credited_at: string | null;
  created_at: string;
  updated_at: string;
  items: AdminSaleItem[];
  payout: PayoutRow | null;
}

export interface PayoutDetail {
  request: PayoutRow;
  note: string | null;
  reject_reason: string | null;
  decided_by: AdminUser | null;
  sale: AdminSale;
  history_sales: AdminSaleRow[];
  history_payouts: PayoutRow[];
  can_decide: boolean;
}

export interface Bracket {
  from_usd: string;
  percent: string;
}

/** The sale-settings document; decimals travel as strings. */
export interface SaleSettings {
  enabled: boolean;
  margin: Bracket[];
  rate_cut_pct: string;
  balance_bonus_pct: string;
  card_fee_pct: Record<CardType, string>;
  card_min_uzs: number;
  min_sum_usd: string;
}

export interface SaleSettingsOut {
  settings: SaleSettings;
  updated_at: string | null;
  updated_by: AdminUser | null;
  rate_uzs: string | null;
}

export function listPayouts(status: PayoutStatus, cursor?: string): Promise<PayoutsPage> {
  const params = new URLSearchParams({ status });
  if (cursor) params.set("cursor", cursor);
  return session.apiGet<PayoutsPage>(`${BASE}/payouts?${params.toString()}`);
}

export function getPayout(id: string): Promise<PayoutDetail> {
  return session.apiGet<PayoutDetail>(`${BASE}/payouts/${encodeURIComponent(id)}`);
}

/** The full card number (audited on the API side). Never keep it beyond the page. */
export function revealCard(id: string, purpose: "show" | "copy"): Promise<{ number: string }> {
  return session.apiPost<{ number: string }>(`${BASE}/payouts/${encodeURIComponent(id)}/reveal`, {
    purpose,
  });
}

export function markPaid(id: string, note: string | null, key: string): Promise<PayoutDetail> {
  return session.apiPost<PayoutDetail>(
    `${BASE}/payouts/${encodeURIComponent(id)}/paid`,
    { note },
    { idempotencyKey: key },
  );
}

export function rejectPayout(id: string, reason: string, key: string): Promise<PayoutDetail> {
  return session.apiPost<PayoutDetail>(
    `${BASE}/payouts/${encodeURIComponent(id)}/reject`,
    { reason },
    { idempotencyKey: key },
  );
}

export interface ListSalesParams {
  status?: SaleStatus;
  q?: string;
  cursor?: string;
}

export function listSales(p: ListSalesParams): Promise<AdminSalesPage> {
  const params = new URLSearchParams();
  if (p.status) params.set("status", p.status);
  if (p.q) params.set("q", p.q);
  if (p.cursor) params.set("cursor", p.cursor);
  return session.apiGet<AdminSalesPage>(`${BASE}?${params.toString()}`);
}

export function getSale(number: string): Promise<AdminSale> {
  return session.apiGet<AdminSale>(`${BASE}/${encodeURIComponent(number)}`);
}

export function getSaleSettings(): Promise<SaleSettingsOut> {
  return session.apiGet<SaleSettingsOut>(`${BASE}/settings`);
}

export function saveSaleSettings(doc: SaleSettings, key: string): Promise<SaleSettingsOut> {
  return session.apiPut<SaleSettingsOut>(`${BASE}/settings`, doc, { idempotencyKey: key });
}
```

```ts
// apps/admin/src/features/sales/keys.ts
/** Query keys of the «Выкуп» area, shared by the pages that read and the actions that write. */

export const PAYOUTS_KEY = ["admin", "sales", "payouts"] as const;
export const payoutKey = (id: string) => ["admin", "sales", "payout", id] as const;
export const SALES_LIST_KEY = ["admin", "sales", "list"] as const;
export const saleKey = (number: string) => ["admin", "sales", "one", number] as const;
export const SALE_SETTINGS_KEY = ["admin", "sales", "settings"] as const;
```

```ts
// apps/admin/src/features/sales/labels.ts
/** «Выкуп»'s words for the operator (Russian). */
import { type CardType, type PayoutStatus, type SaleStatus } from "./api";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";

export const PAYOUT_LABELS: Record<PayoutStatus, string> = {
  to_pay: "К выплате",
  waiting_hold: "Ждут 7 дней",
  paid: "Выплачено",
  rejected: "Отклонено",
  canceled: "Отменено",
};

export const SALE_LABELS: Record<SaleStatus, string> = {
  creating: "создаётся",
  offered: "обмен отправлен",
  hold: "холд 7 дней",
  credited: "зачислено на баланс",
  payout: "выплата на карту",
  closed: "закрыта",
  reverted: "откат обмена",
};

export const ATTENTION_LABELS: Record<string, string> = {
  rolled_back: "откат после выплаты — разобрать вручную",
  late_deposit: "закрыта, но Skinslink видит обмен — разобрать вручную",
};

export const CARD_BRANDS: Record<CardType, string> = {
  uzcard: "Uzcard",
  humo: "Humo",
  uzum_visa: "Uzum Visa",
};

/** `•••• 9015` with the brand: «Humo •••• 9015». */
export function cardLabel(type: CardType | null, masked: string | null): string {
  return type && masked ? `${CARD_BRANDS[type]} ${masked}` : "—";
}

/** 16 digits grouped by four. */
export function groupDigits(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

export function payoutErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code === "payout_not_payable") {
    return "Заявку уже нельзя изменить — страница обновлена.";
  }
  return errorText(err);
}
```

- [ ] **Step 4: The pages**

```tsx
// apps/admin/src/features/sales/PayoutsPage.tsx
/** «Заявки на выплату»: status tabs with counts («К выплате» first), newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listPayouts, PAYOUT_STATUSES, type PayoutRow, type PayoutsPage as Page } from "./api";
import { PAYOUTS_KEY } from "./keys";
import { cardLabel, PAYOUT_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

function Row({ row }: { row: PayoutRow }) {
  return (
    <tr className="border-border border-t">
      <td className="py-2 pr-3">
        <Link to={`/payouts/${row.id}`} className="font-mono font-medium hover:underline">
          {row.sale_number}
        </Link>
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${row.user.id}`} className="hover:underline">
          {row.user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="py-2 pr-3">{cardLabel(row.card_type, row.card_masked)}</td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatSum(row.amount_uzs)}
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2">
        {row.to_pay_at ? formatDateTime(row.to_pay_at) : "—"}
      </td>
    </tr>
  );
}

export function PayoutsPage() {
  const url = useUrlParams();
  const status = pick(PAYOUT_STATUSES, url.get("status")) ?? "to_pay";
  const query = useInfiniteQuery<
    Page,
    Error,
    InfiniteData<Page, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...PAYOUTS_KEY, status],
    queryFn: ({ pageParam }) => listPayouts(status, pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const counts = query.data?.pages[0]?.counts;
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Заявки на выплату</h1>
      <nav aria-label="Статусы" className="flex flex-wrap gap-2">
        {PAYOUT_STATUSES.map((s) => (
          <Link
            key={s}
            to={`/payouts?status=${s}`}
            aria-current={s === status ? "page" : undefined}
            className={
              s === status
                ? "bg-accent text-accent-fg rounded-md px-3 py-1.5 text-sm"
                : "bg-surface-2 rounded-md px-3 py-1.5 text-sm"
            }
          >
            {PAYOUT_LABELS[s]} {counts?.[s] ?? 0}
          </Link>
        ))}
      </nav>
      {query.isError ? (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      ) : query.isPending ? (
        <p className="text-fg-muted">Загрузка…</p>
      ) : items.length === 0 ? (
        <p className="text-fg-muted">Заявок нет.</p>
      ) : (
        <table className="w-full text-sm" data-testid="payouts-table">
          <thead className="text-fg-muted text-left">
            <tr>
              <th className="py-2 pr-3 font-medium">Продажа</th>
              <th className="py-2 pr-3 font-medium">Пользователь</th>
              <th className="py-2 pr-3 font-medium">Карта</th>
              <th className="py-2 pr-3 text-right font-medium">Сумма</th>
              <th className="py-2 font-medium">К выплате с</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <Row key={row.id} row={row} />
            ))}
          </tbody>
        </table>
      )}
      {query.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          onClick={() => void query.fetchNextPage()}
        >
          Показать ещё
        </Button>
      ) : null}
    </div>
  );
}
```

```tsx
// apps/admin/src/features/sales/PayoutDetail.tsx
/**
 * «Заявка на выплату»: the card (masked; «Показать номер» / «Скопировать номер» go through the
 * audited reveal, the number lives only in this page's state), the money, the items, the
 * seller's history, and «Выплачено» / «Отклонить» behind a confirm, one key per submission.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getPayout, markPaid, type PayoutDetail as Detail, rejectPayout, revealCard } from "./api";
import { PAYOUTS_KEY, payoutKey } from "./keys";
import { cardLabel, groupDigits, PAYOUT_LABELS, payoutErrorText, SALE_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime, formatSum } from "@/lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-44 shrink-0">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function CardBlock({ detail }: { detail: Detail }) {
  const [number, setNumber] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const show = useMutation({
    mutationFn: () => revealCard(detail.request.id, "show"),
    onSuccess: (r) => {
      setNumber(r.number);
    },
  });
  const copy = useMutation({
    mutationFn: async () => {
      const r = await revealCard(detail.request.id, "copy");
      await navigator.clipboard.writeText(r.number);
    },
    onSuccess: () => {
      setCopied(true);
    },
  });
  return (
    <section className="border-border flex flex-col gap-2 rounded-lg border p-4">
      <h2 className="font-semibold">Карта</h2>
      <p className="font-mono text-lg">
        {cardLabel(detail.request.card_type, detail.request.card_masked)}
      </p>
      {number !== null ? (
        <p className="font-mono text-lg tracking-wider">{groupDigits(number)}</p>
      ) : null}
      <div className="flex gap-2">
        <Button variant="secondary" disabled={show.isPending} onClick={() => show.mutate()}>
          Показать номер
        </Button>
        <Button variant="secondary" disabled={copy.isPending} onClick={() => copy.mutate()}>
          Скопировать номер
        </Button>
        {copied ? <span className="text-fg-muted self-center text-sm">Скопировано</span> : null}
      </div>
      {show.isError || copy.isError ? (
        <p role="alert" className="text-danger text-sm">
          {errorText(show.error ?? copy.error)}
        </p>
      ) : null}
    </section>
  );
}

type Panel = "none" | "paid" | "reject";

function Actions({ detail, onStale }: { detail: Detail; onStale: () => void }) {
  const qc = useQueryClient();
  const id = detail.request.id;
  const [panel, setPanel] = useState<Panel>("none");
  const [text, setText] = useState("");
  const paidKey = useIdempotencyKey("admin-payout-paid");
  const rejectKey = useIdempotencyKey("admin-payout-reject");
  const act = useMutation({
    mutationFn: (p: Exclude<Panel, "none">): Promise<Detail> => {
      const value = text.trim();
      return p === "paid"
        ? markPaid(id, value || null, paidKey.keyFor(JSON.stringify({ id, value })))
        : rejectPayout(id, value, rejectKey.keyFor(JSON.stringify({ id, value })));
    },
    onSuccess: (next, p) => {
      (p === "paid" ? paidKey : rejectKey).reset();
      qc.setQueryData(payoutKey(id), next);
      void qc.invalidateQueries({ queryKey: PAYOUTS_KEY });
      setPanel("none");
      setText("");
    },
    onError: () => {
      onStale();
    },
  });
  if (!detail.can_decide) return null;
  return (
    <section className="flex flex-col gap-3">
      <div className="flex gap-2">
        <Button onClick={() => setPanel("paid")}>Выплачено</Button>
        <Button variant="secondary" onClick={() => setPanel("reject")}>
          Отклонить
        </Button>
      </div>
      {panel !== "none" ? (
        <div
          role="group"
          aria-label="Подтверждение"
          className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4"
        >
          <label className="flex flex-col gap-1 text-sm">
            {panel === "paid" ? "Комментарий" : "Причина"}
            <textarea
              maxLength={500}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
              className="border-border bg-bg rounded-md border p-2"
            />
          </label>
          {panel === "reject" ? (
            <p className="text-fg-muted text-sm">
              {formatSum(Number(detail.request.amount_uzs) + Number(detail.request.fee_uzs))} будут
              зачислены на баланс пользователя.
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button
              disabled={act.isPending || (panel === "reject" && text.trim() === "")}
              onClick={() => act.mutate(panel)}
            >
              {panel === "paid" ? "Да, выплачено" : "Да, отклонить"}
            </Button>
            <Button variant="secondary" onClick={() => setPanel("none")}>
              Отмена
            </Button>
          </div>
          {act.isError ? (
            <p role="alert" className="text-danger text-sm">
              {payoutErrorText(act.error)}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function PayoutDetail() {
  const { id = "" } = useParams();
  const detail = useQuery({ queryKey: payoutKey(id), queryFn: () => getPayout(id) });
  if (detail.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(detail.error)}
      </p>
    );
  }
  if (!detail.data) return <p className="text-fg-muted">Загрузка…</p>;
  const d = detail.data;
  const s = d.sale;
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">
          Выплата по продаже{" "}
          <Link to={`/sales/${s.number}`} className="font-mono hover:underline">
            {s.number}
          </Link>
        </h1>
        <p className="text-fg-muted">
          {PAYOUT_LABELS[d.request.status]} · {d.request.user.display_name ?? "Без имени"}
        </p>
      </header>
      <CardBlock detail={d} />
      <dl className="flex flex-col gap-1 text-sm">
        <Field label="Предметы">{formatSum(s.items_uzs)}</Field>
        <Field label="Комиссия карты">−{formatSum(s.fee_uzs)}</Field>
        <Field label="К выплате">{formatSum(d.request.amount_uzs)}</Field>
        <Field label="Skinslink платит нам">${s.amount_usd ?? s.quoted_usd}</Field>
        <Field label="Наша маржа">${s.margin_usd}</Field>
        <Field label="К выплате с">
          {d.request.to_pay_at ? formatDateTime(d.request.to_pay_at) : "—"}
        </Field>
        {d.note ? <Field label="Комментарий">{d.note}</Field> : null}
        {d.reject_reason ? <Field label="Причина отказа">{d.reject_reason}</Field> : null}
      </dl>
      <Actions detail={d} onStale={() => void detail.refetch()} />
      <section>
        <h2 className="mb-2 font-semibold">Предметы</h2>
        <ul className="text-sm">
          {s.items.map((i) => (
            <li key={i.asset_id} className="border-border flex justify-between border-t py-1.5">
              <span>{i.name}</span>
              <span className="tabular-nums">
                ${i.price_usd} · {formatSum(i.price_uzs)}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="mb-2 font-semibold">История пользователя</h2>
        <ul className="text-sm">
          {d.history_sales.map((h) => (
            <li key={h.number} className="border-border flex justify-between border-t py-1.5">
              <Link to={`/sales/${h.number}`} className="font-mono hover:underline">
                {h.number}
              </Link>
              <span>{SALE_LABELS[h.status]}</span>
              <span className="tabular-nums">{formatSum(h.payout_uzs)}</span>
            </li>
          ))}
          {d.history_payouts.map((h) => (
            <li key={h.id} className="border-border flex justify-between border-t py-1.5">
              <Link to={`/payouts/${h.id}`} className="font-mono hover:underline">
                {h.sale_number}
              </Link>
              <span>{PAYOUT_LABELS[h.status]}</span>
              <span className="tabular-nums">{formatSum(h.amount_uzs)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

```tsx
// apps/admin/src/features/sales/SalesPage.tsx
/** «Продажи»: find a sale by number, filter by status, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { type AdminSalesPage, listSales, SALE_STATUSES } from "./api";
import { SALES_LIST_KEY } from "./keys";
import { ATTENTION_LABELS, SALE_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

export function SalesPage() {
  const url = useUrlParams();
  const status = pick(SALE_STATUSES, url.get("status"));
  const q = upTo(url.get("q"), 8);
  const query = useInfiniteQuery<
    AdminSalesPage,
    Error,
    InfiniteData<AdminSalesPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...SALES_LIST_KEY, status ?? "", q],
    queryFn: ({ pageParam }) =>
      listSales({
        ...(status ? { status } : {}),
        ...(q ? { q } : {}),
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Продажи</h1>
      <div className="flex gap-2">
        <input
          aria-label="Номер продажи"
          placeholder="S…"
          maxLength={8}
          defaultValue={q}
          onChange={(e) => {
            url.set("q", e.target.value.trim());
          }}
          className="border-border bg-bg rounded-md border px-3 py-1.5"
        />
        <select
          aria-label="Статус"
          value={status ?? ""}
          onChange={(e) => {
            url.set("status", e.target.value);
          }}
          className="border-border bg-bg rounded-md border px-3 py-1.5"
        >
          <option value="">Все</option>
          {SALE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {SALE_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      {query.isError ? (
        <p role="alert" className="text-danger">
          {errorText(query.error)}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-fg-muted text-left">
            <tr>
              <th className="py-2 pr-3 font-medium">Номер</th>
              <th className="py-2 pr-3 font-medium">Статус</th>
              <th className="py-2 pr-3 font-medium">Пользователь</th>
              <th className="py-2 pr-3 text-right font-medium">Skinslink, $</th>
              <th className="py-2 pr-3 text-right font-medium">Выплата</th>
              <th className="py-2 pr-3 text-right font-medium">Маржа, $</th>
              <th className="py-2 font-medium">Создана</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.number} className="border-border border-t">
                <td className="py-2 pr-3">
                  <Link to={`/sales/${s.number}`} className="font-mono font-medium hover:underline">
                    {s.number}
                  </Link>
                </td>
                <td className="py-2 pr-3">
                  {SALE_LABELS[s.status]}
                  {s.attention_reason ? (
                    <div className="text-danger text-xs">
                      {ATTENTION_LABELS[s.attention_reason] ?? s.attention_reason}
                    </div>
                  ) : null}
                </td>
                <td className="py-2 pr-3">
                  <Link to={`/users/${s.user.id}`} className="hover:underline">
                    {s.user.display_name ?? "Без имени"}
                  </Link>
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{s.quoted_usd}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{formatSum(s.payout_uzs)}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{s.margin_usd}</td>
                <td className="text-fg-muted py-2">{formatDateTime(s.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {query.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          onClick={() => void query.fetchNextPage()}
        >
          Показать ещё
        </Button>
      ) : null}
    </div>
  );
}
```

```tsx
// apps/admin/src/features/sales/SaleDetail.tsx
/** «Продажа»: statuses, Skinslink's amount, our payout and margin, the items, the payout. */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { getSale } from "./api";
import { saleKey } from "./keys";
import { ATTENTION_LABELS, cardLabel, PAYOUT_LABELS, SALE_LABELS } from "./labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-44 shrink-0">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const at = (iso: string | null): string => (iso ? formatDateTime(iso) : "—");

export function SaleDetail() {
  const { number = "" } = useParams();
  const sale = useQuery({ queryKey: saleKey(number), queryFn: () => getSale(number) });
  if (sale.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(sale.error)}
      </p>
    );
  }
  if (!sale.data) return <p className="text-fg-muted">Загрузка…</p>;
  const s = sale.data;
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="font-mono text-2xl font-bold">{s.number}</h1>
      {s.attention_reason ? (
        <p role="alert" className="text-danger">
          {ATTENTION_LABELS[s.attention_reason] ?? s.attention_reason}
        </p>
      ) : null}
      <dl className="flex flex-col gap-1 text-sm">
        <Field label="Статус">{SALE_LABELS[s.status]}</Field>
        <Field label="Пользователь">
          <Link to={`/users/${s.user.id}`} className="hover:underline">
            {s.user.display_name ?? "Без имени"}
          </Link>
        </Field>
        <Field label="Куда">
          {s.payout_to === "card" ? cardLabel(s.card_type, s.card_masked) : "баланс"}
        </Field>
        <Field label="Skinslink: котировка">${s.quoted_usd}</Field>
        <Field label="Skinslink: зачисляет">
          {s.amount_usd !== null ? `$${s.amount_usd}` : "—"}
        </Field>
        <Field label="Курс">{s.rate}</Field>
        <Field label="Предметы">{formatSum(s.items_uzs)}</Field>
        {s.payout_to === "card" ? (
          <Field label="Комиссия карты">−{formatSum(s.fee_uzs)}</Field>
        ) : (
          <Field label="Бонус за баланс">+{formatSum(s.bonus_uzs)}</Field>
        )}
        <Field label="Выплата">{formatSum(s.payout_uzs)}</Field>
        <Field label="Наша маржа">${s.margin_usd}</Field>
        <Field label="Обмен Skinslink">{s.trade_id ?? "—"}</Field>
        <Field label="Оффер Steam">{s.trade_offer_id ?? "—"}</Field>
        <Field label="Бот">{s.bot_name ?? "—"}</Field>
        <Field label="Холд до">{at(s.hold_end_at)}</Field>
        <Field label="Причина закрытия">{s.fail_reason ?? "—"}</Field>
        <Field label="Зачислено">{at(s.credited_at)}</Field>
        <Field label="Создана">{at(s.created_at)}</Field>
        {s.payout ? (
          <Field label="Выплата на карту">
            <Link to={`/payouts/${s.payout.id}`} className="hover:underline">
              {PAYOUT_LABELS[s.payout.status]}
            </Link>
          </Field>
        ) : null}
      </dl>
      <section>
        <h2 className="mb-2 font-semibold">Предметы</h2>
        <ul className="text-sm">
          {s.items.map((i) => (
            <li key={i.asset_id} className="border-border flex justify-between border-t py-1.5">
              <span>{i.name}</span>
              <span className="tabular-nums">
                ${i.price_usd} · {formatSum(i.price_uzs)}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

```tsx
// apps/admin/src/features/sales/SaleSettingsPage.tsx
/** «Настройки выкупа»: the sale-settings document. A save affects new sales only; audited. */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { CARD_TYPES_ORDER, getSaleSettings, saveSaleSettings, type SaleSettings } from "./api";
import { SALE_SETTINGS_KEY } from "./keys";
import { CARD_BRANDS } from "./labels";

import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

interface NumberFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

function NumberField({ label, value, onChange }: NumberFieldProps) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        aria-label={label}
        inputMode="decimal"
        value={value}
        onChange={(e) => {
          onChange(e.target.value.trim());
        }}
        className="border-border bg-bg w-40 rounded-md border px-3 py-1.5 tabular-nums"
      />
    </label>
  );
}

export function SaleSettingsPage() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: SALE_SETTINGS_KEY, queryFn: getSaleSettings });
  const [draft, setDraft] = useState<SaleSettings | null>(null);
  const [confirming, setConfirming] = useState(false);
  const key = useIdempotencyKey("admin-sale-settings");
  const save = useMutation({
    mutationFn: (doc: SaleSettings) => saveSaleSettings(doc, key.keyFor(JSON.stringify(doc))),
    onSuccess: (out) => {
      key.reset();
      qc.setQueryData(SALE_SETTINGS_KEY, out);
      setDraft(null);
      setConfirming(false);
    },
  });
  if (settings.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(settings.error)}
      </p>
    );
  }
  if (!settings.data) return <p className="text-fg-muted">Загрузка…</p>;
  const doc = draft ?? settings.data.settings;
  const set = (patch: Partial<SaleSettings>) => {
    setDraft({ ...doc, ...patch });
  };
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">Настройки выкупа</h1>
        <p className="text-fg-muted text-sm">
          Курс ЦБ сейчас: {settings.data.rate_uzs ?? "нет"} · сохранено{" "}
          {settings.data.updated_at ? formatDateTime(settings.data.updated_at) : "никогда"}
          {settings.data.updated_by
            ? `, ${settings.data.updated_by.display_name ?? "без имени"}`
            : ""}
          . Новые настройки действуют на новые продажи.
        </p>
      </header>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          aria-label="Выкуп включён"
          checked={doc.enabled}
          onChange={(e) => {
            set({ enabled: e.target.checked });
          }}
        />
        Выкуп включён
      </label>
      <section className="flex flex-col gap-2">
        <h2 className="font-semibold">Маржа по диапазонам цены Skinslink</h2>
        {doc.margin.map((b, i) => (
          <div key={i} className="flex items-end gap-2">
            <NumberField
              label={`От, $ (${String(i + 1)})`}
              value={b.from_usd}
              onChange={(v) => {
                set({ margin: doc.margin.map((x, j) => (j === i ? { ...x, from_usd: v } : x)) });
              }}
            />
            <NumberField
              label={`Маржа, % (${String(i + 1)})`}
              value={b.percent}
              onChange={(v) => {
                set({ margin: doc.margin.map((x, j) => (j === i ? { ...x, percent: v } : x)) });
              }}
            />
            <Button
              variant="secondary"
              aria-label="Убрать диапазон"
              disabled={doc.margin.length === 1}
              onClick={() => {
                set({ margin: doc.margin.filter((_, j) => j !== i) });
              }}
            >
              ×
            </Button>
          </div>
        ))}
        <Button
          variant="secondary"
          className="self-start"
          onClick={() => {
            set({ margin: [...doc.margin, { from_usd: "", percent: "" }] });
          }}
        >
          Добавить диапазон
        </Button>
      </section>
      <section className="flex flex-wrap gap-4">
        <NumberField
          label="Скидка с курса ЦБ, %"
          value={doc.rate_cut_pct}
          onChange={(v) => set({ rate_cut_pct: v })}
        />
        <NumberField
          label="Бонус за баланс, %"
          value={doc.balance_bonus_pct}
          onChange={(v) => set({ balance_bonus_pct: v })}
        />
        {CARD_TYPES_ORDER.map((t) => (
          <NumberField
            key={t}
            label={`Комиссия ${CARD_BRANDS[t]}, %`}
            value={doc.card_fee_pct[t]}
            onChange={(v) => set({ card_fee_pct: { ...doc.card_fee_pct, [t]: v } })}
          />
        ))}
        <NumberField
          label="Минимум на карту, сум"
          value={String(doc.card_min_uzs)}
          onChange={(v) => set({ card_min_uzs: Number(v) || 0 })}
        />
        <NumberField
          label="Минимальная сумма, $"
          value={doc.min_sum_usd}
          onChange={(v) => set({ min_sum_usd: v })}
        />
      </section>
      <div className="flex gap-2">
        <Button disabled={draft === null || save.isPending} onClick={() => setConfirming(true)}>
          Сохранить
        </Button>
        <Button variant="secondary" disabled={draft === null} onClick={() => setDraft(null)}>
          Сбросить
        </Button>
      </div>
      {confirming ? (
        <div className="border-warning bg-surface flex flex-wrap items-center gap-3 rounded-lg border p-4">
          <span>Сохранить? Действует на новые продажи.</span>
          <Button disabled={save.isPending} onClick={() => save.mutate(doc)}>
            Да, сохранить
          </Button>
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            Отмена
          </Button>
        </div>
      ) : null}
      {save.isError ? (
        <p role="alert" className="text-danger">
          {errorText(save.error)}
        </p>
      ) : null}
    </div>
  );
}
```

`features/users/labels.ts`, `KINDS`: add `sale_credit: "Продажа скинов",` and `payout_return: "Выплата на баланс",`.

- [ ] **Step 5: The routes, the nav, the dashboard tile**

`app/router.tsx`: import the five pages and add under the layout's children, before `"*"`:

```tsx
          { path: "/payouts", element: <PayoutsPage /> },
          { path: "/payouts/:id", element: <PayoutDetail /> },
          { path: "/sales", element: <SalesPage /> },
          { path: "/sales/:number", element: <SaleDetail /> },
          { path: "/sale-settings", element: <SaleSettingsPage /> },
```

`app/Layout.tsx`: `HandCoins`, `Wallet` and `Settings2` join the lucide import, and a group after «Операции»:

```tsx
  {
    label: "Выкуп",
    items: [
      { to: "/payouts", label: "Заявки на выплату", icon: Wallet },
      { to: "/sales", label: "Продажи", icon: HandCoins },
      { to: "/sale-settings", label: "Настройки выкупа", icon: Settings2 },
    ],
  },
```

`app/Layout.test.tsx`, «a left sidebar lists every page…»: the expected list gains `"Заявки на выплату", "Продажи", "Настройки выкупа",` after `"Платежи",`.

`features/dashboard/api.ts`, `DashboardOut`: `payouts: { to_pay_count: number; to_pay_uzs: string };`.

`features/dashboard/DashboardPage.tsx`: import `formatSum` from `@/lib/format`, and after the «Требуют внимания» tile:

```tsx
<Tile title="К выплате">
  <Link
    to="/payouts"
    className={data.payouts.to_pay_count > 0 ? "text-danger underline" : "underline"}
  >
    {data.payouts.to_pay_count}
  </Link>
  <span className="text-fg-muted text-sm">{formatSum(data.payouts.to_pay_uzs)}</span>
</Tile>
```

- [ ] **Step 6: Run the tests and the checks**

Run: `pnpm --filter @csmarket/admin exec vitest run src/features/sales src/features/dashboard src/app src/features/users && pnpm --filter @csmarket/admin exec tsc --noEmit && pnpm --filter @csmarket/admin exec eslint src/features/sales src/features/dashboard src/app src/features/users/labels.ts --max-warnings 0 && npx prettier --write apps/admin/src`
Expected: PASS; tsc and eslint clean.

- [ ] **Step 7: Commit**

```bash
git add apps/admin/src
git commit -m "feat(admin/sales): payout requests with the audited card reveal, sales, settings, the «К выплате» tile" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Documents — ADR-0016, the module README and map, the flow, the runbook, PII, keys, metrics, API notes, AGENTS

**Files:**

- Create: `docs/decisions/0016-skin-sales-through-skinslink-deposits.md`
- Rewrite: `apps/api/src/csmarket/modules/sales/README.md`
- Modify: `docs/architecture/module-map.md` (a «Selling skins to us (ADR-0016)» section; the worker and scheduler rows)
- Create: `docs/architecture/sequence-diagrams/skin-sale.mmd`, `docs/product/flows/sell.md`, `docs/runbooks/sales.md`, `infra/prometheus/tests/sales_test.yml`
- Modify: `docs/security/pii-handling.md`, `docs/architecture/cache-keys.md`, `docs/architecture/metrics.md`, `docs/api/README.md`, `docs/runbooks/skinslink.md`, `apps/api/src/csmarket/modules/skinslink/README.md`, `AGENTS.md` (§0, §9, §11)

**Interfaces:**

- Consumes: everything Tasks 1–15 built (names exactly as there).
- Produces: documents only; the `#overdue` anchor of `docs/runbooks/sales.md` that `SalePayoutsOverdue` links to (Task 10).

- [ ] **Step 1: Write the failing alert test**

```yaml
# infra/prometheus/tests/sales_test.yml
# Unit tests for ../alerts/sales.yml. Run from the repo root:
#
#   docker run --rm -v "$PWD/infra/prometheus:/p" --entrypoint promtool \
#     prom/prometheus test rules /p/tests/sales_test.yml
rule_files:
  - ../alerts/sales.yml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'csmarket_sale_payouts_overdue{job="scheduler"}'
        values: "0 0 2 2 2 2 2 2 2 2"
    alert_rule_test:
      - eval_time: 3m
        alertname: SalePayoutsOverdue
        exp_alerts: []
      - eval_time: 8m
        alertname: SalePayoutsOverdue
        exp_alerts:
          - exp_labels:
              severity: warn
            exp_annotations:
              summary: "2 card payout(s) payable for over 48 h"
              description: "Open «Выкуп» → «Заявки на выплату» → «К выплате» in the admin and pay them by hand, or reject one with a reason (its money then goes to the seller's balance).\n"
              runbook: "https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/sales.md#overdue"

  # The API and the worker export the gauge too but never set it: only the scheduler's counts.
  - interval: 1m
    input_series:
      - series: 'csmarket_sale_payouts_overdue{job="api"}'
        values: "3 3 3 3 3 3 3 3 3 3"
    alert_rule_test:
      - eval_time: 8m
        alertname: SalePayoutsOverdue
        exp_alerts: []
```

Run: `docker run --rm -v "$PWD/infra/prometheus:/p" --entrypoint promtool prom/prometheus test rules /p/tests/sales_test.yml`
Expected: PASS (the rule exists since Task 10). If Docker is not running on the laptop, leave it to CI's reviewer and say so in the commit body.

- [ ] **Step 2: ADR-0016**

```markdown
# 0016. Selling skins to us through Skinslink deposits

- **Status**: Accepted
- **Date**: 2026-10-08
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security | data

## Context and problem statement

The buy side runs on three sources. The sell side («выкуп») is the next revenue line: a user
sells skins, Skinslink takes them through its deposit API and credits **our** merchant
balance in USD, and we pay the user in soʻm minus our margin — to the csmarket balance, or to
a card by hand. Spec: `docs/superpowers/specs/2026-10-08-skin-sales-design.md`.

## Decision drivers

- No path pays twice, pays for a reverted trade, or pays before a verified `completed`.
- No external call holds a database lock or an open transaction (AGENTS §11).
- A card number is PII and a payment credential.
- The seller is paid what the cart showed.

## Considered options

1. **Skinslink's API flow** (`inventory` → `create-deposit` → `deposit/status` + webhook).
2. **Skinslink's hosted intent** (a redirect or an iframe) — their UI, not ours; no control
   over the copy, the payout choice or the card.
3. **Our own bots** — a Steam bot fleet, trade holds and inventory risk of our own.

## Decision outcome

**Chosen option:** 1, because it keeps the page ours and the risk (bots, Steam holds,
reversals) Skinslink's, and its `min_prices` lets us fix the payout when the sale is created.

- **Pricing.** `price_uzs = floor100((usd − bracket_margin(usd)) × rate)`, the rate being the
  raw CBU rate less `rate_cut_pct` (never the buy side's uplift); the balance gets a bonus, a
  card pays its type's fee; every figure rounds down to 100. All of it lives in one admin
  document (`sale_settings`, row 1), like the pricing rules.
- **Fixed payout.** `POST /sell` re-prices from the inventory snapshot we kept (Redis, 5 min,
  the life of Skinslink's own snapshot), refuses a cart whose payout differs from what it
  showed, and floors each item at 99 % of its quoted price (`min_prices`): Skinslink then
  credits us at least that or refuses the deposit (`item_specified_price_not_found` →
  `prices_changed`).
- **Two new AGENTS §11 carve-outs.** `GET /sell/inventory` calls Skinslink `inventory` on a
  cache miss (6 s timeout, 120 s breaker, its own `ip_guard` bucket, no DB connection held);
  `POST /sell` stores and commits the sale, then calls `create-deposit` once (10 s; a timeout
  leaves the sale `creating` for the poll, which asks `deposit/status`).
- **One status machine.** `sales.status.apply_deposit` moves a sale under its row lock; the
  webhook (signed over `trade_id` only) never moves anything — it queues a check, and the
  worker asks `deposit/status`. A 60-s poll covers `creating` / `offered` (no webhooks before
  `hold`), a 30-min one `hold`.
- **The ledger.** A new credit-normal house account `house_skin_buys`; a balance sale books
  D `user_wallet` / C `house_skin_buys` under `sale:{sale_id}` at `completed` — once, whatever
  the races. A card payout books nothing (the money leaves our bank by hand); a rejected one
  credits the amount before the fee under `payout_return:{request_id}`.
- **Reversals.** `reverted` before the money left cancels the payout; after it, the sale gets
  `attention_reason = rolled_back` and an admin decides — no automatic debit.
- **Cards.** Encrypted with `core.crypto` (purpose `csmarket:payout-card:v1`); `last4` only in
  logs, lists, letters and replays; the full number only through an audited reveal that is
  never stored as a replay. At most three live cards per user.
- **Switches.** `CSMARKET_SALES_ENABLED` and the admin's «Выкуп включён», both off by default.

### Positive consequences

- A seller sees soʻm prices for the items Skinslink accepts now, and is paid once.
- The buy side's patterns (row locks, keyed ledger posts, checks queued by a webhook, polling
  fallbacks) carry over unchanged.

### Negative consequences

- Card payouts are manual: an admin must pay within 48 h (`SalePayoutsOverdue`).
- We carry the gap between Skinslink's quote and its credit (at most 1 % per item).
- The 7-day Steam protection delays every payout; no instant credit until KYC (later).

## Validation

Integration tests pin the double credit, a reversal before and after the credit, the forged
webhook, price drift and the card number's PII (the plan's Review Focus). In production: the
owner's test sale, then `csmarket_sale_outcomes_total` and the `SalePayoutsOverdue` alert.

## References

- [ADR-0010](./0010-skinslink-buy-source.md) — Skinslink as a buy source (the client, the
  webhook).
- [ADR-0007](./0007-orders-buying-trades.md) — the buy paths' locking and ledger patterns.
- Skinslink docs: Get Inventory, Create Deposit, Deposit Status, Webhooks, Errors (2026-10-08).
```

- [ ] **Step 3: The module README and the map**

`apps/api/src/csmarket/modules/sales/README.md`:

```markdown
# `sales` — users sell skins to us (Skinslink deposits)

Spec: `docs/superpowers/specs/2026-10-08-skin-sales-design.md`. Decision: ADR-0016. Flow:
`docs/architecture/sequence-diagrams/skin-sale.mmd`. Runbook: `docs/runbooks/sales.md`.

## Owns

| Table             | What                                                                        |
| ----------------- | --------------------------------------------------------------------------- |
| `sales`           | One per deposit; `id` = Skinslink's `merchant_tx_id`; the payout fixed      |
| `sale_items`      | The items at the prices the seller saw (USD from Skinslink, soʻm ours)      |
| `payout_cards`    | Saved cards, the number encrypted (`CARD_PURPOSE`), `last4` in the clear    |
| `payout_requests` | Card payouts an admin pays by hand (`waiting_hold` → `to_pay` → `paid` / …) |
| `sale_settings`   | Row 1: the admin's document (`rules.SaleSettings`)                          |
| `sale_checks`     | «Ask Skinslink about sale N», queued by the deposit webhook                 |

## Files

- `rules.py`, `pricing.py`, `settings_store.py` — the document and the pure pricing.
- `gate.py`, `clients.py`, `inventory.py` — the switches, the Skinslink client per route, the
  kept inventory snapshot and its breaker.
- `service.py` — `POST /sell`; `status.py` — every transition (`apply_deposit`, `check_sale`);
  `payouts.py` — a card sale's request; `checks.py` — the webhook's queue; `reconcile.py` —
  the poll and the overdue count; `letters.py` — the three letters.
- `cards.py`, `views.py`, `schemas.py`, `routes.py`, `cards_routes.py` — the seller's API.
- `admin_schemas.py`, `admin_sales.py`, `admin_payouts.py`, `admin_routes.py` — «Выкуп».

## Boundaries

Imports `skinslink.api` (the deposit client), `wallet.api` (`credit_sale`,
`credit_payout_return`), `notifications.api` (`enqueue`), `realtime.api` (`nudge_sale`),
`fx.api`, `skins.api` (`Bracket`, `bracket_margin`, `SkinItem`), `users.api`, `auth.api`,
`admin.api`. `skinslink.routes` imports `sales.api.enqueue_sale_check`; the dashboard
`sales.api.payouts_summary`; the worker `drain_sale_checks`; the scheduler `poll_sales`.

## Money rules

- The payout is fixed at creation and is what the cart showed (`expected_payout_uzs`).
- No ledger posting before `completed`; the credit is keyed by the sale; a rejected card
  payout by the request.
- A reversal never debits: `rolled_back` / `late_deposit` wait for an admin.

## Settings

| Env                                        | Default | Meaning                                    |
| ------------------------------------------ | ------- | ------------------------------------------ |
| `CSMARKET_SALES_ENABLED`                   | `false` | The env kill switch                        |
| `CSMARKET_SALES_INVENTORY_TIMEOUT_SECONDS` | `6`     | Skinslink `inventory` on the request path  |
| `CSMARKET_SALES_DEPOSIT_TIMEOUT_SECONDS`   | `10`    | Skinslink `create-deposit` on `POST /sell` |

The admin's document (`/admin/sales/settings`): `enabled`, `margin[]`, `rate_cut_pct`,
`balance_bonus_pct`, `card_fee_pct{uzcard, humo, uzum_visa}`, `card_min_uzs`, `min_sum_usd`.
It ships switched off with the demo's placeholder fees (5 %): the owner sets real ones first.
```

`docs/architecture/module-map.md`, a section before «Processes outside the API»:

```markdown
## Selling skins to us (ADR-0016)

- **`sales`** — owns `sales`, `sale_items`, `payout_cards`, `payout_requests`,
  `sale_settings` and `sale_checks`; migration `0023_sales`. Imports `skinslink.api` (the
  deposit client), `wallet.api`, `notifications.api`, `realtime.api`, `fx.api`, `skins.api`,
  `users.api`, `auth.api`, `admin.api`; everyone else imports `sales.api`. The only place a
  sale moves is `sales.status.apply_deposit`.
- **`skinslink`** — gains `deposits.py` (`inventory`, `create-deposit`, `deposit/status`); its
  webhook routes a signed deposit webhook to `sales.api.enqueue_sale_check`.
- **`wallet`** — a credit-normal `house_skin_buys` account; `credit_sale` (key
  `sale:{sale_id}`) and `credit_payout_return` (key `payout_return:{request_id}`); entries
  `sale_credit` / `payout_return` show the sale's `S…` number.
- **`notifications`** — `email_outbox.sale_id` and the letters `sale_hold`, `sale_paid`,
  `sale_canceled` (one per sale and kind).
- **`realtime`** — `nudge_sale`: the socket frame `{"type": "sale.updated", "number"}`.
- **`admin`** — the dashboard's «К выплате» (`sales.api.payouts_summary`); «Выкуп» routes live
  in `sales.admin_routes`.
- **Processes** — the worker's `sales` queue (`sales.api.drain_sale_checks`); the scheduler's
  `sales.poll` (every 60 s; sets `csmarket_sale_payouts_overdue`).

Flow: [`sequence-diagrams/skin-sale.mmd`](./sequence-diagrams/skin-sale.mmd). Runbook:
[`sales`](../runbooks/sales.md). Decision:
[ADR-0016](../decisions/0016-skin-sales-through-skinslink-deposits.md).
```

In the «Processes outside the API» table: the worker row gains "; `sales` (ADR-0016, one drainer) — `sales.api.drain_sale_checks` asks Skinslink about the sales its deposit webhook named", the scheduler row gains "; `sales.poll` (every 60 s) — ADR-0016", the web row gains "; selling (`/sell`, `/account/sales/{number}`, «Мои карты») ADR-0016", the admin row gains "; «Выкуп» (payout requests, sales, settings) ADR-0016".

- [ ] **Step 4: The flow and the diagram**

`docs/architecture/sequence-diagrams/skin-sale.mmd`:

```text
sequenceDiagram
    autonumber
    actor U as Seller
    participant Web as Storefront
    participant API as API
    participant R as Redis
    participant DB as Postgres
    participant W as Worker (sales queue)
    participant S as Scheduler (sales.poll)
    participant SL as Skinslink
    actor A as Admin

    U->>Web: opens /sell
    Web->>API: GET /sell/inventory
    API->>DB: switches, trade link, CBU rate (then the transaction ends)
    API->>R: kept snapshot? (sales:inventory:{user}:{hash(link)}, 5 min)
    alt miss or ?refresh=1
        API->>SL: POST /merchant/inventory {partner, token} (6 s, breaker)
        API->>R: keep the snapshot 5 min
    end
    API-->>Web: items priced in soʻm, max_items, the minimum
    U->>Web: picks items, the balance or a card, «Продать за …»
    Web->>API: POST /sell {asset_ids, payout, expected_payout_uzs} + Idempotency-Key
    API->>R: re-price from the kept snapshot (never the browser's numbers)
    API->>DB: insert sale (creating), items, a new card (encrypted); COMMIT
    API->>SL: POST /merchant/create-deposit {merchant_tx_id = sale id, min_prices = 99 %} (10 s)
    alt active
        API->>DB: lock the sale → offered (bot, offer id, expiry); NOTIFY order_events
    else price under the floor / stale snapshot
        API->>DB: closed (fail_reason); drop the kept snapshot
        API-->>Web: 409 prices_changed
    else timeout / 5xx
        Note over API,DB: stays creating; the poll settles it
    end
    API-->>Web: the sale → /account/sales/{number}
    U->>SL: accepts the Steam offer
    SL->>API: POST /skinslink/webhook {trade_id, sign, merchant_tx_id, status: hold}
    API->>API: verify sign = base64(sha256(trade_id + secret)) before reading anything
    API->>DB: insert sale_checks row; NOTIFY sales
    W->>SL: GET /merchant/deposit/status?merchant_tx_id
    W->>DB: lock the sale → hold (a card sale's request: waiting_hold); letter sale_hold
    loop every 60 s (creating, offered) / 30 min (hold)
        S->>SL: GET /merchant/deposit/status
        S->>DB: apply under the lock
    end
    SL->>API: webhook status: completed (7 days later)
    W->>SL: GET /merchant/deposit/status
    alt balance
        W->>DB: D user_wallet / C house_skin_buys, key sale:{id} → credited; letter sale_paid
    else card
        W->>DB: request → to_pay → sale payout
        A->>API: «Скопировать номер» (audited), pays by hand, «Выплачено» (audited)
        API->>DB: request paid; letter sale_paid
    end
    Note over SL,DB: reverted before the money left → reverted, nothing paid; after → rolled_back for an admin
```

`docs/product/flows/sell.md`:

```markdown
# Flow — Sell skins

A signed-in user with a trade link sells skins from their Steam inventory and is paid in soʻm:
to the csmarket balance (with a bonus) or to a card (with a fee), once Steam's 7-day
protection of the trade is over. Design: ADR-0016; operations:
[`sales.md`](../../runbooks/sales.md); diagram:
[`skin-sale.mmd`](../../architecture/sequence-diagrams/skin-sale.mmd).

## What the seller sees

1. **`/sell`** while selling is on (else «Скоро»): signed out → «Войдите через Steam»; no
   trade link → the trade-link form; else the items we buy now, priced in soʻm, dearest
   first, and «Показаны предметы, которые можно продать сейчас». A Steam refusal of the
   account (private profile, trade ban, …) is said in plain words.
2. **The cart:** the chosen items, «Куда получить» — the balance (+2 % by default), a saved
   card (up to three) or a new Uzcard / Humo / Uzum Visa (the number checked as it is typed),
   the fee or the bonus, «Вы получите», and «Деньги придут через 7 дней после обмена».
   «Продать за {sum}» stays off under the minimum («Добавьте ещё на {sum}») and for a card
   under 30 000 soʻm.
3. **«Продать»:** the browser goes to `/account/sales/{number}`: «Примите обмен» with
   «Открыть обмен в Steam», the bot's name and the deadline. If prices moved: «Цены
   обновились — проверьте сумму и нажмите ещё раз», and the inventory is read again.
4. **After the trade:** «Скины получены. {amount} поступят {date}.» — then «Деньги на
   балансе» or, for a card, «Отправляем деньги» → «Деньги отправлены». A rejected card
   payout: «Перевод на карту не прошёл — {amount} зачислены на баланс». A declined or
   expired offer: «Продажа не состоялась»; a trade reversed in Steam: «Обмен отменён».
5. **Account:** «Обмены» → «Продажи» lists the sales; «Мои карты» lists and forgets cards;
   «Транзакции» shows «Ожидает зачисления: {sum}» while balance sales wait, and the credit
   as «Продажа скинов».
6. **Letters** (to a confirmed address): skins received, money sent, sale did not go through.

## Rules

- The payout is fixed when the sale is created; Skinslink crediting a little less is ours.
- The minimum is on the sum of the items (1 $ at Skinslink's prices by default), not per item.
- Nothing is paid before Steam's protection ends; nothing is paid twice; a reversal is never
  debited automatically.
```

- [ ] **Step 5: The runbook**

`docs/runbooks/sales.md`:

```markdown
# Runbook — Selling skins to us (Skinslink deposits)

ADR-0016. Module: `apps/api/src/csmarket/modules/sales/`. Alert: `SalePayoutsOverdue`.

## Switching on

1. Skinslink buying's credentials are set (`CSMARKET_SKINSLINK_API_KEY`, `_SECRET`), the VPS
   IP is whitelisted in the cabinet, the merchant webhook URL is
   `https://api.csmarket.uz/api/v1/skinslink/webhook` (the same endpoint serves purchases
   and deposits) — `docs/runbooks/skinslink.md`.
2. Deploy with `CSMARKET_SALES_ENABLED=false`; then set it `true` in `secrets/api.env` and
   restart the API, the worker and the scheduler with the pinned `IMAGE_TAG`.
3. In the admin, «Выкуп» → «Настройки выкупа»: set the real card fees, the bonus, the margin
   brackets; leave «Выкуп включён» off.
4. The owner makes a test sale with «Выкуп включён» on for a minute: inventory, offer, accept,
   `hold`. Check the sale page and «Продажи» in the admin; then decide whether to leave it on.

## Paying a card request

«Выкуп» → «Заявки на выплату» → «К выплате» (the default tab). Open a request:

1. «Скопировать номер» (or «Показать номер») — each is an audit row
   (`sales.card.copy` / `sales.card.show`). Never paste the number anywhere but the bank.
2. Pay the amount shown («К выплате») from the bank by hand.
3. «Выплачено», with the bank's reference as the note. The seller gets a letter.

The number is never in a list, a letter or a log; do not screenshot it.

## Overdue

`SalePayoutsOverdue`: a request has been «К выплате» for more than 48 h. Pay it as above, or
«Отклонить» with a reason when the card cannot take it (blocked, wrong bank): the amount
**before** the card fee goes to the seller's balance (`payout_return`), and they get a letter.

## Rejecting

«Отклонить» needs a reason. It is possible only for a request «К выплате» — a request still
waiting for its 7 days cannot be decided (409 `payout_not_payable`).

## Stuck sales

- **`creating` for minutes**: `create-deposit` timed out. `sales.poll` asks `deposit/status`
  every minute; an unknown deposit is closed (`not_created`) after 2 minutes. If many pile up,
  check Skinslink (`csmarket_skinslink_calls_total{endpoint="deposit"}`).
- **`offered` for hours**: the seller has not accepted; Skinslink cancels expired offers and
  the poll closes the sale.
- **`hold` past its date**: the poll asks every 30 minutes; check the deposit in the cabinet
  by the sale id (= `merchant_tx_id`).

## Attention

- **`rolled_back`**: Skinslink reported `reverted` after the money left (the balance credited,
  or the card paid). Nothing is debited automatically. Look at the deposit in the cabinet; if
  the seller kept the money for skins we lost, contact them; adjust the balance only with the
  owner's word («Пользователи» → balance adjustment, audited).
- **`late_deposit`**: a sale we closed (`not_created`, a refusal) that Skinslink reports alive.
  The seller may have handed over skins: check the cabinet; if the deposit completed, pay the
  seller by hand (an admin balance adjustment with the sale number in the note).

## Switching off

The admin's «Выкуп включён» off (instant), or `CSMARKET_SALES_ENABLED=false` (a restart).
Open sales keep settling: the poll and the worker run while the Skinslink key is set.
```

`docs/runbooks/skinslink.md`, «Webhook URL»: replace "Deposit webhooks (the future sell side) are answered and ignored." with "A deposit webhook (`trade_id`, ADR-0016) queues a check of the sale its `merchant_tx_id` names; the worker asks `deposit/status` (`docs/runbooks/sales.md`). The route answers while Skinslink buying **or** selling is active." Same change in `modules/skinslink/README.md`'s webhook paragraph.

- [ ] **Step 6: PII, cache keys, metrics, API notes**

`docs/security/pii-handling.md`, in «Inventory», a subsection:

```markdown
### Payout cards (ADR-0016)

- **Card number** — `payout_cards.number_enc` + `number_nonce`: encrypted with `core.crypto`
  under the purpose `csmarket:payout-card:v1` (a stolen dump alone yields nothing). In the
  clear: `last4` and the type. The full number is returned only by
  `POST /admin/sales/payouts/{id}/reveal`, to an admin, audited every time
  (`sales.card.show` / `sales.card.copy`, payload `last4`), and is never stored as an
  idempotency replay, never in a letter, a log (`card_number`, `number_enc`, `new_card`, `pan`
  are redacted keys), a metric or an admin list. `NewCardIn.number` and the service's draft
  are `repr=False`. A 422 for a bad number never echoes it (`card_invalid`).
- **Retention** — a deleted card is soft-deleted: a paid request must keep pointing at its
  card for disputes. Erasing old encrypted numbers is M5's retention work.
- **Skinslink's deposit webhook** carries the seller's Steam id; it is never read or logged.
```

and in «Where each may appear» → «Third parties», add: "Skinslink receives `partner` and `token` to price the seller's inventory and send the deposit offer (ADR-0016)".

`docs/architecture/cache-keys.md`, two rows:

```markdown
| `sales:inventory:{user_id}:{hash_short(trade_link)}` | 300 s | `sales.inventory.fetch_snapshot` (a Skinslink `inventory` read) | `fetch_snapshot` (`GET /sell/inventory`), `cached_snapshot` (`POST /sell` re-prices from it); `forget_snapshot` on `prices_changed` | The user id (internal) and a digest of the link; the value is Skinslink's priced items (asset ids, names, USD prices) |
| `sales:inventory:breaker` | 120 s | `sales.inventory.fetch_snapshot` on a Skinslink outage, 429 or 403 | the same: while it exists no `inventory` call is made | No: a flag |
```

`docs/architecture/metrics.md`: the `csmarket_skinslink_calls_total` row's `endpoint` list gains `inventory` / `deposit` / `deposit_status` ("Get Inventory, Create Deposit, Deposit Status — ADR-0016"), and two rows:

```markdown
| `csmarket_sale_outcomes_total` | `outcome` = `offered` / `hold` / `credited` / `payout` / `closed` / `reverted` / `attention` | Where `sales.status.apply_deposit` moved a sale (ADR-0016). Incremented once per move, in the transaction that makes it. | — (dashboards) |
| `csmarket_sale_payouts_overdue` (gauge) | — | Card payout requests `to_pay` for over 48 h; set by the scheduler's `sales.poll` every minute. | `SalePayoutsOverdue` (> 0 for 5 min) |
```

and the promtool line at the end of the file gains `/p/tests/sales_test.yml`.

`docs/api/README.md`, a section after «Source callbacks: Skinslink»:

```markdown
## Selling skins (ADR-0016)

Signed in unless said. Money in whole soʻm as strings; a card by its type and last four.

- `GET /sell/config` — **public**: `enabled`, `balance_bonus_pct`, `card_fee_pct`,
  `card_min_uzs`, `min_sum_uzs` (a hint; `null` without a rate), `max_cards`.
- `GET /sell/inventory?refresh=1` — the items Skinslink accepts now at our prices, `max_items`,
  `min_sum_uzs`. Kept 5 minutes per user and trade link; `refresh` asks again. Rate-limited
  (`ip_guard` bucket `sell-inventory`). An advisory external call (AGENTS §11): 6 s, a 120 s
  breaker. 409 `sales_disabled` / `trade_link_missing` / `trade_link_bad` / `steam_refused`
  (+ `reason`: Skinslink's Steam account code); 503 `sales_unavailable` / `rate_unavailable`.
- `POST /sell` — **`Idempotency-Key` required** (16..160); a replay answers 200 with the stored
  sale whatever the body. Body: `asset_ids`, `payout` (`{to: "balance"}` |
  `{to: "card", card_id}` | `{to: "card", new_card: {type, number}}`),
  `expected_payout_uzs` (the cart's figure; another is 409 `prices_changed`). Bucket
  `sell-create`. One `create-deposit` call (10 s) after the sale is committed. 409
  `prices_changed`, `below_minimum` (+ `min_sum_uzs`), `below_card_minimum`
  (+ `card_min_uzs`), `too_many_items` (+ `max_items`), `steam_refused`, `cards_limit`,
  `sales_disabled`, `trade_link_*`; 422 `card_invalid` (the number is never echoed); 404 a
  card that is not mine; 503 `sales_unavailable`. 201 `SaleOut`; a timeout answers
  `status: "creating"`.
- `GET /sales?cursor=`, `GET /sales/{number}` (`S…`; 404 for anyone else's),
  `GET /sales/pending` (`pending_uzs`: balance sales still in Steam's protection).
- `GET /payout-cards`; `DELETE /payout-cards/{id}` — `Idempotency-Key` required; the soft
  delete is its own replay (a repeat is 204).
- Socket: `{"type": "sale.updated", "number"}` on the order socket.
- Admin (`/admin/sales`): `GET /payouts?status=` (tabs with `counts`), `GET /payouts/{id}`,
  `POST /payouts/{id}/reveal {purpose: show|copy}` (**keyless on purpose**: it changes only the
  audit trail and a replay would store the number), `POST /payouts/{id}/paid {note?}` and
  `POST /payouts/{id}/reject {reason}` (keyed, audited; 409 `payout_not_payable` unless
  `to_pay`), `GET`/`PUT /settings` (keyed, audited `sales.settings.save`), `GET ""?status=&q=`,
  `GET /{number}`. The dashboard gains `payouts: {to_pay_count, to_pay_uzs}`.
```

- [ ] **Step 7: AGENTS.md**

- §0, after the LIS-SKINS sentence: "Selling skins to us through Skinslink deposits (spec `2026-10-08-skin-sales-design.md`, ADR-0016) is built on branch `skin-sales` — off behind `CSMARKET_SALES_ENABLED` and the admin's «Выкуп включён» (`docs/runbooks/sales.md`)."
- §9, the 95 % list: `payments`, `wallet`, `orders`, `skins`, `notifications`, `realtime`, `skinslink`, `lisskins`, `sales`.
- §11, after the fifth carve-out ("…a failed call accepts the snapshot price (the worker's `max_price` guards)."): "A sixth and a seventh (ADR-0016): `GET /sell/inventory` asks Skinslink `inventory` on a cache miss — 6 s timeout, a 120 s breaker, the result kept 5 minutes per user, its own `ip_guard` bucket, no DB connection held across it; `POST /sell` commits the sale, then calls `create-deposit` once — 10 s, nothing open across it, a timeout left to the poll. Both routes are in the latency alerts' `handler` regexes."

- [ ] **Step 8: Check the documents and commit**

Run: `npx prettier --write docs AGENTS.md apps/api/src/csmarket/modules/sales/README.md apps/api/src/csmarket/modules/skinslink/README.md infra/prometheus/tests/sales_test.yml && npx prettier --check docs AGENTS.md`
Expected: formatted; no other file changed (do not run prettier from `apps/web`).

```bash
git add docs AGENTS.md apps/api/src/csmarket/modules/sales/README.md apps/api/src/csmarket/modules/skinslink/README.md infra/prometheus/tests/sales_test.yml
git commit -m "docs: ADR-0016, the sell flow, the sales runbook, PII, keys, metrics, API notes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review notes (for the executor)

- **Spec coverage:** §1 goal → Tasks 8, 9, 13 (sell), 7 (paid once at `completed`), 12 (card by hand); §2 constraints → Global Constraints, Tasks 6 (card PII), 8/9 (carve-outs), 1/8 (switches); §3 pricing → Task 4 (+ 9 for drift and the minimums); §4 data → Task 3, wallet → Task 7, «ожидает зачисления» → Tasks 11, 14; §5 API → Tasks 6, 8, 9, 11; §6 status flow → Tasks 7, 9, 10; §7 admin → Tasks 12, 15 (dashboard tile, 48 h alert → Task 10); §8 storefront → Tasks 13, 14, letters → Task 5; §9 testing → every task, coverage gate → Task 1; §10 documents → Task 16.
- **Full verification** (`make lint typecheck test`) runs on CI after the push the owner orders; locally each task runs only its own tests.
