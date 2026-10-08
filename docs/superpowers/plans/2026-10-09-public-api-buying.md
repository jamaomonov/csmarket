# Public API: keys and buying (plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user issues an API key in the profile and buys Skinslink / LIS-SKINS skins over
`/api/v1/public/*` from the USD wallet (plan A), onto any trade link, at the key's tariff, and
follows the order; refunds come back to the USD wallet with a reason.

**Architecture:** A new module `modules/public_api` owns keys, the key-auth dependency, per-key
limits, the feed snapshot, offer pricing by tariff and the public routes. Buying reuses the
orders pipeline: `orders/api_checkout.py` creates an ordinary `orders` row (`channel = 'api'`)
already paid from the USD wallet, and the existing worker buys it (lease, lookup-before-buy,
`cost_units` cap, no substitute — ADR-0007, ADR-0013). Nothing in a public request calls a
supplier: offers come from our Skinslink mirror and LIS-SKINS snapshot, the feed from a Redis
snapshot built every 60 s.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, Redis, APScheduler, pytest +
testcontainers; Next.js storefront.

**Spec:** `docs/superpowers/specs/2026-10-09-public-api-design.md` (§2, §4–§7, §12 B). Plan A
(`docs/superpowers/plans/2026-10-09-usd-wallet.md`) is built on the same branch. AGENTS.md is
binding.

## Global Constraints

- Money in the API: USD strings with three decimals (`"12.345"`); inside, integer milli-USD
  units (1000 = $1). Never floats.
- Token `csm_` + `secrets.token_urlsafe(32)`, shown once; only `sha256` stored. One live key per
  user; reissue revokes the old one, the tariff carries over. Never log a token (only `key_id`).
- Tariffs: `retail` = storefront rules (`quote(...).price_usd`); `cost` = the offer's
  `price_units` as is, plus `retail_price_usd`. Default `retail`; only an admin changes it
  (admin UI in plan C — until then a script / SQL in the runbook).
- No supplier name or supplier offer id ever leaves the API; `offer_id` is opaque.
- Supply: Skinslink and LIS-SKINS only; `delivery` is always `"instant"`.
- The trade link is checked for form only at `POST /orders` (422 `trade_link_invalid`).
- No public request calls a supplier or holds a DB connection across an external call.
- Purchases debit only the USD wallet; refunds go back to it. 403 `usd_wallet_disabled`, 402
  `insufficient_balance` on the public API.
- API orders: no letters; they show on the site's «Обмены» with an «API» tag and a USD amount.
- Limits per key: 60/min reads, 10/min `POST /orders`, feed first page 1/min; 429 + `Retry-After`.
- Errors RFC 7807 with `code`; ru / uz / en for every new site string; mypy --strict, ruff,
  eslint `--max-warnings 0`; prettier from the repo root only.
- Coverage: `orders`, `wallet` ≥ 95 %; add `public_api` to `scripts/check-module-coverage.py`
  at ≥ 95 %.
- Tests: run only the files you touch; full suites on CI. Commit per task; never push.

## Rulings made while planning (record in the spec, Task 1)

- **R1 — UZS columns stay NOT NULL.** Spec §6 makes `price_uzs` / `fx_snapshot_id` nullable;
  that would retype every site call site. API orders store `price_uzs = 0`,
  `fx_snapshot_id` = the newest snapshot (any age), `fx_uplift_pct = 0`; `price_usd` holds the
  charged price (so no `charged_units` column). Cost if wrong: a later migration.
- **R2 — issuing a key** needs a successful top-up **or** `usd_wallet_enabled` (YuPay is funded by
  an admin credit and may never top up).
- **R3 — `POST /me/api-key` replay:** the token is never stored, so a replayed Idempotency-Key
  answers 409 `key_already_issued` (with `key_id`), not the token again.
- **R4 — feed pages** are fixed at 1000 items; `limit` is not a parameter; the page JSON is kept
  as text in Redis (the client decodes strings) and compressed by Caddy (`encode gzip`).
- **R5 — `price_moved`** is added to the reasons and kept for a supplier refusal that names a
  price; Skinslink `hold` / `hold_and_permissions` map to the new `trade_hold`.

## Review Focus

1. Two `POST /orders` with the same `client_order_id` at the same time must create one order and
   debit once — Task 5 pins it (concurrent test).
2. A buy whose USD balance is short must write nothing (no order, no posting) and answer 402 —
   Task 5.
3. A refund of an API order must credit the **USD** wallet with exactly the charged amount, never
   the soʻm wallet — Task 6.
4. A revoked key must stop working at once (the next request 401), and a reissued key's tariff
   must equal the old one — Task 2.
5. A forged or another item's `offer_id` must be 409 `offer_gone`, never a 500 or a buy of
   another item — Task 4.

---

### Task 1: Schema — `api_keys`, API order columns, reasons, USD purchase legs

**Files:**

- Create: `apps/api/migrations/versions/0027_public_api.py`
- Create: `apps/api/src/csmarket/modules/public_api/__init__.py`, `models.py`, `README.md`
- Modify: `apps/api/src/csmarket/modules/orders/models.py`
- Modify: `apps/api/src/csmarket/modules/wallet/purchases.py`, `api.py`
- Modify: `apps/api/migrations/env.py` (import `public_api.models`)
- Modify: `docs/superpowers/specs/2026-10-09-public-api-design.md` (§6 → R1; §4 → R2, R3; §7 → R4)
- Test: `apps/api/tests/integration/test_public_api_schema.py`,
  `apps/api/tests/integration/test_wallet_usd_purchase.py`

**Interfaces:**

- Produces:
  - `ApiKey` model (`api_keys`): `id` uuid PK, `user_id` FK users, `token_hash` String(64)
    unique, `pricing_profile` String(8) default `'retail'` CHECK in (`retail`, `cost`),
    `ip_allowlist` ARRAY(String(43)) default `{}`, `created_at`, `last_used_at` nullable,
    `revoked_at` nullable; partial unique index `uq_api_keys_live_user` on `user_id` WHERE
    `revoked_at IS NULL`.
  - `Order` gains `channel` String(4) NOT NULL default `'site'` CHECK in (`site`, `api`),
    `api_key_id` UUID FK `api_keys.id` nullable, `client_order_id` String(64) nullable,
    `pricing_profile` String(8) nullable; CHECK `channel_fields`:
    `(channel = 'site' AND api_key_id IS NULL) OR (channel = 'api' AND api_key_id IS NOT NULL
AND client_order_id IS NOT NULL AND pricing_profile IS NOT NULL)`; unique
    `uq_orders_api_key_id_client_order_id (api_key_id, client_order_id)`.
  - `FAILURE_REASONS` += `trade_hold`, `price_moved` (Python-only, no DB CHECK exists).
  - `wallet.purchases`: `USD_WALLET = "usd_wallet"` (in `REFUND_SOURCES`);
    `debit_purchase_usd(db, *, user_id, order_id, units: Decimal) -> WalletTransaction`
    (C `user_wallet_usd` / D `house_payments_received_usd`, key `purchase:order:{order_id}`,
    lock + balance check → `InsufficientBalanceError(code="balance_too_low")`);
    `credit_order_refund_usd(db, *, user_id, order_id, units: Decimal, actor="orders")`
    (key `refund:order:{order_id}`, mirror legs).

- [ ] **Step 1: Failing tests**

`test_wallet_usd_purchase.py`:

```python
"""USD purchase debit and refund (plan B, spec §3, §6)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust_usd,
    credit_order_refund_usd,
    debit_purchase_usd,
    user_balance,
    user_usd_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

ADMIN = "00000000-0000-4000-8000-000000000001"
ORDER = "00000000-0000-4000-8000-0000000000a1"


async def _funded(db: AsyncSession, units: int) -> str:
    user = await make_user(db)
    await admin_adjust_usd(db, user_id=user.id, amount=Decimal(units), reason="seed",
                           admin_id=ADMIN, idempotency_key=f"seed-usd-{user.id}")
    await db.commit()
    return user.id


async def test_debit_then_refund_in_dollars(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 20_000)
    await debit_purchase_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(12_345))
    assert await user_usd_balance(db_session, uid) == Decimal(7_655)
    again = await debit_purchase_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(12_345))
    assert again.idempotency_key == f"purchase:order:{ORDER}"
    assert await user_usd_balance(db_session, uid) == Decimal(7_655)
    await credit_order_refund_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(12_345))
    assert await user_usd_balance(db_session, uid) == Decimal(20_000)
    assert await user_balance(db_session, uid) == Decimal(0)


async def test_short_usd_balance_books_nothing(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 1_000)
    with pytest.raises(InsufficientBalanceError):
        await debit_purchase_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(1_001))
    assert await user_usd_balance(db_session, uid) == Decimal(1_000)
```

`test_public_api_schema.py`: an `api` order without `api_key_id` violates `ck_orders_channel_fields`
(IntegrityError); two live keys for one user violate `uq_api_keys_live_user`; a revoked key plus
a live key for the same user are fine; `(api_key_id, client_order_id)` is unique. Build orders
with `tests/integration/orders_factory.build_order(..., channel="api", api_key_id=…,
client_order_id="c-1", pricing_profile="retail")`.

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the models, the migration `0027_public_api` (revises
      `0026_wallet_currency`; create `api_keys`, add the order columns + CHECK + unique; downgrade
      drops them), the wallet functions (copy `debit_purchase` / `credit_order_refund` and swap the
      account kinds: `user_usd_account(db, user_id, lock=True)`,
      `ensure_account(..., kind="house_payments_received_usd")`), the `env.py` import, the
      `public_api/README.md` (what the module owns), and the spec edits for R1–R4.
- [ ] **Step 4: Run** both test files + `tests/integration/test_migrations.py` +
      `tests/integration/test_wallet_purchase.py`; mypy on `modules/wallet modules/orders
modules/public_api`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(api/public_api): api keys table, API order columns, USD purchase legs`

---

### Task 2: Keys — issue, reissue, revoke, the key-auth dependency, per-key limits

**Files:**

- Create: `apps/api/src/csmarket/modules/public_api/keys.py`, `auth.py`, `limits.py`,
  `site_routes.py`, `schemas.py`, `api.py`
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `site_routes.router`)
- Modify: `apps/api/src/csmarket/core/logging.py` (redact values starting `csm_`)
- Test: `apps/api/tests/integration/test_public_api_keys.py`, `tests/unit/test_logging_csm.py`

**Interfaces:**

- Consumes: `ApiKey`, `User.usd_wallet_enabled`; `auth.security.hash_token`;
  `auth.ip_guard.hit_counter(key, *, limit, window) -> bool` (True = over the limit);
  `core.client_ip.client_ip(request)`.
- Produces:
  - `keys.issue(db, *, user: User) -> tuple[ApiKey, str]` — revokes the live key (if any),
    creates a new one with the old tariff (default `retail`), returns the row and the plain token.
    Raises `ConflictError(code="api_key_not_allowed")` unless the user has a succeeded top-up
    (a `topup` wallet transaction on their `user_wallet`) or `usd_wallet_enabled` (R2).
  - `keys.revoke(db, *, user: User) -> None` (no live key → 404 `api_key_missing`).
  - `keys.live_key(db, user_id) -> ApiKey | None`.
  - `auth.ApiCaller` frozen dataclass `(key: ApiKey, user: User)`; dependency
    `api_caller(request, authorization: Header, db) -> ApiCaller`: bearer `csm_…` → hash → live
    key → user; 401 `unauthorized` (missing/unknown/revoked), 403 `account_suspended`
    (banned user), 403 `ip_not_allowed` (allow-list set and `client_ip` not in it); updates
    `last_used_at` when older than 60 s.
  - `limits.enforce(caller, bucket: Literal["read", "order", "feed"]) -> None` — raises
    `RateLimitedError(code="rate_limited", retry_after=60)` (core/errors.py; set the
    `Retry-After` header — check how `RateLimitedError` renders and add the header there if it
    does not) at 60 / 10 / 1 per minute; Redis key `public_api:rl:{bucket}:{key_id}` (catalogue
    it in `docs/architecture/cache-keys.md` in Task 8).
  - Site routes (cookie/JWT user via `current_user`): `GET /me/api-key` → `ApiKeyOut {id,
pricing_profile, created_at, last_used_at} | null` (204 when none — pick `null` body 200);
    `POST /me/api-key` (Idempotency-Key) → 201 `ApiKeyIssuedOut {id, token, pricing_profile,
created_at}`; a replayed key → 409 `key_already_issued` with `key_id` (R3) — persist the key
    via `core.idempotency.save_replay` with a body that holds only `key_id`;
    `DELETE /me/api-key` (Idempotency-Key) → 204.

- [ ] **Step 1: Failing tests** (`test_public_api_keys.py`, fixtures as other route tests):
  - issue → 201, token starts `csm_`, `len(token) >= 40`; DB `token_hash == sha256(token)`;
    the token appears nowhere in `api_keys` columns.
  - no top-up and USD wallet off → 409 `api_key_not_allowed`; USD wallet on → 201.
  - reissue → a new token; the old token → 401 on a key-auth probe route; tariff `cost` set on
    the old key (direct SQL) carries to the new key.
  - revoke → the next probe 401; `GET /me/api-key` → `null`.
  - replayed Idempotency-Key on POST → 409 `key_already_issued` with `key_id`.
  - key auth: missing header 401; `Bearer csm_unknown` 401; banned user 403
    `account_suspended`; allow-list `["10.0.0.0/8"]` and client IP `203.0.113.5` (set
    `X-Forwarded-For` as other tests do) → 403 `ip_not_allowed`.
  - limits: the 11th order-bucket hit within a minute → 429 with `Retry-After`.
    For the probe, mount in the test app a tiny route using `api_caller` (or use `GET
/api/v1/public/me` once Task 5 exists — here use a test-only router added in the test).
    `tests/unit/test_logging_csm.py`: a log event with `token="csm_abc…"` and a free-text value
    containing `csm_abc…` both come out redacted.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.** Token: `"csm_" + secrets.token_urlsafe(32)`. Store
      `hash_token(token)`. Allow-list check with `ipaddress.ip_address(client_ip) in
ipaddress.ip_network(cidr, strict=False)`; an unparsable client IP fails closed when a list is
      set. Key-auth routes must be exempt from the coarse per-IP limiter: add each public handler to
      `bootstrap._exempt_self_authenticating_routes` as Task 5 creates them (here: none yet besides
      the site routes, which keep the coarse limit).
- [ ] **Step 4: Run** the two test files; ruff; mypy. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(api/public_api): API keys — issue, reissue, revoke, key auth and limits`

---

### Task 3: Offer pricing by tariff and the opaque offer id

**Files:**

- Create: `apps/api/src/csmarket/modules/public_api/offers.py`
- Test: `apps/api/tests/unit/test_public_offer_id.py`,
  `apps/api/tests/integration/test_public_api_offers.py`

**Interfaces:**

- Consumes: `skinslink.api.offers_for`, `lisskins.api.offers_for`
  (`(db, skin_item_id, *, settings, now) -> list[Offer]`); `skins.api.quote`, `load_rules`,
  `SkinItem`; `core.crypto.encrypt / decrypt` (purpose `"public_offer"`).
- Produces:
  - `seal_offer_id(item_id: str, offer_id: str) -> str` — url-safe base64 of
    `nonce + ciphertext` of `f"{item_id}|{offer_id}"`; `open_offer_id(token: str, item_id: str)
-> str | None` — `None` on any decode / decrypt failure or an item mismatch.
  - `@dataclass(frozen=True) class PricedOffer: offer: Offer; price_units: int;
retail_units: int` and `public_id: str`.
  - `price_units_for(units: int, *, profile: str, item: SkinItem, rules: PricingRules,
stock: int) -> tuple[int, int]` → `(price_units, retail_units)`; retail =
    `int(quote(units, rules=rules, category=item.category, weapon=item.weapon,
count_auto=stock, item_pp=item.margin_override_pp, fixed_price_usd=item.fixed_price_usd,
steam_price_units=item.steam_price_units).price_usd * 1000)`; cost profile → `units`.
  - `async def api_offers(db, item: SkinItem, *, profile: str, settings, now) -> list[PricedOffer]`
    — Skinslink + LIS-SKINS offers only, sorted by `(price_units, TIE_ORDER, offer_id)`.

- [ ] **Step 1: Failing tests** — unit: seal/open round-trip; open with another `item_id` → None;
      a flipped byte → None; garbage → None; the sealed string contains neither `sl:` nor `ls:`.
      Integration (seed a Skinslink mirror row and a LIS-SKINS offer for one item — reuse
      `tests/integration/skinslink_factory.py` / `lisskins_factory.py`): `cost` price equals the
      offer units; `retail` equals the storefront quote for that offer; Waxpeer listings never appear;
      order is cheapest first.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both files. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(api/public_api): offers priced by tariff, sealed offer ids`

---

### Task 4: Feed snapshot (scheduler) and catalogue routes

**Files:**

- Create: `apps/api/src/csmarket/modules/public_api/feed.py`, `routes.py` (public router,
  prefix `/public`)
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/public_feed.py`
- Modify: `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/api/src/csmarket/api/v1/router.py`,
  `apps/api/src/csmarket/bootstrap.py` (exempt the public handlers)
- Test: `apps/api/tests/integration/test_public_api_feed.py`,
  `apps/scheduler/tests/test_public_feed_job.py`

**Interfaces:**

- Consumes: Task 2 `api_caller`, `limits.enforce`; Task 3 `price_units_for`, `api_offers`,
  `seal_offer_id`, `open_offer_id`.
- Produces:
  - `feed.build_snapshot(db, redis, *, at) -> int` (items written): one query over active,
    not hidden `skin_items` with `skinslink_count + lisskins_count > 0`; per item
    `cost_units = min(non-null skinslink_min_units, lisskins_min_units)`, `retail_units` via
    `price_units_for(..., profile="retail")`, `stock`, `updated_at = prices_updated_at`; sorted
    by `item_id`; pages of 1000 as JSON text under `public_api:feed:{snap}:{n}` plus
    `public_api:feed:current` = `{"snap": snap, "pages": N, "at": iso}`; TTL 10 min; the
    previous snapshot stays until `current` flips.
  - `GET /public/catalog?cursor=&updated_since=` — page `n` of the current snapshot (cursor
    `"{snap}.{n}"`; a cursor of an expired snapshot → 409 `cursor_expired`); each item priced by
    the caller's tariff from the stored `cost_units` / `retail_units`; `ETag` = sha256 of the
    response body, `If-None-Match` → 304 empty; `next_cursor` or null. Limit bucket `feed` only
    for page 0, `read` otherwise.
  - `GET /public/catalog/{item_id}/offers` — `api_offers` priced by tariff, cached 60 s per
    `(item_id, profile)` (`public_api:offers:{profile}:{item_id}`); 404 unknown item.
  - Wire: `CatalogItemOut {item_id, slug, market_hash_name, exterior, price_usd,
retail_price_usd?, stock, updated_at}`, `OfferOut {offer_id, float, paint_seed, stickers[],
price_usd, retail_price_usd?, delivery: "instant"}` — `retail_price_usd` present only on the
    `cost` tariff (omit the key otherwise: `response_model_exclude_none` or a separate model).
  - Scheduler job `public_feed`: every 60 s, `first_run_after(15)`, `coalesce`, `max_instances=1`.

- [ ] **Step 1: Failing tests** — snapshot with 3 items (one with zero stock excluded); page 0
      returns 2 items with tariff prices; `cost` key sees `retail_price_usd`, `retail` key does not;
      `If-None-Match` with the returned ETag → 304; `updated_since` later than one item's
      `prices_updated_at` filters it out; a stale cursor → 409 `cursor_expired`; offers route:
      forged `offer_id` never appears, items' offers carry sealed ids; scheduler job test calls
      `run()` against a session factory and asserts `public_api:feed:current` exists.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the test files. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(api/public_api): the feed snapshot and catalogue routes`

---

### Task 5: Buying — `POST /public/orders`, reads, `/public/me`

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/api_checkout.py`, `orders/public_view.py`
- Modify: `apps/api/src/csmarket/modules/orders/api.py`, `orders/paid.py` (provider
  `usd_wallet` accepted), `modules/public_api/routes.py`, `schemas.py`, `bootstrap.py`
- Test: `apps/api/tests/integration/test_public_api_buy.py`

**Interfaces:**

- Consumes: Task 1 columns and `debit_purchase_usd`; Task 3 `api_offers`, `open_offer_id`;
  Task 2 `ApiCaller`, `limits.enforce`; `orders.paid.mark_paid(db, order, provider=...)`;
  `skins.api.get_item_by_id` (add it if `get_item` only takes a slug: a one-line select by id,
  active, not hidden, enabled category); `tradelink.parse_tradelink`.
- Produces:
  - `ApiOrderIn {item_id: str, offer_id: str | None, max_price_usd: str (pattern
^\d{1,6}(\.\d{1,3})?$), trade_link: str, client_order_id: str (1..64, [A-Za-z0-9_.:-])}`,
    `extra="forbid"`.
  - `create_api_order(db, *, caller: ApiCaller, body: ApiOrderIn, settings) -> tuple[Order, bool]`:
    1. existing `(api_key_id, client_order_id)` → return it, `False`;
    2. `settings.skins_buy_enabled` else 409 `buying_disabled`; `caller.user.usd_wallet_enabled`
       else 403 `usd_wallet_disabled`; `parse_tradelink(body.trade_link)` else 422
       `trade_link_invalid`;
    3. item by id (404 `item_not_found`); offers = `api_offers(...)` for the key's tariff; with
       `offer_id` → the matching sealed id (else 409 `offer_gone`); without → the cheapest whose
       price ≤ max; price > max → 409 `price_above_max` (with `price_usd`);
    4. `Order(status="pending", channel="api", api_key_id, client_order_id, pricing_profile,
source, offer_id (internal), listing_id None, cost_units = offer.price_units,
cost_usd, price_usd = price_units/1000, price_uzs = 0, fx_snapshot_id = newest
snapshot id, fx_uplift_pct = 0, trade_link = parsed url, float_value, paint_seed,
idempotency_key = f"api:{key_id}:{client_order_id}", expires_at = now + order_expiry)`,
       number allocated; flush (an IntegrityError on the unique pair → roll back to a savepoint
       and return the existing order, `False`);
    5. `debit_purchase_usd(units=price_units)` — `InsufficientBalanceError` → the whole
       transaction rolls back → 402 `insufficient_balance`;
    6. `mark_paid(db, order, provider="usd_wallet")` (moves to `paid`, NOTIFY, nudge; letters
       skipped in Task 6); commit.
  - `public_view.public_order(order, trade, purchase) -> PublicOrderOut` with the status mapping
    and reasons of spec §5 (`paid`/`buying`/held-for-support → `buying`; `trade_sent` with an
    accepted trade → `delivered`; refunded → `refunded` + `refund{amount_usd, reason}`; reason
    map `sold_out`→`sold_out`, `invalid_trade_link`→`invalid_trade_link`,
    `trade_hold`→`trade_hold`, `price_moved`→`price_moved`,
    `source_low_balance`/`not_accepted`→`supplier_refused`, `admin`→`cancelled_by_support`).
    `PublicOrderOut {order_id (= order.number), client_order_id, status, item {item_id, slug,
market_hash_name}, price_usd, created_at, trade {offer_sent_at, accepted_at, release_at} |
null, refund {amount_usd, reason} | null}` — never `source` or a supplier id.
  - Routes: `POST /public/orders` → 201 / duplicate → 409 `duplicate_client_order_id` with
    `{"order": PublicOrderOut}` in the problem body; `GET /public/orders/{order_id}` (another
    key's → 404); `GET /public/orders?cursor=&status=` (the key's own, newest first, 50 a page);
    `GET /public/me` → `{balance_usd, usd_wallet_enabled, key {id, pricing_profile,
created_at}, limits {read_per_min: 60, orders_per_min: 10, feed_per_min: 1}}`.
  - Add every public handler to `bootstrap._exempt_self_authenticating_routes`.

- [ ] **Step 1: Failing tests** (`test_public_api_buy.py`; seed a funded USD wallet with
      `admin_adjust_usd`, a key via `keys.issue`, a Skinslink offer for an item):
  - buy with `offer_id` → 201, `status == "buying"`, USD balance down by the price, the order row
    `channel == "api"`, `source == "skinslink"`, `paid_with == "usd_wallet"`, `price_uzs == 0`;
    the body has no `skinslink`/`sl:` substring.
  - buy without `offer_id` picks the cheapest ≤ max; max below the cheapest → 409
    `price_above_max`, nothing written.
  - same `client_order_id` twice → second is 409 `duplicate_client_order_id` with the same
    `order_id`; balance debited once.
  - **concurrent** duplicate (two sessions, `asyncio.gather`) → one order, one debit (Review
    Focus 1).
  - short balance → 402 `insufficient_balance`, no order row, no posting (Review Focus 2).
  - USD wallet off → 403 `usd_wallet_disabled`; bad trade link → 422 `trade_link_invalid`;
    forged `offer_id` → 409 `offer_gone` (Review Focus 5); unknown item → 404.
  - `GET /public/orders/{id}` by another key → 404; list filters by `status`.
  - `cost` tariff charges the offer units; `retail` charges the storefront quote.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.** Map `InsufficientBalanceError` to 402 `insufficient_balance` in the
      public route only (the site keeps 409 `balance_too_low`).
- [ ] **Step 4: Run** the file + `tests/integration/test_orders_checkout.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(api/orders): buying over the public API from the USD wallet`

---

### Task 6: Refunds to the USD wallet, reasons, no letters for API orders

**Files:**

- Modify: `apps/api/src/csmarket/modules/orders/refunds.py`, `orders/letters.py`,
  `orders/skinslink_status.py` (`_failure_reason`), `orders/lisskins_status.py`
- Test: `apps/api/tests/integration/test_public_api_refunds.py`

**Interfaces:**

- Consumes: `credit_order_refund_usd`; `Order.channel`, `Order.price_usd`.
- Produces: `refund_to_balance` credits `credit_order_refund_usd(units=price_usd * 1000)` when
  `order.paid_with == "usd_wallet"` (else unchanged); `enqueue_receipt`, `enqueue_trade_sent`,
  `enqueue_refunded` return early for `order.channel == "api"`; Skinslink fail codes `hold` and
  `hold_and_permissions` → `trade_hold` (other link codes stay `invalid_trade_link`).

- [ ] **Step 1: Failing tests:** an API order (created through `create_api_order`) refunded by
      `refund_to_balance(reason="sold_out")` → USD balance back to the start, soʻm balance unchanged
      (Review Focus 3), `GET /public/orders/{id}` shows `refunded` + `{amount_usd, reason:
"sold_out"}`; a Skinslink status report with `fail_reason="hold"` → `trade_hold`; no
      `email_outbox` rows for an API order across paid / trade_sent / refunded; a site order still
      gets its letters.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file + `tests/integration/test_orders_refunds*.py` +
      `tests/integration/test_orders_skinslink*.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(api/orders): API orders refund to the USD wallet, trade_hold, no letters`

---

### Task 7: Site — «API-ключ» in the profile, «API» on «Обмены»

**Files:**

- Modify: `apps/api/src/csmarket/modules/orders/schemas.py`, `service.py` (`OrderOut.channel`)
- Create: `apps/web/src/components/account/ApiKeyCard.tsx` (+ `.test.tsx`),
  `apps/web/src/lib/api-key.ts`
- Modify: `apps/web/src/components/account/ProfileView.tsx`,
  `apps/web/src/components/trades/TradeRow.tsx`, `apps/web/src/lib/orders.ts`,
  `apps/web/src/test/orders.ts`, `packages/i18n/locales/{ru,uz,en}/web.json`
- Test: `apps/api/tests/integration/test_orders_read.py` (one assertion), web tests

**Interfaces:**

- Consumes: Task 2 site routes; `OrderOut` + `channel: Literal["site", "api"]`.
- Produces: `ApiKeyCard` — states: none («Выпустить ключ», disabled with a hint when the API
  answers 409 `api_key_not_allowed` — «Сначала пополните баланс»); issued (token shown once with
  a copy button and «Сохраните ключ — он больше не покажется»); live (key created / last used,
  tariff, «Перевыпустить» with a confirm, «Отозвать» with a confirm); a link «Документация API»
  to `/docs/api` placeholder href `https://csmarket.uz/api-docs` (plan C publishes the doc —
  until then the link is hidden). `OrderRow`: `channel === "api"` → kind label «API», amount
  `−$12.345` from `price_usd` (3 decimals), note «с USD-кошелька».

- [ ] **Step 1: Failing tests:** `ApiKeyCard.test.tsx` — issue shows the token once and hides
      it after «Готово»; reissue and revoke ask to confirm and call the right functions; 409
      `api_key_not_allowed` shows the hint. `TradesView`/`TradeRow` test — an API order shows «API»
      and «−$12.345». API test — `OrderOut.channel == "api"` for an API order.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** (ru / uz / en strings; owner copy rules; `make gen-api`).
- [ ] **Step 4: Run** web vitest for the touched dirs, eslint, tsc, i18n parity; the API test.
- [ ] **Step 5: Commit** — `feat(web/account): the API key in the profile, API orders on «Обмены»`

---

### Task 8: Docs for plan B

**Files:**

- Create: `docs/api/public-v1.md` (auth, tariffs, feed with ETag and cursor, offers, buy with
  `client_order_id`, statuses and reasons, errors, limits; curl examples; webhooks «скоро»)
- Modify: `docs/api/README.md`, `docs/architecture/cache-keys.md` (`public_api:*` keys),
  `docs/architecture/module-map.md` (public_api), `docs/security/pii-handling.md` (key hash,
  per-order trade links of third parties, 30-day erase applies), `docs/runbooks/public-api.md`
  (revoke a key, set a tariff by SQL until plan C, a stuck API order), ADR-0017 (consequences:
  R1–R5), `AGENTS.md` §0 one line and §11 (no external call on the public path),
  `scripts/check-module-coverage.py` (`public_api` ≥ 95 %).

- [ ] **Step 1:** Write the docs; every example uses fake tokens and links
      (`csm_EXAMPLE…`, `partner=1&token=FAKEFAKE`).
- [ ] **Step 2:** `npx prettier --write` the changed docs from the repo root; commit
      `docs: the public API v1 (keys and buying), runbook, cache keys, PII`.

---

## Self-review notes

- Spec §4 keys (T2, T7), §5 contract (T4, T5), §6 orders/worker (T1, T5, T6), §7 feed/offers/
  limits (T2, T4), §2.8 «Обмены» (T7), §12 B. Webhooks, admin keys page, metrics: plan C.
- `GET /public/orders?status=` filters by the public status (map back to internal sets).
