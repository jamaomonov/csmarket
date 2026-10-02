# M4b — Live Order Updates, Email, Pricing Editor, Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The order page updates the moment an order moves (WebSocket nudge, polling stays the
reconciler); a buyer with a verified email gets a receipt, a «обмен отправлен» and a «деньги
вернулись» letter in their language; an admin edits the pricing document with a live preview and
per-item overrides, and opens a dashboard with today / 7 / 30-day sales, margin, the Waxpeer
balance and what needs attention; the order's trade-link token is erased 30 days after the order
ends.

**Architecture:** A new `realtime` module holds one Postgres `LISTEN order_events` connection per
API process and fans nudges out to authenticated WebSockets; every order status change sends
`pg_notify('order_events', …)` in its own transaction, so a nudge is delivered only on commit. A
new `notifications` module owns an `email_outbox` table (the queue, ADR-0064 shape like `orders`):
rows are written in the same transaction as the event and drained by a worker `emails` queue that
renders ru/uz/en templates and sends through Resend's HTTP API with the outbox id as the
idempotency key. Pricing writes reuse M2's `lock_pricing` / `save_rules` / `reprice_rows`; the
dashboard reads orders plus a Waxpeer balance the `orders.health` job caches in Redis.

**Tech Stack:** FastAPI (WebSocket) · SQLAlchemy 2 async · asyncpg `LISTEN` · Alembic · Postgres 16
· Redis 7 · APScheduler · httpx (Resend REST, no SDK) · pytest + testcontainers + respx · Next.js 15

- next-intl · Vite + React 19 + TanStack Query · Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md` — §3.2 (`notifications`,
`realtime`), §5, §7.6–§7.8 (WS event, email), §9 (pricing document + preview + per-item
overrides), §10 (order page WS-driven; admin Dashboard, Pricing), §11, §12, §13, §14, §15 row M4
(M4b part). ADR-0007 R15 lists this scope. Rulebook: `AGENTS.md` (§4–§12, §14).

**Source material (read-only):** `/Users/macbook_uz/Projects/yupay` — never write there. Useful:
`docs/decisions/0040-order-realtime-ws.md`, `docs/decisions/0027-resend-email-channel.md`,
`apps/api/src/yupay/modules/realtime/*`, `modules/notifications/{channels/email.py,templates.py}`,
`tests/contract/test_resend_email.py`, web `hooks/useOrderSocket.ts`, `lib/realtime.ts`, admin
`features/skins/{SkinPricingPage,PricingRulesCard,PricePreviewCard,ItemOverrideCard,SkinSalesPage}.tsx`

- tests. YuPay's designs differ on purpose where the rulings below say so.

## Global Constraints

- **Owner decisions (2026-10-01/02):** (D1) order emails go **only to a verified address** — a buyer confirms their email by a link; the confirmation letter itself is the only mail sent to an unverified address; (D2) the dashboard shows **today / 7 days / 30 days**, days counted in Tashkent time (UTC+5); (D3) the order's trade-link **token is erased 30 days after the order reaches a terminal status**, keeping the Steam account and the masked form; (D4) a rollback after delivery is never refunded by the app (ADR-0007); (D5) Resend is the email provider.
- **Money:** `Decimal`; soʻm whole units, USD as strings; never floats. Pricing writes go through `lock_pricing` → `save_rules` / item columns → `reprice_rows` in one transaction, then `publish_rules` + `bump_catalog_version` **after** commit.
- **A nudge carries no data a client trusts:** `{type, number}` only; the client re-reads `GET /orders/{number}`. Polling (`lib/order-poll.ts`) stays the reconciler — the socket never silences it.
- **Email:** sent only from the worker; a row is enqueued in the same transaction as the event it reports (atomic); a send is idempotent (provider `Idempotency-Key` = outbox id) and retried with backoff; a failed send never touches money or order state. The recipient is resolved **at send time** from `users` (verified address only; the verify letter snapshots the address it verifies). Letters never contain a trade link, a Steam ID or the buyer's balance.
- **Never log PII or secrets:** email addresses, Steam IDs, trade links/tokens, IPs, the Resend key, verification tokens. Log the outbox id, kind, order number, outcome.
- **Idempotency & limits:** state-changing endpoints take `Idempotency-Key` (16–160) — admin writes as in M3/M4a; `ip_guard` buckets `email-verify` (60/min per IP, 10/min per IP + account) and `ws-connect` (60/min per IP).
- **Copy (owner):** short sentences; outcome, not mechanism; no Waxpeer / marketplace / refund internals for customers; «вы»; ru / uz / en for every customer string and every email; UZ ʻ (U+02BB) after o/g, ʼ (U+02BC) elsewhere; admin copy is Russian; skin names English. (AGENTS §12)
- **Forbidden tokens** in `apps/*/src`, `packages/*/src`: `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`, `merchant_api`, `voucher`, `game_id`. (AGENTS §6)
- **Module direction:** `orders` may import `notifications.api` (enqueue) and `realtime.api` (nudge); `notifications.api` and `realtime.api` import nothing from `orders` or `payments` at import time (the worker-side sender reads orders through `orders.api`, imported lazily); `orders.api` still never imports `payments` (ADR-0007 Ruling A). Routers mount in `api/v1/router.py`; every route change regenerates `docs/api/openapi.json` + client (`make gen-api`); `tests/unit/test_import_order.py` lists every new module.
- **Scheduler:** jobs only time work; new interval jobs take `first_run_after(320)` / `(340)`; nightly cron jobs use fixed UTC times (no first-run stagger). The ordered job-id list in `apps/scheduler/tests/test_main.py` is updated with each new job.
- **Migrations:** `0015_email_outbox` (Task 3), `0016_orders_dashboard` (Task 9), `0017_orders_trade_link_erased` (Task 11); each `down_revision` is the previous one.
- **Coverage:** `orders`, `payments`, `wallet`, `skins` ≥ 95 % (enforced by `scripts/check-module-coverage.py`); `notifications` and `realtime` join the gate in Task 13.
- **Dev ports / processes:** api 8100, web 3100, admin 3102; never touch `yupay*` containers or testcontainers you did not start; kill processes by PID only; `docker compose down` without `-v`.
- **Commits:** Conventional Commits, scopes `api/orders`, `api/realtime`, `api/notifications`, `api/users`, `api/skins`, `api/admin`, `worker`, `scheduler`, `web/orders`, `web/account`, `admin/pricing`, `admin/dashboard`, `infra`, `e2e`, `docs`; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push without the owner's word.

## Rulings taken while planning (owner may veto)

- **R1 — Fan-out through Postgres `LISTEN`, not Redis pub/sub.** Every status writer already runs in a transaction the caller commits later; `pg_notify('order_events', '<user_id>:<number>')` in that transaction is delivered only on commit, so a client re-reading on the nudge always sees the new state (YuPay published to Redis before commit). The API process keeps **one** asyncpg `LISTEN` connection (started in the lifespan, reconnecting with backoff) and an in-process registry `user_id → set[socket]`. One uvicorn process per API container (AGENTS §11) makes this sufficient; a second API replica would also LISTEN and serve its own sockets. The payload is internal ids only and is never logged.
- **R2 — WebSocket auth by first message, not by URL.** The browser opens `wss://api…/api/v1/realtime/orders`, then sends `{"type":"auth","token":"<access token>"}` within 5 s; the server verifies it with `auth.api.authenticate(db, token)` (a new export wrapping `resolve_current_user`), subscribes the socket to that user only, and closes the socket with code 4401 on a bad/expired token and at the token's `exp` (the client reconnects with a fresh token). Nothing secret travels in a URL (Cloudflare and browsers log URLs); no new JWT kind is needed.
- **R3 — Nudges, not payloads:** server → client messages are `{"type":"order.changed","number":"…"}` and `{"type":"ping"}` (every 25 s). The client invalidates the order, the orders list and — on any change — the balance and entries. No toast in M4b (no toast mechanism exists; the order page shows the state).
- **R4 — Which events nudge:** `mark_paid` (paid), `_claim` (buying), `trades.apply` results `trade_sent` / `delivered` / `returned` / `rolled_back`, `refund_to_balance` (failed/returned + refunded), `expire_pending` (cancelled). One helper `realtime.api.nudge(db, *, user_id, number)` issues the `pg_notify`.
- **R5 — Email outbox:** table `email_outbox(id uuid, kind, user_id, order_id null, address citext null (verify only), payload jsonb, status pending|sent|skipped|failed, attempts int, next_attempt_at, sent_at, provider_message_id, last_error_code, created_at, updated_at)`; unique `(order_id, kind)` for order kinds (a replay never enqueues twice); partial index on claimable rows. Enqueue + `pg_notify('emails', id)` in the event's transaction. Kinds: `receipt` (at `mark_paid`), `trade_sent` (at `trades.apply` → `trade_sent`; skipped when an order jumps straight to `delivered`), `refunded` (at `refund_to_balance` → True), `verify` (email confirmation). The worker `emails` queue claims `FOR UPDATE SKIP LOCKED`, resolves the user: order kinds need `email_verified_at` and the same address → else `skipped`; renders in `users.locale`; sends; retries with backoff 1, 5, 15, 60, 180, 600 min (6 attempts) then `failed` + metric + alert. Resend 4xx except 429 → `failed` at once (no retry storm on a bad address).
- **R6 — Dev transport:** `email_transport: Literal["resend","dev"]` (default `dev`; prod refuses `dev` at start-up). The dev transport stores the last 50 rendered letters in Redis (`notifications:dev:mail`, 1 h TTL) and a dev-only `GET /api/v1/dev/emails?kind=&to_user=` returns them to their owner (e2e reads the verification link there). No Resend key is needed locally.
- **R7 — Email verification:** token = HMAC-SHA256 (purpose key from `core.crypto` / `app_enc_key`) over `user_id|email|exp`, base64url, 24 h; stateless. `PATCH /me` with a new email enqueues a `verify` letter; `POST /me/email/verification` re-sends (cooldown 60 s per user in Redis, `ip_guard email-verify`); `POST /email/confirm {token}` is **anonymous** (the link may be opened on another device), sets `email_verified_at` only if the user's current email still equals the token's, and is idempotent. The storefront page `/account/email/confirm?token=` calls it and shows the result.
- **R8 — Pricing editor API:** `GET /admin/skins/pricing` (rules + `updated_at/by` + catalogue counts), `PUT /admin/skins/pricing` (key required; `lock_pricing` → `save_rules` → `reprice_rows(all)` → audit `skins.pricing.save` → replay → commit → `publish_rules` → `bump_catalog_version`), `POST /admin/skins/pricing/preview` (body: optional draft `rules` + either `slug` or `cost_usd`/`category`/`weapon`/`count_auto`/`item_pp`/`fixed_price_usd`; answers every `Quote` component and the soʻm price at the current rate; writes nothing, keyless — the docstring says why), `PUT /admin/skins/items/{slug}/pricing` (`{margin_override_pp, fixed_price_usd}` each nullable; key required; `lock_pricing` → set → `reprice_rows(ids=[item.id])` → audit `skins.item.override` → commit → `bump_catalog_version`). The existing hide/show `PATCH` stays as is.
- **R9 — Dashboard definitions:** a **sale** is an order with `paid_at` in the window that is not refunded (`refunded_at IS NULL`); revenue = Σ `price_uzs` (and Σ `price_usd`); cost = Σ `COALESCE(bought_units/1000, cost_usd)`; margin = revenue_usd − cost; **refunds** = orders with `refunded_at` in the window (count, Σ `price_uzs`); **in flight** = `paid|buying|trade_sent` now; **attention** = open attentions now; per Tashkent day rows for the window. `GET /admin/dashboard?days=1|7|30`.
- **R10 — Waxpeer balance on the dashboard comes from Redis:** the `orders.health` job, on each balance read, also writes `orders:waxpeer:balance` = `{usd, read_at}` (TTL 1 h); the dashboard shows it with its age, or «неизвестно». No new request-path Waxpeer call.
- **R11 — Trade-link erase:** nightly cron 22:00 UTC (03:00 Tashkent): terminal orders whose terminal timestamp (`delivered_at`, `cancelled_at` or `failed_at`) is older than 30 days and `trade_link_erased_at IS NULL` get `trade_link` rewritten to the masked form `https://steamcommunity.com/tradeoffer/new/?partner=<partner>&token=••••XY` and `trade_link_erased_at = now()`, in batches of 500. The admin view shows the stored masked form for erased orders. Nothing reads `trade_link` for a terminal order.
- **R12 — Carry-overs:** (Z) `admin_actions.refund_refusal` answers `order_in_flight` when `trade.buy_unconfirmed_at` is set and later than `trade.resolved_at` (a lost answer newer than the operator's check); (Z2) `buy_rules.link_refused` matches the unambiguous link phrases (`tradelink`, `trade link`, `trade url`) anywhere, and the ambiguous ones (`private inventory`, `inventory is private`, `trade ban`, `cannot trade`, `can't trade`, `can not trade`) only when the message also names the buyer (`buyer`, `your`, `partner`, `receiver`, `recipient`).
- **R13 — Not in M4b:** Waxpeer `my-history` orphan probe (needs the real key on the VPS — M5), marketing email, unsubscribe management (transactional only), a chart library in the admin (tables + tiles).

## Review Focus

1. **A nudge never arrives before the data:** the client re-reads after a nudge and must see the new status — never the old one. → Task 2 `test_nudge_is_delivered_only_after_commit`.
2. **A socket never sees another user's orders, and a dead token closes the socket.** → Task 2 `test_socket_receives_only_its_users_orders`, `test_bad_token_closes_4401`, `test_socket_closes_at_token_expiry`.
3. **One event, one letter; no letter to an unverified or changed address:** a replayed settle, a re-run reconcile, a retried send → one letter; an address changed after the order → `skipped`. → Task 4 `test_replayed_paid_enqueues_one_receipt`, `test_send_skips_unverified_address`, `test_retry_reuses_idempotency_key`.
4. **A pricing save that fails leaves the old prices everywhere** (DB, Redis cache, catalogue pages); a preview never writes. → Task 7 `test_failed_save_keeps_old_rules_and_cache`, `test_preview_writes_nothing`.
5. **A confirmation link for an old address cannot verify a new one; a forged or expired token is refused.** → Task 5 `test_token_for_old_email_does_not_verify_new_one`, `test_tampered_or_expired_token_is_refused`.

---

## File structure (what M4b creates or changes)

```
apps/api/src/csmarket/
├── modules/realtime/{__init__,api,listener,registry,routes}.py + README.md        (T2)
├── modules/notifications/{__init__,api,models,outbox,sender,resend,dev_transport,
│                          templates/{__init__,receipt,trade_sent,refunded,verify,layout}.py,
│                          copy.py,routes_dev}.py + README.md                         (T3, T4)
├── modules/users/{email_verify,routes,service}.py                                  (T5)
├── modules/orders/{paid,buying,trades,refunds,expiry,admin_actions,buy_rules,
│                   dashboard,erase}.py                                              (T1, T2, T4, T9, T11)
├── modules/skins/{admin_routes,admin_schemas,pricing_admin}.py                      (T7)
├── modules/admin/{dashboard_routes,dashboard_schemas}.py                            (T9)
├── modules/auth/api.py (authenticate)                                               (T2)
├── core/{config,metrics,logging,crypto}.py                                          (T2–T5)
apps/api/migrations/versions/0015_email_outbox.py 0016_orders_dashboard.py 0017_orders_trade_link_erased.py
apps/worker/src/csmarket_worker/consumer.py (emails queue)                           (T3)
apps/scheduler/src/csmarket_scheduler/jobs/{orders_erase,orders_health}.py           (T9, T11)
apps/web/src/lib/realtime.ts, hooks/useOrderSocket.ts, components/Providers.tsx,
  components/account/EmailForm.tsx, app/[locale]/account/email/confirm/page.tsx     (T6, T10)
apps/admin/src/features/{pricing,dashboard}/*                                        (T8, T12)
e2e/tests/{live,email,admin-pricing}.spec.ts                                         (T13)
docs/: decisions/0008-realtime-and-email.md, runbooks/{email,pricing}.md, …           (T14)
```

---

### Task 1: Carry-overs — refund re-check window, buyer-scoped link hints

**Files:**

- Modify: `apps/api/src/csmarket/modules/orders/admin_actions.py` (`refund_refusal`, lines ~108–125), `apps/api/src/csmarket/modules/orders/buy_rules.py` (`_LINK_HINTS`, `link_refused`, lines ~22–43), `docs/runbooks/orders.md`, `docs/decisions/0007-orders-buying-trades.md` (rulings Z/Z2 → closed)
- Test: `apps/api/tests/integration/test_admin_orders.py` (extend), `apps/api/tests/unit/test_buy_rules.py` (create or extend)

**Interfaces:**

- Produces: `refund_refusal` returns `"order_in_flight"` when `trade.buy_unconfirmed_at is not None and (trade.resolved_at is None or trade.buy_unconfirmed_at > trade.resolved_at)`; `link_refused(err) -> bool` per R12.

- [ ] **Step 1: Tests first**

```python
# apps/api/tests/unit/test_buy_rules.py
import pytest

from csmarket.modules.orders.buy_rules import link_refused
from csmarket.modules.skins.api import WaxpeerError


@pytest.mark.parametrize(
    "message",
    ["Invalid tradelink", "Bad trade link", "trade url is broken",
     "Your inventory is private", "Buyer has a trade ban", "partner cannot trade"],
)
def test_buyer_link_refusals_are_recognised(message: str) -> None:
    assert link_refused(WaxpeerError(message))


@pytest.mark.parametrize(
    "message",
    ["Seller cannot trade right now", "Item owner has a trade ban", "inventory is private",
     "Price changed"],
)
def test_seller_side_or_unscoped_refusals_are_not_the_buyers_link(message: str) -> None:
    assert not link_refused(WaxpeerError(message))
```

Integration (`test_admin_orders.py`): a `buying` order with a resolved `waxpeer_forbidden` attention and `buy_unconfirmed_at` one minute after `resolved_at` → refund 409 `order_in_flight`, `can_refund` false; with `buy_unconfirmed_at` before `resolved_at` → the existing refund path (lookup-first) proceeds.

- [ ] **Step 2: Implement** (one condition in `refund_refusal` before `buy_running`; split `_LINK_HINTS` into `_LINK_PHRASES` and `_AMBIGUOUS_HINTS` + `_BUYER_WORDS`); update the runbook rows and mark Z/Z2 closed in ADR-0007.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_buy_rules.py tests/integration/test_admin_orders.py tests/integration/test_orders_buying.py -q
cd ../.. && make lint typecheck
git add -A && git commit -m "fix(api/orders): close the refund re-check window and scope link hints to the buyer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Realtime — order nudges over a WebSocket

**Files:**

- Create: `apps/api/src/csmarket/modules/realtime/{__init__,api,listener,registry,routes}.py`, `modules/realtime/README.md`
- Modify: `modules/auth/api.py` (+ `authenticate`), `modules/orders/{paid,buying,trades,refunds,expiry}.py` (call `nudge`), `bootstrap.py` (start/stop the listener in the lifespan), `api/v1/router.py`, `core/config.py` (`auth_ip_guard_bucket_max["ws-connect"] = 60`, `realtime_ping_seconds: int = 25`, `realtime_auth_timeout_seconds: float = 5`), `core/metrics.py` (`csmarket_ws_connections` gauge, `csmarket_ws_nudges_total`), `docs/architecture/{metrics,module-map,cache-keys}.md`, `docker-compose.prod.yml` (the `ulimits` comment: one LISTEN connection, not one Redis connection per socket), `tests/unit/test_import_order.py`
- Test: `apps/api/tests/integration/test_realtime_ws.py`, `apps/api/tests/integration/test_realtime_nudges.py`, `apps/api/tests/unit/test_realtime_registry.py`

**Interfaces:**

- Produces:
  - `realtime.api.CHANNEL = "order_events"`; `async def nudge(db: AsyncSession, *, user_id: str, number: str) -> None` → `SELECT pg_notify('order_events', user_id || ':' || number)` (never logs the payload); exported for `orders`.
  - `realtime.registry.Registry` with `add(user_id, socket)`, `remove(user_id, socket)`, `async publish(user_id, number) -> int` (sends `{"type":"order.changed","number":…}` to every socket of the user; a socket that fails to send is removed); one module-level instance.
  - `realtime.listener.OrderEventsListener(dsn)`: `start()` / `stop()`; one asyncpg connection with `add_listener(CHANNEL, …)`; parses `user_id:number`, calls `registry.publish`; reconnects with backoff 1→30 s; started in `bootstrap.lifespan` when `realtime_enabled` (default true; tests switch it per case).
  - WS route `/api/v1/realtime/orders` (R2): accept → wait ≤ `realtime_auth_timeout_seconds` for `{"type":"auth","token":…}` → `authenticate` (any error → close 4401) → `guard_ip(bucket="ws-connect")` before accept (over → close 4429) → register → loop: ping every `realtime_ping_seconds`, drain client frames, close 4401 at the token's `exp`; always unregister. Not in OpenAPI (documented in `docs/api/README.md`).
  - `auth.api.authenticate(db: AsyncSession, token: str) -> AuthenticatedUser(frozen: user_id, expires_at)` (wraps `resolve_current_user`, keeps the ban/blocklist checks).
  - Nudge call sites (R4), each right after its state write, in the same transaction: `orders.paid.mark_paid`, `orders.buying._claim`, `orders.trades.apply` (when it returns `trade_sent`/`delivered`/`returned`/`rolled_back`), `orders.refunds.refund_to_balance` (when it returns True), `orders.expiry.expire_pending` (per cancelled order).

- [ ] **Step 1: Tests first.** WebSocket tests build their own app with `create_app()` and Starlette's `TestClient` (the integration client has no `websocket_connect`; YuPay's `test_realtime_ws.py` shows the pattern), against the per-worker Postgres testcontainer:

```python
def test_socket_receives_only_its_users_orders(ws_app, two_users) -> None:
    a, b = two_users
    with ws_app.websocket_connect("/api/v1/realtime/orders") as ws:
        ws.send_json({"type": "auth", "token": a.access_token})
        notify_committed(user_id=b.id, number="B0000001")      # another user's order
        notify_committed(user_id=a.id, number="A0000001")
        assert ws.receive_json() == {"type": "order.changed", "number": "A0000001"}


def test_bad_token_closes_4401(ws_app) -> None:
    with ws_app.websocket_connect("/api/v1/realtime/orders") as ws:
        ws.send_json({"type": "auth", "token": "nope"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


async def test_nudge_is_delivered_only_after_commit(db, listen_order_events, buyer) -> None:
    await nudge(db, user_id=buyer.id, number="A0000001")
    assert await listen_order_events.next(timeout=0.5) is None        # not yet committed
    await db.commit()
    assert await listen_order_events.next(timeout=2) == f"{buyer.id}:A0000001"
```

Also: no auth message within the timeout → 4401; `test_socket_closes_at_token_expiry` (mint a token expiring in 2 s); ping arrives; the registry drops a socket whose send fails; the listener reconnects after its connection is killed (`pg_terminate_backend`) and keeps delivering; each R4 call site emits exactly one nudge for its transition (`test_realtime_nudges.py`: pay from balance, `_claim`, `apply` trade_sent/delivered/returned, refund, expiry) and none on a no-op (`unchanged`, `held`, a replayed settle); `ws-connect` bucket closes the 61st connection per minute per IP with 4429; no log line contains a token or a user id.

- [ ] **Step 2: Implement.** `orders` imports `realtime.api` (module direction rule); `realtime` imports nothing from `orders`.
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_realtime_ws.py tests/integration/test_realtime_nudges.py tests/unit/test_realtime_registry.py tests/unit/test_import_order.py -q
uv run pytest -n auto -q && cd ../.. && make lint typecheck
git add -A && git commit -m "feat(api/realtime): order nudges over a WebSocket, delivered on commit through Postgres LISTEN

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Notifications foundation — outbox, Resend transport, worker queue

**Files:**

- Create: `apps/api/src/csmarket/modules/notifications/{__init__,api,models,outbox,sender,resend,dev_transport,routes_dev}.py`, `modules/notifications/README.md`, `apps/api/migrations/versions/0015_email_outbox.py`, `docs/decisions/0008-realtime-and-email.md` (draft: R1–R7; Task 14 finishes it)
- Modify: `core/config.py` (`email_transport: Literal["resend","dev"] = "dev"`, `resend_api_key: str = ""`, `resend_base_url: str = "https://api.resend.com"`, `email_from: str = "noreply@csmarket.uz"`, `email_from_name: str = "CS Market"`, `email_send_timeout_seconds: float = 10`; validator: prod refuses `dev`), `bootstrap._REQUIRED_IN_PROD` (+ `CSMARKET_RESEND_API_KEY`), `core/logging.py` (`resend_api_key`, `address`, `recipient`, `to` redacted), `core/metrics.py` (`csmarket_emails_total{kind,outcome}` pre-created), `.env.example`, `infra/secrets-example/api.env`, `apps/worker/src/csmarket_worker/consumer.py` (`emails` queue + models import; fix the single-tuple unpack test), `migrations/env.py`, scheduler `main.py` models import, integration `conftest.py` `_EMPTY_IN_ORDER` (`email_outbox` first), `api/v1/router.py` (dev router behind `dev_gate`), `infra/prometheus/alerts/notifications.yml` (`EmailsFailing`: `increase(csmarket_emails_total{outcome="failed"}[30m]) > 0`, warn; runbook `docs/runbooks/email.md#failing`), `docs/architecture/{metrics,module-map,cache-keys}.md`
- Test: `apps/api/tests/contract/test_resend.py`, `apps/api/tests/integration/test_email_outbox.py`, `apps/api/tests/unit/test_notifications_config.py`, worker `tests/test_consumer.py` (update)

**Interfaces:**

- Produces:
  - Model `EmailOutbox` (`email_outbox`) per R5: `KINDS = ("receipt","trade_sent","refunded","verify")`, `STATUSES = ("pending","sent","skipped","failed")`, unique `uq_email_outbox_order_kind (order_id, kind) WHERE order_id IS NOT NULL`, index `ix_email_outbox_claimable (next_attempt_at) WHERE status = 'pending'`.
  - `notifications.api.EMAILS_CHANNEL = "emails"`; `async def enqueue(db, *, kind: str, user_id: str, order_id: str | None = None, address: str | None = None, payload: dict[str, str] | None = None) -> str | None` — inserts with `ON CONFLICT DO NOTHING` on the order/kind key (returns `None` when it already exists), sends `pg_notify('emails', id)`; flushes, never commits.
  - `notifications.resend.ResendClient(api_key, base_url, timeout)`: `async send(*, to: str, subject: str, html: str, text: str, idempotency_key: str) -> str` (POST `/emails`, `Authorization: Bearer`, `Idempotency-Key`; → Resend id); errors `EmailRetryableError` (network, timeout, 429, 5xx) and `EmailRejectedError` (other 4xx).
  - `notifications.dev_transport.DevTransport(redis)`: same `send` signature; LPUSH the rendered letter `{to_user, kind, subject, text, html, at}` to `notifications:dev:mail` (trim 50, TTL 1 h); returns a fake id.
  - `notifications.sender.drain_emails(db, *, limit=20) -> int` — the worker drain: claim pending due rows `FOR UPDATE SKIP LOCKED`, per row in a SAVEPOINT: resolve the recipient (R5), render via `notifications.templates.render(kind, locale, payload, order)` (Task 4 fills the templates; Task 3 ships a minimal `verify`-only renderer and a stub that raises `NotImplementedError` for order kinds, replaced in Task 4), send, write `sent`/`skipped`/retry/`failed`, metric; returns claimed count.
  - Worker: `Queue(name="emails", channel=EMAILS_CHANNEL, drain=_drain_emails, concurrency=1)`.
  - Dev-only `GET /api/v1/dev/emails?kind=` → the signed-in user's letters from the dev transport (404 unless `dev_login_active`).

- [ ] **Step 1: Tests first** — Resend contract (port `yupay:apps/api/tests/contract/test_resend_email.py`: success returns the id and sends `Authorization: Bearer` + `Idempotency-Key`; 429/5xx/network → retryable; 422 → rejected; the key never appears in logs); outbox: enqueue twice for one order/kind → one row; `notify` is sent with the insert and delivered on commit; drain sends a `verify` letter via the dev transport; `test_retry_reuses_idempotency_key` (a retryable failure reschedules with the same row id as key; the second attempt succeeds); rejected → `failed` immediately; six retryable failures → `failed`; a row whose recipient has no verified email → `skipped` (`test_send_skips_unverified_address` — with an order kind fixture inserted directly); a crash inside one row does not stop the drain; config: prod + `dev` transport refused; worker registers both queues.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/contract/test_resend.py tests/integration/test_email_outbox.py tests/unit/test_notifications_config.py tests/integration/test_migrations.py -q
uv run pytest -n auto -q && cd ../worker && uv run pytest -q && cd ../..
docker run --rm -v "$PWD/infra/prometheus:/p" --entrypoint promtool prom/prometheus check rules /p/alerts/notifications.yml
make lint typecheck
git add -A && git commit -m "feat(api/notifications): email outbox drained by the worker, Resend and dev transports

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Order letters — templates in three languages, enqueue at the events

**Files:**

- Create: `apps/api/src/csmarket/modules/notifications/templates/{__init__,layout,receipt,trade_sent,refunded,verify}.py`, `modules/notifications/copy.py` (ru / uz / en strings)
- Modify: `modules/notifications/sender.py` (real `render` for every kind), `modules/orders/{paid,trades,refunds}.py` (call `enqueue`), `modules/notifications/README.md`
- Test: `apps/api/tests/unit/test_email_templates.py`, `apps/api/tests/integration/test_order_emails.py`

**Interfaces:**

- Consumes: Task 3 `enqueue`, `EmailOutbox`, `drain_emails`; `orders.api` (lazily, worker side) for the order's number, item name, phase, `price_uzs`, `send_until` from its trade.
- Produces:
  - `templates.render(kind: str, *, locale: Literal["ru","uz","en"], number: str | None, payload: Mapping[str, str], links: Links) -> EmailContent(frozen: subject, html, text)`; `Links(order_url, balance_url, confirm_url)` built from `web_base_url` + locale prefix (`""` for ru, `/uz`, `/en`) + `/orders/{number}`, `/account/balance`, `/account/email/confirm?token=…`.
  - Layout: table-based, inline styles, PNG logo at `{web_base_url}/logo/email-logo.png` (the file is added under `apps/web/public/logo/`), one CTA button with a plain-text fallback link, footer «csmarket.uz — скины CS2 в Узбекистане» (per locale). No external fonts, no tracking pixels.
  - Copy (ru; uz/en equivalents in `copy.py`):
    - `receipt` — subject «Заказ #{number} оплачен»; body «Оплата получена. Покупаем {skin} — обмен придёт в Steam, примите его.»; button «Открыть заказ».
    - `trade_sent` — subject «Обмен по заказу #{number} отправлен»; body «Продавец отправил обмен в Steam. Примите его до {time} по Ташкенту.»; button «Открыть заказ».
    - `refunded` — subject «Деньги по заказу #{number} на балансе»; body «Обмен не состоялся. {amount} вернулись на баланс csmarket.»; button «Открыть баланс».
    - `verify` — subject «Подтвердите почту»; body «Нажмите кнопку, чтобы получать письма о заказах. Ссылка действует 24 часа. Если это были не вы, просто удалите письмо.»; button «Подтвердить почту».
  - Enqueue call sites (same transaction as the event): `mark_paid` → `receipt`; `trades.apply` returning `trade_sent` → `trade_sent` with `payload={"send_until": <ISO>}`; `refund_to_balance` returning True → `refunded` with `payload={"amount_uzs": …}`.

- [ ] **Step 1: Tests first** — each template × each locale renders a non-empty subject/html/text containing the number and the right link, never a trade link, Steam ID or balance; HTML escapes the skin name (`<script>` in a name stays text); `{time}` is in Tashkent time; `test_replayed_paid_enqueues_one_receipt` (settle twice through two kassa attempts → one `receipt` row); a reconcile jump `buying → delivered` enqueues no `trade_sent`; a `held` or replayed refund enqueues nothing; an end-to-end drain of each order kind with a verified buyer produces one dev-transport letter in the buyer's locale; a buyer who changed email after verifying → `skipped`.
- [ ] **Step 2: Implement** (port the layout helpers of `yupay:apps/api/src/yupay/modules/notifications/templates.py` with csmarket branding and copy; no YuPay strings).
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_email_templates.py tests/integration/test_order_emails.py -q
uv run pytest -n auto -q && cd ../.. && make lint typecheck && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/notifications): receipt, trade sent and refunded letters in ru, uz and en

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Email verification

**Files:**

- Create: `apps/api/src/csmarket/modules/users/email_verify.py`
- Modify: `modules/users/{routes,service,schemas}.py`, `core/crypto.py` (purpose `email-verify` if a helper is needed), `core/config.py` (`auth_ip_guard_bucket_max["email-verify"] = 60`, `email_verify_ttl_hours: int = 24`, `email_verify_cooldown_seconds: int = 60`), `docs/api/openapi.json` + client, `docs/security/pii-handling.md`, `docs/architecture/cache-keys.md` (`users:email_verify:cooldown:{user_id}`)
- Test: `apps/api/tests/unit/test_email_verify_token.py`, `apps/api/tests/integration/test_users_email_verify.py`

**Interfaces:**

- Produces:
  - `email_verify.make_token(user_id: str, email: str, *, expires_at: datetime) -> str` and `read_token(token: str) -> VerifyClaim(frozen: user_id, email, expires_at)` (raises `ValidationError(code="email_token_invalid")` on a bad MAC/format, `code="email_token_expired"` past expiry) — HMAC-SHA256 with a purpose key derived from `app_enc_key`, base64url, constant-time compare.
  - `PATCH /me` with a changed email: as today resets `email_verified_at`, and now also `enqueue(kind="verify", user_id, address=<new email>, payload={"token": …})`.
  - `POST /api/v1/me/email/verification` (signed in, `Idempotency-Key` optional, `guard_ip(bucket="email-verify", subject=user.id)`): 409 `email_missing` without an email, 409 `email_already_verified`, 429 `email_verify_cooldown` within 60 s of the last send (Redis key with TTL); else enqueue a `verify` letter → `202 {sent: true}`.
  - `POST /api/v1/email/confirm` body `{token}` (anonymous, `guard_ip(bucket="email-verify")`): reads the token; 404-free: unknown user or the user's current email ≠ token email → 409 `email_token_stale`; sets `email_verified_at` (idempotent: already verified → 200) → `200 {email_verified: true}`. Keyless — the docstring says why (the token is single-purpose and the write is idempotent).
  - `MeOut` unchanged (`email_verified` already there) plus `email_verification_sent_at: datetime | None` (from the latest `verify` outbox row) so the UI can say «Письмо отправлено».

- [ ] **Step 1: Tests first** — token round-trip; `test_tampered_or_expired_token_is_refused`; `test_token_for_old_email_does_not_verify_new_one` (verify for a@, change to b@, confirm the a@ token → 409, b@ stays unverified); PATCH enqueues one `verify` letter whose confirm link carries a working token; resend cooldown → 429; resend for a verified email → 409; confirm twice → 200 twice, one stamp; the token and the address never appear in logs; the bucket answers 429 on the 11th per-account send in a minute.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/unit/test_email_verify_token.py tests/integration/test_users_email_verify.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/users): confirm an email by a signed link before order letters go to it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Storefront — live order page

**Files:**

- Create: `apps/web/src/lib/realtime.ts` (+ test), `apps/web/src/hooks/useOrderSocket.ts` (+ test)
- Modify: `apps/web/src/components/Providers.tsx` (mount the socket for a signed-in user), `apps/web/src/components/order/OrderView.tsx` (export its query key `orderKey(number)` from `lib/orders.ts` and use it), `apps/web/src/lib/order-poll.ts` (comment only — polling stays)
- Test: as listed

**Interfaces:**

- Consumes: Task 2 WS protocol (R2, R3); `session.getAccessToken()` / `session.refreshAccessToken()`; `API_BASE`.
- Produces:
  - `lib/realtime.ts`: `class OrderSocket { constructor(opts: OrderSocketOptions); start(): void; stop(): void }` with `OrderSocketOptions{url, getToken: () => Promise<string | null>, onChanged: (number: string) => void, onState?: (s: "connecting"|"open"|"closed") => void, WebSocketImpl?: typeof WebSocket}`; sends `{type:"auth", token}` on open; reconnect backoff `min(30_000, 500 × 2^attempt)` with jitter; on close 4401 refreshes the token once before reconnecting; closes itself after 60 s without any frame (zombie socket lesson); `wsUrl(API_BASE)` maps `http`→`ws`, `https`→`wss` + `/api/v1/realtime/orders`.
  - `useOrderSocket()` (in `Providers`, keyed on `user?.id`): on `order.changed` → invalidate `orderKey(number)`, `ORDERS_KEY`, `BALANCE_KEY`, `ENTRIES_KEY`; stops on sign-out.

- [ ] **Step 1: Tests first** (fake WebSocket): auth frame sent first; `order.changed` invalidates exactly those keys; reconnect after a drop with a fresh token; 4401 → one refresh then reconnect, a second 4401 → back off; silence 60 s → closes and reconnects; not started for an anonymous visitor; stopped on unmount/sign-out; polling still runs while the socket is open (OrderView test).
- [ ] **Step 2: Implement** (port `yupay:apps/web/src/hooks/useOrderSocket.ts` + `packages/api-client/src/realtime/OrderSocket.ts` ideas onto the first-message auth; no zustand — local state only).
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/web test && pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/orders): live order page — a WebSocket nudge re-reads the order

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Admin pricing API — rules, preview, per-item override

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/pricing_admin.py`
- Modify: `modules/skins/{admin_routes,admin_schemas,api}.py`, `docs/api/openapi.json` + client, `modules/skins/README.md`, `docs/architecture/cache-keys.md` (no new keys; note `skins:pricing` publish after commit)
- Test: `apps/api/tests/integration/test_admin_pricing.py`

**Interfaces:**

- Consumes: `skins.pricing.{PricingRules, quote, to_uzs, DEFAULT_RULES}`, `skins.settings.{load_rules, save_rules, publish_rules}`, `skins.repricing.{lock_pricing, reprice_rows}`, `skins.cachekeys.bump_catalog_version`, `fx.api.current_usd_uzs`, `admin.api.{record, required_key}`, M3/M4a replay helpers (`remember`/`replayed` pattern).
- Produces (all `require_admin`):
  - `GET /admin/skins/pricing` → `PricingOut{rules: PricingRules, updated_at, updated_by: {id, display_name} | null, items_active: int, items_overridden: int, rate_uzs: str | null}`.
  - `PUT /admin/skins/pricing` body `PricingRules` + required key → `PricingOut`; order: `lock_pricing` → `save_rules` → `reprice_rows(db, rules)` → audit `skins.pricing.save` `{items_repriced}` → replay → commit → `publish_rules(rules)` → `bump_catalog_version`. Invalid rules → 422 with the validator's message.
  - `POST /admin/skins/pricing/preview` body `PreviewIn{rules: PricingRules | None, slug: str | None, cost_usd: Decimal | None, category: str | None, weapon: str | None, count_auto: int | None, item_pp: Decimal | None, fixed_price_usd: Decimal | None}` (either `slug` or `cost_usd`+`category`) → `PreviewOut{price_usd, price_uzs, cost_usd, expenses_usd, bracket_margin_usd, category_pp, weapon_pp, liquidity_pp, item_pp, effective_percent, applied}` (strings); with `slug` the item's cost/taxonomy/overrides fill the blanks; draft `rules` previews an unsaved document; writes nothing.
  - `PUT /admin/skins/items/{slug}/pricing` body `{margin_override_pp: Decimal | None (−100..500, 2dp), fixed_price_usd: Decimal | None (0..100000, 2dp)}` + required key → `AdminSkinItemOut` (now carrying `cost_usd`, `sell_price_usd`, `margin_override_pp`, `fixed_price_usd`); order: `lock_pricing` → set columns → `reprice_rows(ids=[item.id])` → audit `skins.item.override` `{slug, margin_override_pp, fixed_price_usd}` → replay → commit → `bump_catalog_version`.
  - `GET /admin/skins/items` gains `overridden: bool` filter and the new fields.

- [ ] **Step 1: Tests first** — save reprices every active item and publishes the cache; `test_failed_save_keeps_old_rules_and_cache` (force `reprice_rows` to raise → 500/409, row 1 unchanged, Redis `skins:pricing` still the old document, catalogue version unchanged); `test_preview_writes_nothing` (no row, no cache, no audit change); preview with draft rules differs from the saved ones; preview by slug uses the item's overrides; override sets/clears (null) each field, reprices only that item, audit row written; replayed key → one audit row, same answer; another body with the same key → 409; a price sync running concurrently waits on the advisory lock (two sessions); customers → 403.
- [ ] **Step 2: Implement** (routes parse and dispatch; logic in `pricing_admin.py`).
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_admin_pricing.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/skins): admin pricing — edit the rules document, preview a price, override one item

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Admin SPA — Pricing page

**Files:**

- Create: `apps/admin/src/features/pricing/{api.ts, PricingPage.tsx, RulesForm.tsx, PreviewCard.tsx, OverrideCard.tsx, labels.ts}` (+ `PricingPage.test.tsx`, `RulesForm.test.tsx`, `OverrideCard.test.tsx`)
- Modify: `apps/admin/src/app/router.tsx` (`/pricing`), `app/Layout.tsx` (nav «Цены»)

**Interfaces:**

- Consumes: Task 7 routes; `useIdempotencyKey`, `errorText`, `lib/format.ts`.
- Produces: `/pricing` page:
  - Status line: «Активных скинов: N, с ручной ценой: M, курс: X сум за $1, правила обновил {кто} {когда}».
  - `RulesForm`: расходы %, мин. маржа $, нижняя цена $, округление сум, «Не дороже Steam» (checkbox); таблица брекетов («от $», «%», добавить/удалить строку); полосы ликвидности («от N лотов», «п.п.»); надбавки по категориям и оружию (ключ → п.п.). «Сохранить» — подтверждение «Сохранить и пересчитать цены всех скинов?»; one key per confirmed submission; 422 shows the validator's message in Russian («Проверьте числа: брекеты должны идти по возрастанию от $0.»). A dirty marker and «Сбросить».
  - `PreviewCard`: по скину (поиск по названию) или по себестоимости + категория; previews the **draft** rules from the form; shows цена $ и сум, себестоимость, расходы, маржа брекета, п.п. категории/оружия/ликвидности/скина, итоговый %, «как посчитано» (`applied` в словах: формула / ручная цена / мин. маржа / не дороже Steam / нижняя цена).
  - `OverrideCard`: поиск скинов (фильтр «только с ручной ценой»), для выбранного — «Наценка, п.п.» и «Фиксированная цена, $», «Будет продаваться за $X / Y сум» (через preview), «Сохранить», «Сбросить ручную цену» (sends nulls).

- [ ] **Step 1: Tests first** — save sends the whole document with a ≥ 16-char key after confirm; a double click sends once; 422 message in Russian, typed values kept; preview uses unsaved form values; override save/clear; nav link; no raw English API text.
- [ ] **Step 2: Implement** (port the shape of `yupay:apps/admin/src/features/skins/{PricingRulesCard,PricePreviewCard,ItemOverrideCard}.tsx`; csmarket has no b2b brackets).
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/pricing): pricing rules editor with a live preview and per-item prices

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Dashboard API and the cached Waxpeer balance

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/dashboard.py`, `apps/api/src/csmarket/modules/admin/{dashboard_routes,dashboard_schemas}.py`, `apps/api/migrations/versions/0016_orders_dashboard.py`
- Modify: `modules/orders/health.py` + `apps/scheduler/src/csmarket_scheduler/jobs/orders_health.py` (write `orders:waxpeer:balance` on each successful read), `modules/orders/api.py`, `api/v1/router.py`, `docs/api/openapi.json` + client, `docs/architecture/cache-keys.md`
- Test: `apps/api/tests/integration/test_admin_dashboard.py`, `apps/api/tests/integration/test_orders_health.py` (extend)

**Interfaces:**

- Produces:
  - Migration `0016`: indexes `ix_orders_paid_at (paid_at)`, `ix_orders_refunded_at (refunded_at)` (partial `WHERE … IS NOT NULL`).
  - `orders.dashboard.summary(db, redis, *, days: Literal[1, 7, 30], at: datetime) -> Dashboard` per R9: window = from the start of the Tashkent day `days − 1` days before `at`; `sales{count, revenue_uzs, revenue_usd, cost_usd, margin_usd, margin_percent}`, `refunds{count, amount_uzs}`, `in_flight: int`, `attention: int`, `by_day: [{day (YYYY-MM-DD Tashkent), sales_count, revenue_uzs, margin_usd}]` (every day in the window, zeros included), `waxpeer: {balance_usd: str | null, read_at: datetime | null}` from Redis.
  - `GET /admin/dashboard?days=1|7|30` (`require_admin`) → `DashboardOut` (strings for money); anything else → 422.
  - Redis `orders:waxpeer:balance` JSON `{usd, read_at}`, TTL 3600 s, written only by the health job.

- [ ] **Step 1: Tests first** — a sale paid at 23:30 Tashkent counts on that Tashkent day, not the UTC one; refunded orders leave sales and appear in refunds (by `refunded_at`); margin uses `bought_units` when present, else `cost_usd`; `days=1` is "today since 00:00 Tashkent"; days without sales are present with zeros; no balance cached → `null`s; the health job writes the cache on a good read and leaves it on a failed one; query count is constant (no per-day queries); customers → 403.
- [ ] **Step 2: Implement** (one aggregate query per block, `AT TIME ZONE 'Asia/Tashkent'`; check the API image has tzdata, else use the fixed UTC+5 offset in SQL `+ interval '5 hours'` and say which).
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_admin_dashboard.py tests/integration/test_orders_health.py tests/integration/test_migrations.py -q
uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && uv run pytest -n auto -q
cd ../scheduler && uv run pytest -q && cd ../.. && make gen-api && make lint typecheck
git add -A && git commit -m "feat(api/admin): dashboard — sales, margin, refunds by Tashkent day, the cached Waxpeer balance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Storefront — confirm the email

**Files:**

- Create: `apps/web/src/app/[locale]/account/email/confirm/page.tsx` (+ client `ConfirmEmail.tsx` + test)
- Modify: `apps/web/src/components/account/EmailForm.tsx` (+ test), `apps/web/src/lib/auth.tsx` (`Me.email_verification_sent_at`), `packages/i18n/locales/{ru,uz,en}/web.json` (`web.account.email.*`)
- Test: as listed

**Interfaces:**

- Consumes: Task 5 routes.
- Produces:
  - `EmailForm` states: no email → the form (hint «Для писем о заказах.»); unverified → «Почта не подтверждена. Мы отправили письмо на {email}.» + «Отправить ещё раз» (disabled 60 s after a send; 429 → «Отправить ещё раз можно через минуту.»); verified → «Подтверждена» badge. Saving a new email shows «Мы отправили письмо со ссылкой — откройте его.»
  - `/account/email/confirm?token=…` (Server shell `noindex`, no `loading.tsx`) → client posts the token once: success «Почта подтверждена. Теперь письма о заказах будут приходить на неё.» + link «В профиль»; `email_token_expired` «Ссылка устарела. Отправьте письмо ещё раз в профиле.»; `email_token_stale`/`email_token_invalid` «Ссылка не подходит. Отправьте письмо ещё раз в профиле.»; works signed out.
  - All copy ru verbatim above; uz/en equivalents; parity test.

- [ ] **Step 1: Tests first** — each EmailForm state; resend cooldown; confirm page each outcome; the token is not echoed in the page or logs; signed-out confirm works.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/account): confirm the email by link, resend from the profile

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Nightly trade-link erase

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/erase.py`, `apps/scheduler/src/csmarket_scheduler/jobs/orders_erase.py`, `apps/api/migrations/versions/0017_orders_trade_link_erased.py`
- Modify: `modules/orders/models.py` (`trade_link_erased_at`), `modules/orders/api.py`, `modules/admin/orders_service.py` (show the stored masked link for erased orders), scheduler `main.py` + `tests/test_main.py`, `docs/security/pii-handling.md` (the purge has landed), `docs/decisions/0007-orders-buying-trades.md` (pointer), `modules/orders/README.md`
- Test: `apps/api/tests/integration/test_orders_erase.py`, `apps/scheduler/tests/test_orders_erase.py`

**Interfaces:**

- Produces:
  - Migration `0017`: `orders.trade_link_erased_at timestamptz NULL`.
  - `erase.erase_old_trade_links(db, *, at: datetime, older_than: timedelta = timedelta(days=30), batch: int = 500) -> int` (R11): selects terminal orders past the cutoff with `trade_link_erased_at IS NULL` (`FOR UPDATE SKIP LOCKED`), rewrites `trade_link` to the masked URL keeping `partner`, stamps `trade_link_erased_at`; a link that does not parse is replaced by `"erased"`; returns the count; loops batches until fewer than `batch`.
  - The same job also nulls `email_outbox.address` on `verify` rows older than 7 days (`erase.erase_old_verify_addresses(db, *, at) -> int`): the confirmation address is the one email the outbox snapshots, and it is not needed once the link has expired.
  - Job `orders.erase_trade_links`: cron 22:00 UTC, coalesced, runs both erasers, `run()` never raises.

- [ ] **Step 1: Tests first** — a delivered order 31 days old is erased, 29 days old is not; a `verify` outbox row 8 days old loses its address, a 6-day-old one keeps it; pending/in-flight orders never; erased orders keep `partner`; running twice changes nothing; the admin detail shows the masked link and never the token; the old token string appears nowhere in the row afterwards; job registration and `test_main.py` list.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
cd apps/api && uv run pytest tests/integration/test_orders_erase.py tests/integration/test_migrations.py -q
uv run pytest -n auto -q && cd ../scheduler && uv run pytest -q && cd ../.. && make lint typecheck
git add -A && git commit -m "feat(scheduler): erase the order's trade-link token 30 days after the order ends

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Admin SPA — Dashboard

**Files:**

- Create: `apps/admin/src/features/dashboard/{api.ts, DashboardPage.tsx, labels.ts}` (+ `DashboardPage.test.tsx`)
- Modify: `apps/admin/src/app/router.tsx` (`/` → the new page), delete `apps/admin/src/routes/Dashboard.tsx`

**Interfaces:**

- Consumes: Task 9 route.
- Produces: tabs «Сегодня» / «7 дней» / «30 дней» (URL `?days=`, guarded by `pick`); tiles «Продажи» (кол-во), «Выручка» (сум и $), «Маржа» ($ и %), «Возвраты» (кол-во, сум), «В пути», «Требуют внимания» (link to `/trades?view=attention`), «Баланс Waxpeer» ($, «обновлено N мин назад» or «неизвестно», warn tone below the alert threshold if the API sends it); table by day (дата, продажи, выручка, маржа); refetch every 60 s.

- [ ] **Step 1: Tests first** — each tab requests the right `days`; tiles render the strings; unknown balance; attention link; empty days shown.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Gate, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
npx prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/dashboard): sales, margin, refunds and the Waxpeer balance at a glance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: e2e and the coverage gate for the new modules

**Files:**

- Create: `e2e/tests/live.spec.ts`, `e2e/tests/email.spec.ts`, `e2e/tests/admin-pricing.spec.ts`
- Modify: `e2e/tests/helpers.ts` (`devEmails(request, token, kind)`), `e2e/playwright.config.ts` (anchored `testMatch`), `e2e/README.md`, `scripts/check-module-coverage.py` (+ `notifications`, `realtime` at 95 %)

- [ ] **Step 1: Specs:**
  1. **Live page:** buy from the balance (fake Waxpeer) with the order page open; after `devTrade(accept)` the page shows «Получено» within 5 s (the nudge — polling would take up to 8 s+; assert with a 5 s timeout and that no extra page reload happened).
  2. **Email:** sign in, set an email on the account page → «Мы отправили письмо…»; read the `verify` letter through the dev route, open its link → «Почта подтверждена»; buy from the balance → a `receipt` letter for that order exists in the dev outbox.
  3. **Admin pricing:** open «Цены», change the 0 $ bracket %, the preview for a seeded skin changes before saving; save after confirm; the storefront item page shows the new price after reload.
- [ ] **Step 2: Run against the dev stack** — `docker compose up -d --build`, `make migrate`, `make seed-skins`, `make test-e2e` twice (all specs), `docker compose down` (no `-v`). A real app bug is reported, not hidden in a spec.
- [ ] **Step 3: Commit**

```bash
npx prettier --check . && pnpm --filter @csmarket/e2e lint && pnpm --filter @csmarket/e2e typecheck
git add -A && git commit -m "test(e2e): live order page, email confirmation and receipt, admin pricing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Docs, ADR-0008, runbooks; full verification

**Files:**

- Create/finish: `docs/decisions/0008-realtime-and-email.md`, `docs/runbooks/{email,pricing}.md`, `docs/architecture/sequence-diagrams/{order-live,email-outbox}.mmd`, `docs/product/flows/email-confirm.md`
- Modify: module READMEs (`realtime`, `notifications`, `orders`, `skins`, `users`, `admin`), `docs/architecture/{module-map,metrics,cache-keys,overview}.md`, `docs/api/README.md` (WS protocol, email confirm, admin pricing/dashboard), `docs/security/pii-handling.md` (email outbox rows hold no address except `verify` rows, whose address the nightly erase job nulls after 7 days; Resend as a processor receives the address, subject and body), `docs/runbooks/first-deploy.md` (Resend key, DNS SPF/DKIM for the sending domain — owner action), `AGENTS.md` (§0 M4b row + status; §2 Email row; §11 nothing new), `.env.example`, `infra/secrets-example/api.env`

- [ ] **Step 1: Write the docs** — ADR-0008: context (ADR-0007 R15, owner D1–D5), decision R1–R13 + execution refinements from the ledger, consequences (nudges delivered on commit; one LISTEN connection per API process; letters only to verified addresses; a lost letter never blocks money), alternatives (Redis pub/sub per socket; token in the URL; inline after-commit email sends like YuPay; an email SDK), dependencies added: none. `runbooks/email.md`: Resend key and domain, `#failing` (what failed means, how to see the outbox, re-queue a row), a buyer says «письмо не пришло» (verified? spam? outbox status), changing the sender. `runbooks/pricing.md`: how a rules save reprices, preview first, overrides, rollback by saving the previous document from the audit log.
- [ ] **Step 2: Full gate**

```bash
git status --porcelain
make lint typecheck test
cd apps/api && uv run python -m csmarket.scripts.export_openapi /tmp/o.json && cd ../.. && diff -q /tmp/o.json docs/api/openapi.json
docker run --rm -v "$PWD/infra/prometheus:/p" --entrypoint promtool prom/prometheus check rules /p/alerts/notifications.yml
docker compose build && docker compose up -d && docker compose exec api alembic upgrade head && make seed-skins
make test-e2e && docker compose down
git status --porcelain
```

Expected: all green; the coverage gate passes for `orders`, `payments`, `wallet`, `skins`, `notifications`, `realtime` (≥ 95 % each); no OpenAPI drift.

- [ ] **Step 3: Commit**

```bash
npx prettier --check .
git add -A && git commit -m "docs: ADR-0008 realtime and email; email and pricing runbooks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

**Spec coverage (ADR-0007 R15 = the M4b scope; spec §3.2 `realtime`, `notifications`; §7.6/§7.8 WS events + email; §9 pricing editor + preview + per-item overrides; §10 order page WS-driven, admin Dashboard and Pricing):** realtime → T2, T6; email outbox + Resend → T3; receipt / trade sent / refunded letters → T4; email verification (owner D1) → T5, T10; pricing editor + preview + overrides → T7, T8; dashboard (owner D2) → T9, T12; trade-link erase (owner D3) → T11; carry-overs Z/Z2 → T1; e2e → T13; docs → T14. Deferred by R13: `my-history` probe (M5).

**Placeholder scan:** no TBD/TODO; each new rule (nudge sites, outbox lifecycle, retries, token format, dashboard definitions, erase rule) is spelled out; ports name their YuPay sources.

**Type consistency:** `nudge(db, *, user_id, number)` (T2) used at the R4 sites; `enqueue(db, *, kind, user_id, order_id, address, payload)` (T3) used by T4/T5; `EMAILS_CHANNEL` (T3) = the worker queue; `render(kind, *, locale, number, payload, links)` (T4) used by `drain_emails` (T3 stub replaced in T4); `make_token`/`read_token` (T5) = the confirm route; `PricingOut`/`PreviewOut` (T7) = the SPA (T8); `Dashboard`/`DashboardOut` (T9) = the SPA (T12); migrations 0015 → 0016 → 0017; scheduler: `orders.erase_trade_links` cron 22:00 UTC (T11), the health job gains the Redis write (T9) — no new interval job, so 320/340 stay free.

**Review Focus → tests:** 1 → T2 `test_nudge_is_delivered_only_after_commit`; 2 → T2 `test_socket_receives_only_its_users_orders`, `test_bad_token_closes_4401`, `test_socket_closes_at_token_expiry`; 3 → T4 `test_replayed_paid_enqueues_one_receipt`, T3 `test_send_skips_unverified_address`, `test_retry_reuses_idempotency_key`; 4 → T7 `test_failed_save_keeps_old_rules_and_cache`, `test_preview_writes_nothing`; 5 → T5 `test_token_for_old_email_does_not_verify_new_one`, `test_tampered_or_expired_token_is_refused`.
