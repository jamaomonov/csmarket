# Public API: webhooks, admin keys, supplier-checked refunds, metrics (plan C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Partners get signed webhooks for their API orders; an admin manages API keys and their
tariff and sees revenue per key; an admin can refund a stuck Skinslink / LIS-SKINS order (site or
API) after the supplier confirms the purchase did not happen; the public API is measured.

**Architecture:** Webhooks follow the email outbox exactly: a `api_webhook_deliveries` row and
`NOTIFY api_webhooks` are written in the same transaction as the order's move, the worker drains
them with `FOR UPDATE SKIP LOCKED`, a guarded update and a backoff schedule, and no DB
connection is held across the HTTP send. Payloads are built at enqueue time from
`orders.public_view.public_order`. The signature key is the stored `api_keys.token_hash` (the hex
SHA-256 of the token — the partner derives it from the token). The supplier-checked refund
mirrors the Waxpeer admin refund: unlocked read → commit → one supplier lookup (4 s, no lock) →
lock → re-check → `refund_to_balance`.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, httpx, Postgres LISTEN/NOTIFY worker,
prometheus_client; Vite + React admin.

**Spec:** `docs/superpowers/specs/2026-10-09-public-api-design.md` (§2.6, §8, §9, §10, §12 C).
Plans A and B are built on branch `public-api`. AGENTS.md is binding.

## Global Constraints

- Webhook events: `order.paid`, `order.trade_sent`, `order.delivered`, `order.refunded`; one
  delivery per `(order, event)`; payload = the public order (`PublicOrderOut`) plus `event`,
  `event_id`, `created_at`. Never a supplier name or id, never a trade link.
- Headers `X-Csm-Event`, `X-Csm-Timestamp` (unix seconds), `X-Csm-Signature =
hex(HMAC-SHA256(key, f"{timestamp}.{body}"))` where `key` = the UTF-8 bytes of the lowercase
  hex SHA-256 of the partner's token (= `api_keys.token_hash` of the user's live key at send time).
- Retries: 1 m, 5 m, 30 m, 2 h, then every 2 h, 10 attempts in all, then `failed`. 2xx = sent;
  timeout 5 s; redirects not followed.
- Webhook URL: `https` only, no userinfo, no fragment, ≤ 500 chars; every resolved address must be
  public (no private, loopback, link-local, multicast, reserved, unspecified, CGNAT 100.64/10,
  `169.254.169.254`) — checked when saved and before every send. Never log the URL (host only).
- Admin refund of a Skinslink / LIS-SKINS order: one supplier status call, 4 s timeout, no lock
  and no open transaction across it; refuse unless the supplier confirms the purchase failed /
  was cancelled / was returned, or never existed **and** no buy is running and the purchase row is
  older than 10 minutes. A failed lookup refuses (`supplier_unavailable`). A new external call on
  an admin route → ADR + an AGENTS.md §11 line + the route in the latency alert regex.
- Tariff changes are admin-only, audited (`api_keys.tariff`), and apply to the user's live key
  (and carry over on reissue, which plan B already does).
- Metrics: `csmarket_public_api_requests_total{route,status}` (route = route template,
  status = HTTP class `2xx|3xx|4xx|5xx`), `csmarket_public_api_orders_total{profile,outcome}`,
  `csmarket_api_webhooks_total{event,outcome}`; never a key id or user as a label.
- mypy --strict, ruff, eslint `--max-warnings 0`; prettier from the repo root only; coverage
  `public_api`, `orders`, `wallet` ≥ 95 %.
- Tests: run only the files you touch; full suites on CI. Commit per task; never push.

## Review Focus

1. A webhook must never be sent to a private address, including when DNS changes between save
   and send (re-check at send; a host resolving to any private address is refused) — Task 3.
2. A refund of a Skinslink / LIS-SKINS order whose purchase the supplier reports as active /
   hold / completed / accepted must be refused, even if the admin clicks twice — Task 5.
3. A replayed webhook body with a changed field must fail verification (the signature covers the
   timestamp and the exact body bytes sent) — Task 3.
4. An order event fired twice (a reconcile re-applying the same report) must create one delivery,
   not two — Task 2.
5. Changing a key's tariff must not change the price of orders already placed — Task 4.

---

### Task 1: Webhook storage, URL guard, `PUT/GET/DELETE /public/webhook`

**Files:**

- Create: `apps/api/migrations/versions/0029_api_webhooks.py`
- Create: `apps/api/src/csmarket/modules/public_api/webhook_url.py`, `webhooks.py`
- Modify: `apps/api/src/csmarket/modules/public_api/models.py`, `routes.py`, `schemas.py`,
  `apps/api/src/csmarket/core/config.py` (+ `.env.example`)
- Test: `apps/api/tests/unit/test_webhook_url.py`, `apps/api/tests/integration/test_public_api_webhook_routes.py`

**Interfaces:**

- Produces:
  - Models: `ApiWebhook` (`api_webhooks`: `user_id` PK FK users CASCADE, `url` Text,
    `created_at`, `updated_at`); `ApiWebhookDelivery` (`api_webhook_deliveries`: `id` uuid,
    `user_id` FK, `order_id` FK orders RESTRICT, `event` String(24) CHECK in the four events,
    `payload` JSONB, `status` String(8) CHECK in `pending|sent|failed`, `attempts` SmallInt 0,
    `next_attempt_at`, `sent_at`, `last_status_code` SmallInt null, `last_error` String(32) null,
    `created_at`, `updated_at`; unique `(order_id, event)`; index `(status, next_attempt_at)`
    WHERE status='pending').
  - `webhook_url.check_url(url: str) -> str` (normalised; raises
    `ValidationError(code="webhook_url_invalid")` for scheme/userinfo/fragment/length);
    `async def public_addresses(host: str, port: int) -> list[str]` (resolve with
    `asyncio.get_running_loop().getaddrinfo`; raises `ValidationError(code="webhook_url_private")`
    if any address is not public or nothing resolves; `ipaddress` checks: `is_private`,
    `is_loopback`, `is_link_local`, `is_multicast`, `is_reserved`, `is_unspecified`, and
    `ip in ip_network("100.64.0.0/10")`; IPv4-mapped IPv6 unwrapped first).
  - Routes (key auth, `limits.enforce(caller, "read")`): `GET /public/webhook` →
    `{url, created_at, last_delivery: {event, status, attempts, last_status_code, at} | null} | null`;
    `PUT /public/webhook {url}` (Idempotency-Key) → 200 same shape; `DELETE /public/webhook`
    (Idempotency-Key) → 204. Exempt from the coarse limiter like the other public handlers.
  - Settings: `webhook_timeout_seconds: float = 5.0`, `webhook_max_attempts: int = 10`.

- [ ] **Step 1: Failing tests.** Unit: `check_url` accepts `https://hooks.example.com/csm`,
      refuses `http://…`, `https://u:p@…`, `https://…#x`, a 600-char URL; `public_addresses` with a
      monkeypatched `getaddrinfo` refuses `10.0.0.1`, `127.0.0.1`, `169.254.169.254`, `::1`,
      `::ffff:10.0.0.1`, `100.64.1.1`, a mix of one public and one private address, and accepts
      `93.184.216.34`. Integration: PUT stores and GET returns it; a private host → 422
      `webhook_url_private`; DELETE → 204 then GET null; another user's webhook is never visible.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** (migration 0029 revises `0028_public_api_orders`; import the models
      where `public_api.models` is imported; `make gen-api`).
- [ ] **Step 4: Run** the two files + `tests/integration/test_migrations.py`; ruff; mypy. PASS.
- [ ] **Step 5: Commit** — `feat(api/public_api): webhook URL with a public-address guard`

---

### Task 2: Enqueue order events in the same transaction as the move

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/webhook_events.py`
- Modify: `orders/paid.py` (`mark_paid`), `orders/refunds.py` (`refund_to_balance`),
  `orders/skinslink_status.py` (`apply_report`), `orders/lisskins_status.py` (`apply_report`),
  `orders/trades.py` (the trade_sent / delivered moves)
- Test: `apps/api/tests/integration/test_api_webhook_events.py`

**Interfaces:**

- Consumes: `ApiWebhook`, `ApiWebhookDelivery`; `orders.public_view.public_order(order, trade,
purchase) -> PublicOrderOut`, `public_status(order, trade, purchase)`.
- Produces: `WEBHOOKS_CHANNEL = "api_webhooks"`; `async def emit_order_event(db, *, order, trade,
purchase) -> None` — no-op unless `order.channel == "api"` and the user has a webhook; maps the
  current public status to an event (`buying` right after `mark_paid` → `order.paid`;
  `trade_sent` → `order.trade_sent`; `delivered` → `order.delivered`; `refunded` →
  `order.refunded`); inserts `ApiWebhookDelivery(payload = {"event", "event_id" (= the delivery
id), "created_at", "order": public_order(...).model_dump(mode="json")})` with
  `ON CONFLICT (order_id, event) DO NOTHING`; on insert `pg_notify(WEBHOOKS_CHANNEL, id)`.
  Call it at each site listed under Files, after the move and before the caller's flush/commit,
  with the rows the site already holds (load the purchase/trade only if the site lacks it).

- [ ] **Step 1: Failing tests:** an API order through `create_api_order` with a webhook set →
      one `order.paid` delivery whose payload has no `source`, `sl:`, `ls:` or trade link; a Skinslink
      report moving it to trade_sent → `order.trade_sent`; the same report applied twice → still one
      (Review Focus 4); a hold with acceptance → `order.delivered`; `refund_to_balance` →
      `order.refunded` with `refund.amount_usd`; a site order → no delivery; an API order of a user
      without a webhook → none.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file + `test_public_api_buy.py`, `test_public_api_refunds.py`,
      `test_orders_skinslink*.py`, `test_orders_lisskins*.py`, `test_orders_trades*.py`. PASS.
- [ ] **Step 5: Commit** — `feat(api/orders): API order events into the webhook outbox`

---

### Task 3: Deliver webhooks (worker queue), signature, retries

**Files:**

- Create: `apps/api/src/csmarket/modules/public_api/webhook_sender.py`
- Modify: `apps/worker/src/csmarket_worker/consumer.py` (a `Queue("api_webhooks", …)`),
  `apps/api/src/csmarket/core/metrics.py` (`csmarket_api_webhooks_total{event,outcome}`)
- Test: `apps/api/tests/integration/test_api_webhook_sender.py`, `apps/api/tests/unit/test_webhook_signature.py`

**Interfaces:**

- Produces:
  - `sign(key_hex: str, timestamp: int, body: bytes) -> str` = hex HMAC-SHA256 over
    `f"{timestamp}.".encode() + body` with key `key_hex.encode()`.
  - `BACKOFF_SECONDS = (60, 300, 1800, 7200)` then 7200; `MAX_ATTEMPTS` from settings (10).
  - `async def drain_webhooks(db, *, limit=20, transport: httpx.AsyncBaseTransport | None = None,
settings=None, resolve=public_addresses) -> int` — claim like `notifications.sender._claim`
    (pending, due, `FOR UPDATE SKIP LOCKED`, bump `attempts`, book `next_attempt_at`, mark
    exhausted `failed`, commit); then per row with no transaction open: load the user's webhook
    URL and live key hash (no key → `failed`, `last_error="no_key"`; no webhook → `failed`,
    `"no_webhook"`); resolve and check the host (`webhook_url_private` → retry later,
    `last_error="private"`); POST the exact body bytes (compact JSON, sorted keys) with the three
    headers, `timeout = settings.webhook_timeout_seconds`, `follow_redirects=False`; connect to
    the checked IP with the original `Host` header and `extensions={"sni_hostname": host}` so a DNS
    change after the check cannot redirect the connection (verify TLS still checks the hostname;
    if httpx cannot do this, record a Ruling and fall back to the re-check only); 2xx → `sent`;
    else keep pending with `last_status_code` / `last_error` (`timeout`, `connect`, `http_<code>`);
    the update is guarded by `attempts` (as `sender._finish`); `record_webhook(event, outcome)`.
  - Worker: `Queue(name="api_webhooks", channel=WEBHOOKS_CHANNEL, drain=_drain_webhooks,
concurrency=1)`.

- [ ] **Step 1: Failing tests** (httpx `MockTransport`): a pending delivery is POSTed once with the
      three headers; the signature verifies with `sign(token_hash, ts, body)` and fails if one body
      byte changes (Review Focus 3); 500 → still pending, attempts 1, next in 60 s; after 10 failures →
      `failed`; a host now resolving to `10.0.0.1` → not sent (Review Focus 1); no live key → `failed
no_key`; a revoked-then-reissued key → signed with the new key's hash; the URL never appears in
      captured logs.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the two files + the worker tests (`cd apps/worker && uv run pytest -p
no:randomly`). PASS.
- [ ] **Step 5: Commit** — `feat(api/public_api): signed webhook delivery with retries`

---

### Task 4: Admin — API keys page, tariff, revenue

**Files:**

- Create: `apps/api/src/csmarket/modules/admin/api_keys_routes.py`, `api_keys_service.py`,
  `api_keys_schemas.py`; `apps/admin/src/features/apiKeys/{ApiKeysPage.tsx, ApiKeyCard.tsx,
api.ts, labels.ts}` (+ tests)
- Modify: `apps/api/src/csmarket/modules/public_api/keys.py` (`set_pricing_profile`),
  `api/v1/router.py`, `apps/admin/src/app/router.tsx`, `apps/admin/src/app/Layout.tsx` (nav)
- Test: `apps/api/tests/integration/test_admin_api_keys.py`

**Interfaces:**

- Produces:
  - `keys.set_pricing_profile(db, *, key: ApiKey, profile: Literal["retail","cost"]) -> None`.
  - `GET /admin/api-keys?q=&cursor=&limit=` → `{items: [{id, user {id, display_name},
pricing_profile, created_at, last_used_at, revoked_at, orders, revenue_usd, cost_usd}],
next_cursor}` (live keys first, newest first; `revenue_usd` = sum of `price_usd` of the key's
    `api` orders not refunded; `cost_usd` = sum of `cost_usd`); `GET /admin/api-keys/{id}` → the
    row + the latest 20 orders (`AdminOrderRow`) + webhook `{host, last_delivery}` (host only);
    `PUT /admin/api-keys/{id}/tariff {pricing_profile, reason}` (key, audited `api_keys.tariff`,
    409 on a revoked key); `POST /admin/api-keys/{id}/revoke {reason}` (audited `api_keys.revoke`).
  - Admin SPA: nav item «API-ключи» (group «Продажи» or the nearest), list + card with the tariff
    switch (confirm with reason) and revoke; orders link to `/orders/{number}`.

- [ ] **Step 1: Failing tests:** list shows a key with its order count and sums; tariff change is
      audited and the next order uses `cost`, an order placed before keeps its `retail` price
      (Review Focus 5); a non-admin → 403; revoke → the key's next public request → 401. SPA tests for
      the list and the tariff dialog.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** (follow `admin/users_*` exactly: `require_admin`, `required_key`,
      `replayed` / `remember` / `_finish`, keyset cursor; `make gen-api`).
- [ ] **Step 4: Run** the API file, `cd apps/admin && npx vitest run src/features/apiKeys`, eslint,
      tsc. PASS.
- [ ] **Step 5: Commit** — `feat(admin/api-keys): API keys page, tariff and revenue`

---

### Task 5: Admin refund of a Skinslink / LIS-SKINS order, checked with the supplier

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/admin_refund_sources.py`
- Modify: `orders/admin_actions.py` (dispatch by `order.source`; `can_refund` for purchase
  rows), `admin/orders_routes.py` (inject the supplier clients), `infra/prometheus/alerts/api.yml`
  (route already in the handler regex? check), `apps/admin/src/features/orders/*` (button shows
  when `can_refund`, error labels for the new codes)
- Test: `apps/api/tests/integration/test_admin_refund_sources.py`

**Interfaces:**

- Consumes: `purchase_rows.purchase_of(db, order, lock=)`; Skinslink client
  `purchase_status(*, merchant_tx_id) -> Purchase | None` (statuses `active`, `hold`,
  `completed`, `failed`, `canceled`, `reverted`; errors `SkinslinkError`,
  `SkinslinkUnavailableError`); LIS-SKINS client `info(*, custom_ids) -> list[Purchase]` (skin
  statuses `processing`, `wait_accept`, `accepted`, `return`, `wait_unlock`, `wait_withdraw`;
  errors `LisskinsError`, `LisskinsUnavailableError`); `refund_to_balance(..., reason="admin")`.
- Produces:
  - `purchase_refund_refusal(order, purchase, at) -> str | None` — `already_refunded`;
    `order_not_refundable` unless `order.status in ("buying", "trade_sent")`; `order_busy` while
    `purchase.buy_pending` and the buy lease is live; `order_in_flight` for a purchase younger
    than 10 minutes with no supplier id.
  - `async def admin_refund_purchase(db, *, number, admin_id, skinslink, lisskins) -> Order`:
    unlocked read + refusal + commit → one lookup with `asyncio.timeout(4)`:
    Skinslink: `failed` / `canceled` / not found → refundable; anything else →
    `order_in_flight`. LIS-SKINS: skin `return` / not found → refundable; anything else →
    `order_in_flight`. Errors / timeout → 409 `supplier_unavailable`. Then lock order + purchase,
    re-check, `refund_to_balance(to_status="failed", reason="admin", actor=f"admin:{admin_id}")`,
    clear `buy_pending`, return (the route audits and commits as today).
  - `admin_actions.admin_refund` dispatches by `order.source`; `CONFLICTS` gains
    `supplier_unavailable`; the detail's `can_refund` covers purchase rows (no supplier call).

- [ ] **Step 1: Failing tests** (fake clients): Skinslink `failed` → refunded (USD for an API
      order, soʻm for a site order), `hold` / `completed` / `active` → 409 `order_in_flight` and
      nothing booked (Review Focus 2); a second click after a refund → `already_refunded`; LIS-SKINS
      `return` → refunded, `accepted` → refused; timeout → `supplier_unavailable`; not found but the
      purchase is 2 minutes old → `order_in_flight`; not found and 11 minutes old → refunded; the
      supplier call happens with no transaction open (assert via a fake that checks
      `db.in_transaction()` is False).
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement**; ADR (new file `docs/decisions/0018-admin-refund-skinslink-lisskins.md`)
      and an AGENTS.md §11 line (the sixth/seventh carve-out wording style); make sure
      `POST /admin/orders/{number}/refund` is in the `ApiWaxpeerLatency` / `ApiHighLatency` handler
      regexes.
- [ ] **Step 4: Run** the file + `test_admin_orders.py` + admin vitest for orders. PASS.
- [ ] **Step 5: Commit** — `feat(api/orders): admin refund of Skinslink and LIS-SKINS orders, checked with the supplier`

---

### Task 6: Public API metrics

**Files:**

- Modify: `apps/api/src/csmarket/core/metrics.py`, `public_api/routes.py` (a dependency or
  middleware scoped to the public router), `orders/api_checkout.py` (outcome),
  `docs/architecture/metrics.md`
- Test: `apps/api/tests/unit/test_public_api_metrics.py`, one integration assertion

**Interfaces:**

- Produces: `record_public_request(route: str, status: int)` (route = the matched route template
  from `request.scope["route"].path`, unknown → "other"; status → `2xx|3xx|4xx|5xx`);
  `record_public_order(profile, outcome)` with `outcome` in `created|duplicate|insufficient|
offer_gone|price_above_max|rejected` (everything else `rejected`); both precreated.

- [ ] **Step 1–5** (TDD as above). Commit — `feat(api/public_api): request and order metrics`

---

### Task 7: Docs

**Files:** `docs/api/public-v1.md` (Webhooks: events, payload example, headers, retries, how to
verify in Python and Node with a fake token, idempotency by `event_id`), `docs/api/README.md`
(admin api-keys routes, admin refund codes), `docs/runbooks/public-api.md` (a stuck webhook —
read `api_webhook_deliveries`; change a tariff in the admin instead of SQL; the supplier-checked
refund), `docs/architecture/module-map.md`, `docs/security/pii-handling.md` (webhook URLs:
stored, never logged; host only in logs/admin), ADR-0017 (plan C consequences), AGENTS.md §0 (plan
C built) and §11, `docs/tech-debt.md` (remove the SQL-tariff note).

- [ ] **Step 1:** write; **Step 2:** prettier from the repo root; commit `docs: webhooks, admin
keys, supplier-checked refunds`.

---

## Self-review notes

- Spec §8 (T1–T3), §9 admin keys (T4), §10 metrics + docs (T6, T7); the owner's 2026-10-09
  answer (supplier-checked refund, option 1) → T5. Spec §9's "admin: orders filter channel=api"
  is covered by the API keys card's order list; a filter on the admin orders page is left out
  (YAGNI) — note it in the runbook if needed.
