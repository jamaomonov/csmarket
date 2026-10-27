# Referrals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Partners chosen by the admin earn a percentage of what the new accounts they bring buy,
credited to their site balance after an 8-day hold.

**Architecture:** A new module `modules/referrals` owns partners, attributions, rewards and
visit counts. A link visit sets a cookie on the API host; the Steam sign-in that creates an
account reads it and writes the attribution. An hourly scheduler job turns delivered orders of
attributed buyers into `held` rewards and settles the matured ones into a new wallet kind
`referral_reward`. The storefront gets the partner page at the existing `/account/referral`;
the admin gets «Партнёры», a block on the user card and a «Партнёрам» line in «Аналитика».

**Tech Stack:** FastAPI, SQLAlchemy 2.1 async, Alembic, Redis, APScheduler; Next.js 15 + next-intl;
Vite admin + TanStack Query; pytest + testcontainers, vitest.

**Spec:** `docs/superpowers/specs/2026-10-27-referrals-design.md`

## Global Constraints

- Owner rule: the full test suite never runs locally — only the tests the task names (plus
  `ruff`, `mypy` on touched files, `tsc`/`eslint` on the touched package). CI runs the rest.
- Commit locally after every task on branch `referrals`. Never push or deploy without the owner's word.
- Conventional Commits, scope `api/referrals`, `web/referral`, `admin/referrals`, `docs`; trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Money: whole soʻm, `Decimal`, `numeric(14,0)`; reward = `floor(price_uzs × percent / 100)`.
- Percent 0.1–20, one decimal; term 1–120 months or `null` = forever; default term 6.
- Code: `^[a-z0-9-]{3,32}$`, unique, not changeable once an attribution exists.
- Link cookie `csm_ref`, 30 days, last click wins; attribution only for an account created by
  this sign-in through `app="web"`.
- Hold: `available_at = delivered_at + 8 days`.
- Never log or show the buyer to the partner: no name, Steam ID, order number. Logs carry
  partner code and amounts only, never IP or Steam ID.
- Python: mypy --strict, Google docstrings, files ≤ 400 LOC, functions ≤ 50 LOC, ruff PLR0917
  (keyword-only after `*`). TS: strict, no `any`, ≤ 300 LOC per file.
- All three locales (ru / uz / en) for every new string; owner copy rules (§12): short, «вы».
- Module coverage ≥ 95 % (add `referrals` to `scripts/check-module-coverage.py` and its test fixture).
- `make gen-api` after every endpoint change; prettier only from the repo root.

## Review Focus

1. **A reward for an order whose trade was rolled back** (Skinslink `reverted` arrives delivered
   and `rolled_back` at once) must be cancelled, never credited — Task 5 `test_rolled_back_*`.
2. **The partner page leaking the buyer** — the `/referrals/me/rewards` payload must have no
   order number, user id or name — Task 6 `test_rewards_carry_no_buyer`.
3. **A second sign-in of an existing account through a link** must not attribute it, nor must the
   admin app's sign-in — Task 4 `test_existing_account_is_not_attributed`, `test_admin_app_never_attributes`.
4. **A frozen partner wallet or a banned partner** must leave the reward `held` and the job must go
   on with the others — Task 5 `test_frozen_wallet_waits_and_others_credit`.
5. **The settle job run twice / two schedulers** must book one wallet transaction — Task 5
   `test_settle_twice_books_once`.

---

### Task 1: Sign-in tells whether it created the account

**Files:**

- Modify: `apps/api/src/csmarket/modules/users/service.py`, `users/api.py`, `users/README.md`
- Test: `apps/api/tests/integration/test_users_signin_created.py`

**Interfaces:**

- Produces: `async def sign_in_by_steam(db, *, steam_id: str, display_name: str | None, avatar_url: str | None) -> tuple[User, bool]` — `(user, created)`; `upsert_user_by_steam` stays and returns `(await sign_in_by_steam(...))[0]`.

- [ ] **Step 1: Write the failing test** — `test_first_sign_in_creates_then_finds`: first call → `created is True`; second call with the same steam id → `created is False`, same `user.id`. `test_concurrent_first_sign_in_one_creates`: two sessions race (reuse the pattern of `test_auth_refresh_race.py`) → exactly one `True`.
- [ ] **Step 2: Run** `uv run pytest apps/api/tests/integration/test_users_signin_created.py -q` — Expected: FAIL, `sign_in_by_steam` not importable.
- [ ] **Step 3: Implement** — move the body of `upsert_user_by_steam` into `sign_in_by_steam`, returning `created=True` only on the path whose INSERT succeeded (the `IntegrityError` loser returns `False`). Export it in `users/api.py`; one line in the README interface list.
- [ ] **Step 4: Run** the test file and `apps/api/tests/integration/test_auth_refresh_race.py` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api/users): sign-in says whether it created the account`.

### Task 2: The referrals tables and the reward's ledger kind

**Files:**

- Create: `apps/api/src/csmarket/modules/referrals/{__init__.py,models.py,api.py,README.md}`
- Create: `apps/api/migrations/versions/0043_referrals.py`
- Create: `apps/api/src/csmarket/modules/wallet/referrals.py`
- Modify: `wallet/models.py` (`ACCOUNT_KINDS` + `house_referrals`), `wallet/service.py` (`NORMAL_SIDE["house_referrals"] = "C"`, `TX_KINDS` + `referral_reward`), `wallet/api.py`, `wallet/README.md`
- Modify: `apps/api/migrations/env.py`, `apps/scheduler/src/csmarket_scheduler/main.py` (import the models), `apps/api/tests/conftest.py` (cleanup list: the four tables)
- Test: `apps/api/tests/integration/test_referrals_tables.py`, `apps/api/tests/integration/test_wallet_referral_reward.py`

**Interfaces:**

- Produces (models, `referrals/models.py`):
  - `ReferralPartner`: `user_id` PK FK users (CASCADE), `code` String(32) unique, `percent` Numeric(4,1) CHECK 0.1–20, `term_months` Integer null CHECK 1–120, `active` bool default true, `note` Text null, `created_at`, `updated_at`.
  - `ReferralAttribution`: `user_id` PK FK users (CASCADE), `partner_id` FK `referral_partners.user_id` (RESTRICT), `attributed_at`; index `ix_referral_attributions_partner`.
  - `ReferralReward`: `order_id` PK FK orders (RESTRICT), `partner_id` FK partners, `referred_user_id` FK users, `base_uzs` Numeric(14,0), `percent` Numeric(4,1), `amount_uzs` Numeric(14,0) CHECK > 0, `status` String(16) CHECK in (`held`,`credited`,`cancelled`), `delivered_at`, `available_at`, `credited_at` null, `cancelled_reason` String(32) null, `created_at`; partial index `ix_referral_rewards_due` on `available_at` WHERE `status = 'held'`; index on `(partner_id, delivered_at)`.
  - `ReferralVisitDay`: PK (`partner_id`, `day` Date), `visits` Integer ≥ 0.
  - Constants `REWARD_STATUSES`, `CANCEL_REASONS = ("rolled_back",)`, `HOLD = timedelta(days=8)`.
- Produces (wallet): `async def credit_referral_reward(db, *, user_id: str, order_id: str, amount: Decimal) -> WalletTransaction` — D `user_wallet` / C `house_referrals`, kind `referral_reward`, key `referral_reward:{order_id}`, `Reference(type="referral", id=order_id)`, actor `referrals`. A frozen wallet raises the ledger's `ConflictError` unchanged.

- [ ] **Step 1: Failing tests** — `test_referrals_tables.py`: `test_percent_and_term_bounds` (0.0, 20.1, term 0 and 121 refused by the DB), `test_one_reward_per_order` (second row same `order_id` → IntegrityError), `test_reward_amount_positive`. `test_wallet_referral_reward.py`: `test_credits_the_balance_once` (two calls → one transaction, balance +amount), `test_customer_entry_has_no_order_number` (`entries_for_user` line for the kind has `reference_number is None`), `test_frozen_wallet_refuses`.
- [ ] **Step 2: Run** both files — Expected: FAIL (no module / no table).
- [ ] **Step 3: Implement** models, migration `0043_referrals` (revises `0042_articles`; also drops and re-creates the `wallet_accounts.kind` CHECK with `house_referrals` added, as `0026_wallet_currency` does; downgrade refuses while a `house_referrals` account exists), the wallet function. `entries.py`: confirm the `referral` reference type yields `None` (add the kind to no `ENTRY_TYPES` filter).
- [ ] **Step 4: Run** both files — Expected: PASS. `uv run alembic -c apps/api/alembic.ini check` style drift test if the repo has one (`tests/integration/test_migrations*.py` for the new revision).
- [ ] **Step 5: Commit** `feat(api/referrals): tables, and the reward as a wallet kind`.

### Task 3: Partners in the admin (API)

**Files:**

- Create: `referrals/{schemas.py,partners.py,admin_routes.py,stats.py}`
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `admin_routes.router`)
- Test: `apps/api/tests/integration/test_referrals_admin.py`, `apps/api/tests/integration/referrals_factory.py`

**Interfaces:**

- Consumes: `users.api.set_roles`, `admin.api.{require_admin, required_key, replayed, remember, record}`.
- Produces:
  - `partners.create_partner(db, *, user_id, code, percent: Decimal, term_months: int | None, note: str | None, admin_id) -> ReferralPartner` — 404 `user_not_found`, 409 `partner_exists`, 409 `code_taken`, 422 `code_invalid`; adds role `partner` to the account; audit `referrals.partner.create` (payload: code, percent, term_months — no note text).
  - `partners.update_partner(db, *, user_id, patch: PartnerPatch, admin_id) -> ReferralPartner` — 404 `partner_not_found`, 409 `code_locked` (code change after an attribution), 409 `code_taken`; audit `referrals.partner.update` with the changed field names and new values (not the note text).
  - `stats.partner_totals(db, partner_ids: list[str] | None) -> dict[str, PartnerTotals]` — one grouped query each for visits, attributions, rewards; `PartnerTotals{visits, accounts, purchases, revenue_uzs, held_uzs, credited_uzs}` (purchases/revenue = non-cancelled rewards count / `sum(base_uzs)`).
  - `stats.by_month(db, partner_id) -> list[MonthOut]` (Tashkent months, newest first, max 24).
  - Routes under `/admin/referrals` (all `require_admin`; writes keyed with `Idempotency-Key`, `replayed`/`remember`):
    - `GET /partners` → `AdminPartnersOut{items: [AdminPartnerOut]}` sorted by `revenue_uzs` desc; `AdminPartnerOut{user_id, display_name, steam_id, code, percent, term_months, active, note, created_at, totals}`.
    - `POST /partners` body `PartnerIn{user_id, code, percent, term_months=6, note=None}` → 201 `AdminPartnerOut`.
    - `PATCH /partners/{user_id}` body `PartnerPatch` (all optional; `term_months` explicit `null` = forever, so use `model_fields_set`) → `AdminPartnerOut`.
    - `GET /partners/{user_id}` → `AdminPartnerDetailOut{partner, months, rewards: [AdminRewardOut{order_number, delivered_at, base_uzs, percent, amount_uzs, status, available_at, credited_at, cancelled_reason}], next_cursor}` (cursor = `(delivered_at, order_id)`, 50 a page, malformed cursor → 422).
    - `GET /users/{user_id}` → `UserReferralOut{partner: PartnerRefOut{user_id, code, display_name} | null, attributed_at | null, is_partner: bool}`.

- [ ] **Step 1: Failing tests** — `test_create_adds_the_role_and_audits`, `test_code_rules` (bad shapes → 422 `code_invalid`; duplicate → 409 `code_taken`; second partner row for the user → 409 `partner_exists`), `test_percent_bounds_422`, `test_patch_term_to_forever_and_back`, `test_code_locked_after_an_attribution`, `test_list_totals_and_sort_by_revenue` (two partners with rewards in all three statuses; cancelled excluded from purchases/revenue), `test_detail_pages_rewards_with_cursor`, `test_user_block_shows_who_brought_them`, `test_replay_returns_the_first_answer`, `test_customers_get_403`. Factory `referrals_factory.py`: `make_partner(db, user=None, **over)`, `attribute(db, *, user, partner, at=None)`, `make_reward(db, *, partner, order, status="held", **over)`.
- [ ] **Step 2: Run** `uv run pytest apps/api/tests/integration/test_referrals_admin.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces. Code normalised with `.strip().lower()` before validation.
- [ ] **Step 4: Run** the file — Expected: PASS. `uv run ruff check` + `uv run mypy` on `modules/referrals`.
- [ ] **Step 5: Commit** `feat(api/referrals): partners in the admin`.

### Task 4: The link visit and the attribution at sign-in

**Files:**

- Create: `referrals/{visits.py,attribution.py,routes.py}`
- Modify: `auth/service.py` (`steam_login(..., ref_code: str | None = None)`), `auth/routes.py` (`steam_complete` reads cookie `csm_ref`, passes it, clears it on every outcome), `api/v1/router.py` (mount `routes.router`)
- Test: `apps/api/tests/integration/test_referrals_visit.py`, `apps/api/tests/integration/test_referrals_attribution.py`

**Interfaces:**

- Consumes: Task 1 `sign_in_by_steam`.
- Produces:
  - `REF_COOKIE = "csm_ref"`, `REF_MAX_AGE = 30 * 24 * 3600` (in `referrals/api.py`).
  - `visits.count_visit(db, partner: ReferralPartner, *, ip: str) -> bool` — the article-view pattern: salt `referrals:visit_salt:YYYY-MM-DD` (2 days), dedup key `referrals:visited:<sha256(salt|ip|partner_id)>` until UTC midnight; then `INSERT … ON CONFLICT (partner_id, day) DO UPDATE SET visits = visits + 1`. Redis down → not counted, still `False`, no error.
  - `POST /api/v1/referrals/visit` body `{code: str}` → 204 always (unknown / inactive code / banned partner too, no cookie). For an active partner: count, then `Set-Cookie: csm_ref=<code>; Max-Age=2592000; HttpOnly; SameSite=Lax; Secure in prod; Path=/` (host-only on the API host, like `csm_aid`). Keyless: docstring says it only moves a counter and remembers a link. `ip_guard` bucket `referral-visit`, 60 per 60 s (add to `core/config.py` buckets).
  - `attribution.attribute_new(db, *, user: User, code: str | None) -> bool` — writes `ReferralAttribution(user_id, partner_id, attributed_at=now())` when `code` names an active, unbanned partner whose `user_id != user.id`; else nothing. Called from `steam_login` only when `created and app == "web"`.

- [ ] **Step 1: Failing tests** — visit: `test_active_code_sets_the_cookie_and_counts`, `test_same_visitor_counts_once_a_day`, `test_unknown_or_inactive_code_sets_nothing` (204, no `set-cookie`), `test_redis_down_still_204`. Attribution (drive `steam_login` with the existing fake verifier used by the auth tests): `test_new_account_with_cookie_is_attributed`, `test_existing_account_is_not_attributed`, `test_admin_app_never_attributes`, `test_inactive_partner_cookie_ignored`, `test_cookie_cleared_on_success_and_on_refusal`.
- [ ] **Step 2: Run** both files — Expected: FAIL.
- [ ] **Step 3: Implement.** `steam_login` swaps `upsert_user_by_steam` for `sign_in_by_steam`; `dev_login` keeps `upsert_user_by_steam`.
- [ ] **Step 4: Run** both files plus `apps/api/tests/integration/test_auth*.py -k steam` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api/referrals): the link visit and the attribution at first sign-in`.

### Task 5: Rewards — accrue and settle, and the hourly job

**Files:**

- Create: `referrals/rewards.py`
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/referrals.py`; modify `main.py` (`referrals.register(scheduler)`)
- Test: `apps/api/tests/integration/test_referrals_rewards.py`, `apps/scheduler/tests/test_referrals_job.py`

**Interfaces:**

- Consumes: `orders.api.{Order, SkinTrade}`, `skinslink.api.SkinslinkPurchase`, `lisskins.api.LisskinsPurchase`, Task 2 `credit_referral_reward`.
- Produces:
  - `LOOKBACK = timedelta(days=14)`.
  - `rewards.accrue(db) -> int` — one `INSERT … SELECT … ON CONFLICT (order_id) DO NOTHING` for orders with `status = 'delivered'`, `api_key_id IS NULL`, `delivered_at >= now() - LOOKBACK`, buyer attributed, `delivered_at >= attributed_at`, `term_months IS NULL OR delivered_at < attributed_at + make_interval(months => term_months)`, partner `active` and its account not banned, `floor(price_uzs * percent / 100) > 0`. Stores `base_uzs`, `percent`, `amount_uzs`, `delivered_at`, `available_at = delivered_at + 8 days`. Commits; returns rows inserted.
  - `rewards.hold_state(db, order_ids) -> dict[str, Literal["rolled_back", "open", "clear"]]` — from the trade / purchase row of each order: `attention_reason = 'rolled_back'` (resolved or not) → `rolled_back`; another reason with `resolved_at IS NULL` → `open`; else `clear`.
  - `rewards.settle(db, *, limit: int = 200) -> SettleResult{credited, cancelled, waiting}` — takes due `held` rewards `FOR UPDATE SKIP LOCKED`, one SAVEPOINT each: `rolled_back` → `cancelled` + reason; `open` or partner banned → skip; else `credit_referral_reward`, `credited_at`; a `ConflictError` from the ledger (frozen) → roll back the savepoint, skip. Commits once. Logs `referrals.reward.credited` / `cancelled` with partner code and amount only.
  - Job `referrals.rewards`: every 3600 s, `first_run_after(480)`, runs `accrue` then `settle`; a crash is logged and retried next tick.

- [ ] **Step 1: Failing tests** — `test_accrues_a_delivered_order_in_term`, `test_skips_api_orders_undelivered_and_before_attribution`, `test_term_end_is_exclusive_and_forever_has_none` (6 months: an order at +6 months − 1 min earns, at +6 months does not; `term_months=None` earns at +5 years), `test_inactive_or_banned_partner_earns_nothing_new`, `test_accrue_is_idempotent`, `test_floor_and_zero_not_booked` (price 1 000, 0.1 % → 1; price 999 would be 0 — build with a price that floors to 0 and expect no row), `test_settle_credits_after_the_hold_only`, `test_rolled_back_is_cancelled_even_if_resolved` (one Waxpeer `SkinTrade`, one `SkinslinkPurchase`), `test_open_attention_waits_then_credits_after_resolution`, `test_frozen_wallet_waits_and_others_credit`, `test_settle_twice_books_once`. Scheduler: `test_job_registers_hourly_and_survives_a_crash` (the pattern of the existing job tests in `apps/scheduler/tests/`).
- [ ] **Step 2: Run** `uv run pytest apps/api/tests/integration/test_referrals_rewards.py apps/scheduler/tests/test_referrals_job.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; `hold_state` reads the three tables in at most three queries.
- [ ] **Step 4: Run** the same — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api/referrals): rewards accrue on delivery and credit after the hold`.

### Task 6: The partner's own API

**Files:**

- Modify: `referrals/routes.py`, `referrals/schemas.py`, `referrals/stats.py`
- Test: `apps/api/tests/integration/test_referrals_me.py`

**Interfaces:**

- Produces:
  - `GET /api/v1/referrals/me` (signed in) → 404 `not_a_partner` unless a partner row exists; `PartnerMeOut{code, percent, term_months, active, month: Counts, all_time: Counts, held_uzs, next_available_at | null, credited_uzs}`; `Counts{visits, accounts, purchases, earned_uzs}` (earned = held + credited, this Tashkent month / all time).
  - `GET /api/v1/referrals/me/rewards?cursor=` → `PartnerRewardsOut{items: [PartnerRewardOut{delivered_at, base_uzs, amount_uzs, status, available_at}], next_cursor}`, 20 a page, malformed cursor → 422.

- [ ] **Step 1: Failing tests** — `test_not_a_partner_404`, `test_counts_this_month_and_all_time`, `test_inactive_partner_still_sees_the_page`, `test_rewards_carry_no_buyer` (assert the JSON keys of an item are exactly `{delivered_at, base_uzs, amount_uzs, status, available_at}`), `test_rewards_page_and_bad_cursor`.
- [ ] **Step 2: Run** the file — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api/referrals): the partner's stats and rewards`.

### Task 7: «Партнёрам» in analytics

**Files:**

- Modify: `referrals/api.py` (`credited_between`), `analytics/schemas.py` (`Totals.partners_uzs: str`), `analytics/business.py`
- Test: `apps/api/tests/integration/test_analytics_partners.py`

**Interfaces:**

- Produces: `referrals.api.credited_between(db, *, since: datetime, until: datetime) -> Decimal` (sum of `amount_uzs`, `status = 'credited'`, `credited_at` in `[since, until)`). `Totals.partners_uzs` = that for the site channel and `"all"`, `"0"` for `api`. `gross_profit_uzs` unchanged.

- [ ] **Step 1: Failing test** — `test_partners_line_counts_credited_in_window_only` (credited inside, credited outside, held, cancelled → only the first), `test_api_channel_has_none`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** `summary` fetches it once alongside `buyback`.
- [ ] **Step 4: Run** the file and `apps/api/tests/integration/test_analytics*.py -k totals` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api/analytics): what partners were paid`.

### Task 8: API docs, client and the backend docs

**Files:**

- Run `make gen-api` (commits `docs/api/openapi.json` + `packages/api-client`).
- Create: `docs/decisions/0026-referrals.md` (attribution at account creation only; reward as a ledger kind with a house account; pull accrual by an hourly job instead of a hook in four `delivered` call sites — why: `orders` stays unaware of `referrals`, cost: up to an hour between delivery and the `held` row and the percent read at accrual).
- Create: `docs/runbooks/referrals.md` (add a partner from the user card; change terms; a rollback found after credit → «Коррекция баланса»; a frozen wallet; the alt-account risk and how to spot it: the partner's detail page, same trade link or card on the buyer's admin card).
- Modify: `referrals/README.md` (owns, interface, rules), `docs/architecture/module-map.md`, `docs/architecture/cache-keys.md` (two keys), `docs/security/pii-handling.md` (an attribution links two accounts; the partner never sees the buyer; no IP stored), `docs/api/README.md` (Referrals section: the keyless visit, the cookie, the 404), `wallet/README.md` (kind table rows), `scripts/check-module-coverage.py` + `apps/api/tests/unit/test_check_module_coverage.py` (`referrals`), `AGENTS.md` §9 list.
- Test: `apps/api/tests/unit/test_check_module_coverage.py`

- [ ] **Step 1:** Add `referrals` to the coverage script and its test fixture; run the unit test — Expected: PASS.
- [ ] **Step 2:** `make gen-api`; `git diff --stat docs/api packages/api-client` shows the new paths.
- [ ] **Step 3:** Write the docs above.
- [ ] **Step 4:** `npx prettier --check docs` from the root — Expected: clean.
- [ ] **Step 5: Commit** `docs(referrals): ADR-0026, runbook, module map, API notes`.

### Task 9: Storefront — the link, the partner page, the menu

**Files:**

- Create: `apps/web/src/components/referral/RefCapture.tsx` (+ test), `components/referral/PartnerView.tsx` (+ test), `lib/referrals.ts`
- Modify: `app/[locale]/layout.tsx` (mount `RefCapture`), `app/[locale]/account/referral/page.tsx` (render `PartnerView` instead of `ComingSoon`), `components/header/nav.ts` (`accountNav(isPartner: boolean)`), `AccountSidebar.tsx`, `AccountMenu.tsx`, `MobileMenu.tsx` (+ their tests), `components/account/ProfileView.tsx` + `ProfileSetup.tsx` (remove `ReferralTeaser`), `components/ComingSoon.tsx` (drop `"referral"`), `lib/balance.ts` (kind `referral_reward`), `packages/i18n/locales/{ru,uz,en}/web.json`

**Interfaces:**

- Consumes: Task 6 routes, `me.roles` contains `"partner"`.
- Produces:
  - `RefCapture`: on mount reads `ref` from `window.location.search`; if it matches `^[a-z0-9-]{3,32}$` → `fetch(API_BASE + "/api/v1/referrals/visit", {method: "POST", credentials: "include", headers: {"content-type": "application/json"}, body: JSON.stringify({code})})`, errors ignored; then `history.replaceState` without `ref` (other params kept).
  - `accountNav(isPartner)` → `ACCOUNT_NAV` without the `referral` entry unless `isPartner`.
  - `PartnerView` (client): signed out → the existing sign-in prompt pattern of account pages; 404 from `/referrals/me` → a short «Программа по приглашению» note; else: link `https://csmarket.uz/?ref=<code>` (from `WEB_ORIGIN`) with «Скопировать»; terms «<percent> % с покупок · <6 месяцев | навсегда>»; an «Отключена» badge when `active` is false; two count rows (this month / all time: переходы, новые аккаунты, покупки, заработано); money tiles «В ожидании» (+ «ближайшее начисление <date>») and «Начислено»; the rewards list (date, сумма покупки, начисление, статус «В ожидании до <date>» / «Начислено» / «Отменено») with «Показать ещё».
  - Wallet history label `referral_reward`: ru «Партнёрское начисление», uz «Hamkorlik daromadi», en «Partner reward».

- [ ] **Step 1: Failing tests** — `RefCapture.test.tsx`: posts once for a valid code and strips `ref` keeping `?sort=price`; ignores `ref=Bad Code!`. `PartnerView.test.tsx`: renders link, terms «1 % с покупок · 6 месяцев», «навсегда» for `null`, the inactive badge, the invitation note on 404, «Показать ещё» fetches the next cursor. Menu tests: the «Реферал» entry only for a `partner` role.
- [ ] **Step 2: Run** `pnpm --filter web exec vitest run src/components/referral src/components/header src/components/account` — Expected: FAIL.
- [ ] **Step 3: Implement**; strings in all three locales under `web.referral.*`.
- [ ] **Step 4: Run** the same, then `pnpm --filter web exec tsc --noEmit` and `pnpm --filter web exec eslint src/components/referral src/components/header src/components/account` — Expected: PASS; `pnpm --filter @csmarket/i18n test` parity — PASS.
- [ ] **Step 5: Commit** `feat(web/referral): the link, the partner page, the menu entry for partners`.

### Task 10: Admin — «Партнёры», the user card, the analytics tile

**Files:**

- Create: `apps/admin/src/features/referrals/{api.ts,labels.ts,PartnersPage.tsx,PartnerDetail.tsx,PartnerForm.tsx,UserReferralBlock.tsx}` + tests
- Modify: `app/router.tsx` (`/partners`, `/partners/:userId`), the admin `nav.ts` («Партнёры»), `features/users/UserCard.tsx` (mount `UserReferralBlock`), `features/users/labels.ts` (`referral_reward: "Партнёрское начисление"`), `features/analytics/{api.ts,Tiles.tsx,fixtures.ts}` (tile «Партнёрам»)

**Interfaces:**

- Consumes: Task 3 routes, Task 7 `partners_uzs`.
- Produces:
  - `PartnerForm` (create and edit): code, percent (step 0.1), term (number of months + checkbox «Навсегда»), note, «Активен» on edit; code disabled with hint «Код нельзя менять: по ссылке уже пришли люди» once `totals.accounts > 0`; when percent > 2 the warning «На скинах от $1 000 маржа может уйти в минус.» (role `status`, not blocking). Errors by code: `code_taken` «Такой код уже занят», `code_invalid` «Только латиница, цифры и дефис, 3–32 символа», `code_locked`, `partner_exists`.
  - `PartnersPage`: the table (аккаунт, код, %, срок, активен, переходы, аккаунты, покупки, выручка, в ожидании, начислено), rows link to detail.
  - `PartnerDetail`: the form (edit), months table, rewards with order numbers linking to `/orders/:number`, «Показать ещё».
  - `UserReferralBlock`: «Привёл: <name> (<code>)» linking to the partner, or «Пришёл сам»; for a non-partner a «Сделать партнёром» button opening `PartnerForm` (create, `user_id` fixed); for a partner «Партнёр: <code>» linking to its page.

- [ ] **Step 1: Failing tests** — form: warning appears at 2.1 and not at 2.0; «Навсегда» sends `term_months: null`; locked code disabled; server error codes show their text. Page: rows sorted as the API gives, links. Block: three states. Tiles: «Партнёрам» shows `partners_uzs`.
- [ ] **Step 2: Run** `pnpm --filter admin exec vitest run src/features/referrals src/features/users src/features/analytics` — Expected: FAIL.
- [ ] **Step 3: Implement** with the existing admin patterns (`useIdempotencyKey`, `ApiError` codes, TanStack Query invalidation of `["referrals"]`).
- [ ] **Step 4: Run** the same, `pnpm --filter admin exec tsc --noEmit`, eslint on touched folders — Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin/referrals): partners, the user card block, the analytics tile`.

### Task 11: Finish

- [ ] **Step 1:** `npx prettier --check .` from the root; `uv run ruff check apps/api apps/scheduler`; `uv run mypy` on `modules/referrals`, `modules/wallet`, `modules/auth`, `modules/users`, `modules/analytics` — Expected: clean.
- [ ] **Step 2:** AGENTS.md §0: a «Referrals» status line (built on branch `referrals`, not merged).
- [ ] **Step 3: Commit** `docs: referrals status`. Then the final review (executing-plans), and the push of the branch for CI only on the owner's word.
