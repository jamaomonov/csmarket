# csmarket.uz — CS2 skins marketplace, design

Status: **approved by the owner in conversation (2026-10-01)**; awaiting the owner's review of
this written spec, then `writing-plans` for milestone M0.

Owner: jamaomonov. Working language with the owner: Russian, terse. Code, docs and commit
messages: English.

---

## 1. Purpose and scope

**csmarket.uz** is a standalone CS2-skins shop for Uzbekistan: browse a catalogue of ~35k
items, pay in soʻm (Click / Payme / Uzum, or an internal balance), receive the skin as a Steam
trade offer sourced from **Waxpeer**. It is a separate brand, repository, database, VPS,
Waxpeer account and set of acquirer contracts — it shares **nothing at runtime** with YuPay
(`~/Projects/yupay`), although most of its code is ported from there.

**MVP = the buy side.** Selling skins to us (via the **skinslink** aggregator) is the next
stage; the MVP only leaves room for it (a `sell` module beside `skins`, a `sell_payout` ledger
kind).

Out of MVP: selling, Telegram bot / Mini App, crypto, promo codes / cashback / referrals,
reviews, blog, balance withdrawal, Paynet (optional later).

Main competitor: **skinsavdo.uz** (supplier skinsback, open API, tiered markup 15 %→6 %; see
YuPay memory `skinsavdo-competitor.md`). Aim is parity with a fair margin, not a price war.

## 2. Decisions taken by the owner (2026-10-01)

1. **Independent project**: own repo, backend, admin, storefront; nothing shared with YuPay.
2. **Own acquirer kassas** (Click, Payme, Uzum) opened for csmarket; the owner is the merchant.
3. **Internal balance is mandatory** — it is where refunds land when a trade fails.
4. **Steam-only sign-in.** No email/password, no Google, no Telegram.
5. **Web only** for MVP. No Mini App, no bot.
6. **Locales ru / uz / en; prices in soʻm** (USD may be shown beside).
7. **Own VPS** (not YuPay's), same infra template.
8. **Build path: new repo, port modules one by one** (not a fork of YuPay, not greenfield).
9. **Nothing YuPay-specific may leak in** — see §4.
10. **Admin sign-in = the same Steam sign-in + `admin` role** on named `steam_id`s. No passwords.
11. **Short order numbers**, not UUIDs, everywhere a human or an acquirer sees an id (§6).

Decisions inherited from YuPay's skins work (ADR-0093, spec
`yupay/docs/superpowers/specs/2026-09-28-cs2-skins-design.md`) and still in force:

- Deliver straight to the customer's trade link; no Steam bot of our own.
- Our catalogue is ours (ByMykel/CSGO-API); Waxpeer supplies only listings; nothing
  Waxpeer-branded reaches a browser; seller name + inspect link may be shown.
  **Changed 2026-10-06:** Skinslink is a second buy source beside Waxpeer — spec
  `2026-10-06-skinslink-buy-source-design.md`, ADR-0010.
- Buy only `auto` listings.
- Skin names stay English; taxonomy (category, weapon, wear, StatTrak/Souvenir) is localised.
- The Waxpeer purchase happens **at payment** (no "I am ready" gate); the offer waits for the
  buyer in Steam.
- Markup is admin-configurable (pricing document with brackets, liquidity bands, min margin,
  price floor). YuPay's tuned `DEFAULT_RULES` (min margin $0.03, floor $0.10, 100–1000
  bracket 3 %, 1000+ 2 %) is the seed.
- Default sort `-price`; «Мгновенная доставка» copy is acceptable.
- Copy rules: no service meta («цены обновляются каждые 5 минут»), no "water", concrete
  over abstract (see §11).

## 3. Architecture

### 3.1 Repository

```
csmarket/
├── apps/
│   ├── api/        FastAPI, Python package `csmarket` (src/csmarket/…)
│   ├── worker/     Postgres-queue consumer: Waxpeer buy, trade tracking
│   ├── scheduler/  APScheduler: catalogue import (daily), price sync (5 min),
│   │               trade reconcile (2–3 min), history audit (daily), protection watch
│   ├── web/        Next.js 15 App Router, ru/uz/en — storefront + account
│   └── admin/      Vite 5 + React 19 + React Router 7 SPA
├── packages/       ui, api-client (openapi-ts), i18n, utils, config-eslint/tsconfig/tailwind
├── infra/          docker/, caddy/, prometheus/ grafana/ loki/ promtail/, postgres/init, backup/
├── docs/           architecture/, decisions/ (ADR), runbooks/, api/, product/flows/, superpowers/
├── scripts/        bootstrap, gen-api, seed, check-no-yupay.sh
├── .github/workflows/  ci.yml, build.yml, deploy.yml
├── AGENTS.md (CLAUDE.md → symlink), README.md, Makefile
├── docker-compose.yml, docker-compose.prod.yml
└── turbo.json, pnpm-workspace.yaml, package.json, pyproject.toml, uv.lock, .python-version, .nvmrc
```

Stack, tooling, lint/format/type rules, commit conventions, Makefile targets, CI jobs,
Dockerfiles, Caddy, observability and backup scripts are **copied from YuPay** with names
replaced (`yupay` → `csmarket`). GHCR images: `csmarket-{api,worker,scheduler,web,admin}`.

### 3.2 Backend modules (`apps/api/src/csmarket/modules/`)

| Module                                | Ported from (YuPay path under `apps/api/src/yupay/`)                                                                                                                                          | Changes                                                                                                                                                  |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core/`                               | `core/` (db, config, redis, logging, metrics, money, idempotency, ids, errors, clock, crypto, cache_headers, client_ip, events, outbox)                                                       | drop `outbound*` (merchant-webhook delivery)                                                                                                             |
| `auth`                                | `modules/auth/` (`steam.py`, `jwt.py`, `cookies.py`, `deps.py`, `security.py`, `ip_guard.py`, `service.py`)                                                                                   | keep Steam OpenID + EdDSA JWT (15 min) + rotating refresh (30 d) + blocklist + ip_guard; drop `google.py`, `telegram.py`, `dev_login.py`, password paths |
| `users`                               | `modules/users/`                                                                                                                                                                              | `steam_id` is the identity; email optional; trade link lives here; no password/delivery_email/display_currency                                           |
| `payments` + `click`, `payme`, `uzum` | `modules/payments/` (FSM, idempotency, gateways/base, click, payme, uzum, wallet, mock, _stub) + `modules/click`, `payme`, `uzum` (webhook twins)                                             | as is; `purpose: order                                                                                                                                   | topup`; own kassa credentials; `paynet`/`octo` not ported |
| `wallet`                              | `modules/wallet/`                                                                                                                                                                             | as is: double-entry ledger, `NORMAL_SIDE` per kind, `post()` invariant, `admin.adjust` the only manual mutation                                          |
| `fx`                                  | `modules/fx/`                                                                                                                                                                                 | CBU rate, snapshot per order                                                                                                                             |
| `skins`                               | `modules/skins/` (all files) + `modules/fulfillment/suppliers/waxpeer_client.py`, `waxpeer_skins.py`, `waxpeer_trades.py`, `modules/fulfillment/skin_sweeps.py` + scheduler jobs `skins_*.py` | one module; the Waxpeer client lives here; **no `Fulfiller` protocol, no SKU, no supplier mapping**                                                      |
| `orders`                              | **new, thin**                                                                                                                                                                                 | order = one skin, one offer; statuses, money, trade (§5, §7)                                                                                             |
| `admin`                               | `modules/admin/` (deps, audit) + skins admin routes (`admin.py`, `admin_ops.py`, `admin_reports.py`, `admin_trades.py`)                                                                       | no catalog / suppliers / brands / merchants                                                                                                              |
| `notifications`                       | `modules/notifications/`                                                                                                                                                                      | email only (receipt, "trade sent", "refunded"); Telegram later                                                                                           |
| `realtime`                            | `modules/realtime/`                                                                                                                                                                           | WS order status for the order page                                                                                                                       |

Not ported: `catalog`, `gifts`, `blog`, `merchants`, `integrations`, `sourcing`, `inventory`,
`promo`, `promotions`, `affiliate`, `reviews`, `broadcasts`, `stats`, `delivery`, `evidence`,
`storage` (no user files), `paynet`, `pricing` (YuPay's per-SKU pricing — skins has its own).

### 3.3 Frontend

- `apps/web`: layout, `components/skins/*`, `app/[locale]/skins/*` (renamed to the routes in
  §10), order page + `SkinTradeCard`, wallet pages, Steam sign-in, `lib/skins.ts`,
  `lib/skin-seo.ts`, `lib/skin-landing.ts`, `lib/skin-checkout.ts`, sitemap routes. Home = the
  catalogue. Own colours, name, copy.
- `apps/admin`: skins pages (trades, pricing, sales, catalogue) + payments, users, wallet,
  audit; dashboard.
- `packages/ui`, `packages/i18n` skeleton, `packages/api-client` generator — from YuPay.

## 4. Port rules — nothing YuPay-specific leaks in

1. **Allow-list, not copy-paste.** Every ported module is brought over by an explicit list of
   tables, functions and routes the plan names. Anything not on the list is not copied.
   Re-declare models in `csmarket` with only the columns §5 lists; do not carry YuPay columns
   "just in case".
2. **Rename on the way in.** Package `csmarket`, env prefix `CSMARKET_`, cookie names, metric
   names, log fields, Redis key prefixes — no `yupay` anywhere.
3. **CI guard** `scripts/check-no-yupay.sh` (runs in `ci.yml` `lint-py`): fails on any of
   `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`,
   `merchant_api`, `voucher`, `game_id` in `apps/api/src`, `apps/web/src`, `apps/admin/src`,
   `packages/*/src`. The list is tunable (acquirers legitimately say "merchant" in
   `merchant_trans_id`); the intent is not.
4. **Tests travel with code.** A ported money module comes with its YuPay unit/integration
   tests, adapted, so a silent divergence fails CI.
5. **Docs travel with code.** Each ported module keeps a `README.md` describing what it owns
   here (not YuPay's README verbatim).

## 5. Domain and tables (~14)

Money: `Decimal`, minor units where a table says so; USD with 6 decimals as YuPay does for
Waxpeer prices (units = $0.001).

### users

`id uuid pk, steam_id text unique, display_name, avatar_url, email citext null,
email_verified_at null, locale (ru|uz|en), trade_link text null, trade_link_checked_at null,
trade_link_verdict (ok|warn|bad|null), roles text[] (`admin`), banned_at, ban_reason,
created_at, updated_at, deleted_at`.

### refresh_tokens

As YuPay `auth`: `id, user_id, token_hash, expires_at, revoked_at, created_at` (blocklist by
hash).

### skin_items, skin_pricing_rules, skin_search_aliases

1:1 with YuPay `skins/models.py` (item = market hash name + Doppler phase, slug, taxonomy,
image URL, stored 5-min price, per-item overrides; rules row 1 = the pricing document;
aliases for search).

### orders

`id uuid pk, number char(8) unique (§6), user_id, status, skin_item_id, market_hash_name,
waxpeer_item_id bigint, cost_usd numeric(12,6) (Waxpeer price at checkout), price_usd
numeric(12,6), price_uzs numeric(14,0), fx_snapshot_id, trade_link text (snapshot),
idempotency_key, created_at, paid_at, expires_at, delivered_at, cancelled_at, failed_at,
refunded_at, refunded_to (balance|null), failure_reason text null, claimed_at, claimed_by`.

Statuses and transitions:

| From         | To           | Trigger                                                                              |
| ------------ | ------------ | ------------------------------------------------------------------------------------ |
| `pending`    | `paid`       | balance debit, or acquirer webhook success                                           |
| `pending`    | `cancelled`  | `expires_at` passed (scheduler) or user cancel                                       |
| `paid`       | `buying`     | worker claim (`FOR UPDATE SKIP LOCKED`)                                              |
| `buying`     | `trade_sent` | Waxpeer `buy-one-p2p` success (→ `skin_trades` row)                                  |
| `buying`     | `failed`     | no offer ≤ cost, Waxpeer balance low, hard error → **refund to balance** + ops alert |
| `trade_sent` | `delivered`  | Waxpeer status 4 **with `release_date` set** (buyer accepted)                        |
| `trade_sent` | `returned`   | Waxpeer status 6 (declined / not accepted / cancelled) → **refund to balance**       |

`failed` and `returned` are terminal; the refund is posted in the **same transaction** that
sets them, recorded by `refunded_at` / `refunded_to` (there is no separate `refunded` status).
`delivered` and `cancelled` are the other terminal states.

The `orders` table is the queue (ADR-0064 shape): `paid` rows are claimable; the transaction
that writes `paid` also `NOTIFY orders`. Handlers are idempotent — a claim can be re-run; a lost
Waxpeer response is resolved by `check-many-project-id` (project_id = order id), never by
buying again.

### skin_trades

`order_id pk/fk, waxpeer_trade_id, project_id (= order id), status int, escrow_status,
is_released bool, release_date, send_until, steam_trade_id, seller_name, seller_avatar,
seller_level, seller_since, reason, penalties jsonb, last_polled_at, attention bool,
resolved_at, note, created_at, updated_at`.

### payments

`id, number (for top-ups: `T` + 7 chars; for orders the order number is the acquirer id),
purpose (order|topup), order_id null, topup_id null, user_id, provider (click|payme|uzum|wallet),
provider_ref, amount_uzs, status (FSM as YuPay: created → pending → succeeded | failed |
cancelled | refunded), idempotency_key, created_at, updated_at, succeeded_at`. Provider
webhook logs: `click_webhooks`, `payme_transactions`, `uzum_transactions` as in YuPay's twins.

### wallet_accounts, ledger_entries

As YuPay `wallet`: one account per user (UZS), entries with `kind` ∈ `topup, purchase, refund,
admin_adjust` (later `sell_payout`), `NORMAL_SIDE` per kind, `post()` keeps debits = credits.

### wallet_topups

`id, number ('T'+7), user_id, amount_uzs, payment_id, status, created_at, succeeded_at`.

### fx_snapshots

`id, usd_uzs numeric(12,4), source (cbu), fetched_at`.

### admin_audit_log

`id, actor_user_id, action, target_type, target_id, payload jsonb, created_at`.

## 6. Order number

`orders.number`: 8 characters from the Crockford base32 alphabet
`0123456789ABCDEFGHJKMNPQRSTVWXYZ`, generated with `secrets.choice`, unique index, up to 3
retries on collision (32⁸ ≈ 1.1 × 10¹²). Shown as `#7K3M9QX2`; used in `/orders/7K3M9QX2`,
emails, admin search, and as the acquirer's order id (`merchant_trans_id` for Click,
`account.order` for Payme/Uzum). Top-ups: `T` + 7 characters, so a webhook is recognisable by
prefix. Sequential numbers are rejected: a competitor could count our sales.

## 7. Flows

### 7.1 Sign-in (Steam OpenID 2.0)

`GET /auth/steam/start` → Steam → `GET /auth/steam/callback` (verify OpenID, fetch
`GetPlayerSummaries` with the csmarket Steam Web API key) → upsert user by `steam_id` → cookies
(access 15 min EdDSA JWT, refresh 30 d rotating). Admin SPA uses the same flow with a
`return_to` on the admin host; `/admin/*` requires the `admin` role. Sign-in is rate-limited by
`ip_guard`.

### 7.2 Trade link (account)

User pastes the link once (`PUT /me/trade-link`). Parsed (`partner`, `token`), must belong to
the signed-in `steam_id`; advisory checks: Waxpeer `POST /v1/check-tradelink` and Steam
`GetTradeHoldDurations` (a non-zero escrow → verdict `bad` with the reason: no mobile
authenticator for 7 days; checkout is refused and the buy panel says how to fix it — owner
decision 2026-10-01, as in YuPay: a held trade can roll back after the sale, and a
buyer-fault rollback costs a 30 % Waxpeer penalty and risks P2P suspension).
Verdict cached 10 min in Redis keyed by a hash of the link; the token is never logged.
Without a link the buy button leads to the account page.

### 7.3 Item page and offers

`GET /skins/{slug}` from Postgres; `GET /skins/{slug}/listings` → Waxpeer search-by-name from
the handler on a cache miss (90 s fresh / 1 h stale), process-wide budget under Waxpeer's
20/min, 2-min breaker, **degrades** to the 5-min snapshot with `degraded: true`; own
`ip_guard` bucket. (This is the one non-money external call in a request handler; documented
as such in AGENTS.md §10 of this repo.)

### 7.4 Checkout

`POST /orders` (Idempotency-Key, signed in, trade link present): body `{item_id, offer_id}`.
Server re-prices: `check-availability` for the live Waxpeer price; ±2 % tolerance to the
client's quote; if the offer is gone, the cheapest `auto` offer of the same item at ≤ paid
price + 3 % is substituted, else 409 with the next offer. Price = pricing rules(cost USD) →
sell USD → soʻm at the fx snapshot with rounding from the rules; floor $0.10 (~1 200 soʻm;
acquirer minimum is 1 000). Order `pending`, `expires_at = now + 15 min`. **One skin per
order.**

### 7.5 Payment

Balance covers it → ledger `purchase` debit, payment `provider=wallet` succeeded, order `paid`
— one transaction, then `NOTIFY orders`. Otherwise `POST /orders/{number}/pay {provider}`
creates the `payments` row and returns the redirect; the acquirer webhook (signature verified
**before** the body is parsed, raw-body middleware) → `succeeded` → order `paid` + NOTIFY. Balance
is pre-selected in the UI when it covers the order (YuPay `prefer-balance` behaviour). No mixed
payment (balance + card) in MVP.

### 7.6 Worker: buy at Waxpeer

Claim `paid → buying`. `GET /v1/buy-one-p2p` with `item_id`, `price = cost_usd` (Waxpeer refuses
with `new_price` if it rose — our drift guard), `partner`/`token`, `project_id = order.id`.
Lost response → `check-many-project-id` first; only a confirmed absence is a retry. Refused on
price → substitute per §7.4 rule once; still nothing → `failed`. Waxpeer balance below the
price → `failed` at once + ops alert (owner's YuPay choice: refund immediately, do not stall).
Success → `trade_sent`, `skin_trades` row, WS event, email if the user has one.

### 7.7 Scheduler: trades

- `trades_reconcile` every 2–3 min over `trade_sent` orders via `check-many-project-id`:
  status 4 + `release_date` set → `delivered` (keep "protected until release_date" on the trade
  row); status 6 → `returned` → refund; `penalties` present → keep the money spent, alert.
- `protection_watch` daily: status 5 or a rollback after `delivered` → alert, admin attention.
- `history_audit` daily: `my-history` last 14 days vs our orders; alert once per divergence
  (orphan buys, reverted trades).
- `expire_pending` every minute: `pending` past `expires_at` → `cancelled`.

### 7.8 Refund to balance

`failed` / `returned` → ledger `refund` credit to the user's wallet, `refunded_to = balance`,
`refunded_at`, WS event `order.refunded`, email. Money guards ported from YuPay: while a skin is
in flight (`buying`, `trade_sent`) an acquirer cancel and an admin refund are refused; a retry
of a refunded order is refused; admin manual refund only from `failed`/`returned`/`attention`.

### 7.9 Balance top-up

`POST /wallet/topups {amount_uzs, provider}` → `wallet_topups` + `payments(purpose=topup)` →
redirect → webhook → ledger `topup` credit. Minimum 1 000 soʻm. No withdrawal in MVP.

## 8. Waxpeer facts to build on (measured in YuPay, 2026-09-28)

- The API key is **IP-whitelisted**: every call from a non-whitelisted address is
  `403 "You need to whitelist your IP"`. The csmarket VPS IP goes on the csmarket account.
- `buy-one-p2p` answers at once with `{success, id, price}`; `project_id` round-trips through
  `check-many-project-id`; an unknown `project_id` answers `{"success": true, "trades": []}`.
- Status axis: `0 processing → 1 creating → 2 seller confirm → 4 sent, buyer can accept → 5
completed`, `6 declined/refunded`; `escrow_status`, `is_released`/`release_date` (7-day Steam
  trade protection after accept), `send_until` (+5 min at 0, +10 at 2, +30 at 4),
  `trade_id` (Steam offer, deep link `https://steamcommunity.com/tradeoffer/{trade_id}/`),
  `seller_*`, `reason`, `penalties` (`rollback_fee` 20 % + `rollback_penalty` 10 % on
  buyer-fault rollback).
- **Acceptance = `release_date` appearing at status 4.** Waiting for 5 would hold every order a
  week.
- A declined / unaccepted offer → 6 within about a minute, `reason: "Buyer failed to accept"`,
  `penalties: null`, Waxpeer refunds our balance in full.
- Rate limits: search-by-name and mass-info share 20 req/min (partner status lifts it);
  `/v1/prices/snapshot?format=csv` (all listings, `auto` flag) is the price source, 429 with
  `Retry-After: 1` under load.
- Listings: `auto: bool` and `delivery: bot|p2p` on `search-items-by-name?delivery_details=1`;
  buy only `auto`.
- Images: ByMykel's Steam CDN URLs, host rewritten to a reachable one (Akamai host did not open
  from Uzbekistan) — `cs2_skins_image_host` setting; `/256fx256f` on cards, `/512fx384f` on the
  item page.

## 9. Pricing

Port `skins/pricing.py` and `DEFAULT_RULES` as the seed of `skin_pricing_rules` row 1:
expenses %, brackets per channel, liquidity bands, category/weapon adjustments, min margin
$0.03, floor $0.10, UZS rounding. Admin edits the document with a preview (`admin/skins/pricing`)
and per-item overrides. `Quote` carries every component that made the price. Sell rate =
CBU USD/UZS snapshot; expenses cover acquirer fees and FX cost. Owner guidance: ~10 % on
liquid mid items, 4–5 % on expensive, ~3 % expenses + 1–5 % margin on cheap.

## 10. Storefront and admin

### Web (`csmarket.uz`, ru/uz/en)

- `/` — the catalogue: search + category tiles strip, then the grid with URL-state filters
  (category, weapon, wear, rarity, StatTrak/Souvenir, price, team for agents), sort `-price`,
  infinite scroll.
- `/item/[slug]` — wear tiles, live offers (seller, float, stickers, inspect link), buy panel,
  FAQ built from the item's numbers; Product/AggregateOffer + FAQPage + BreadcrumbList JSON-LD.
- `/category/[c]`, `/weapon/[w]` — SEO landings; `/sitemap.xml` index + `/skins-sitemap/<n>.xml`
  (5 000 items × 3 locales each) + landings sitemap; unknown slug = 404 (real one — keep the
  page non-streaming so `notFound()` returns 404, unlike YuPay's soft-404).
- `/account` — Steam profile, trade link with an inline «где взять?» hint, optional email.
- `/account/orders`, `/orders/[number]` — history; order page with the trade card
  («Покупаем» → «<seller> отправил обмен — примите в Steam до HH:MM» + deep link → «Получено» /
  «Отменено — деньги вернулись на баланс»), WS-driven.
- `/account/balance` — balance, ledger, top-up.
- `/how-it-works`, `/faq`, `/terms`, `/privacy`, `/contacts` — static, i18n.
- Sign-in button «Войти через Steam» in the header.

SEO wording (from YuPay's 2026-09-30 keyword research): Uzbekistan searches in Google
(Yandex ≈ 0); the biggest query is English «cs2 skins»; Russian queries write «кс2» in Cyrillic
(«скины кс2», «ножи кс2», «кейсы кс2», «агенты кс2»). RU titles/H1 say «КС2» with «(CS2)»
beside; UZ hub title carries «CS2 skins»; EN H1 «CS2 skins». Rarity names stay English.

### Admin (`admin.csmarket.uz`)

- Dashboard: sales day/week, margin, Waxpeer balance, orders needing attention.
- Trades: attention queue + «Разобрано», refund / retry, note.
- Pricing: rules document + preview, per-item override.
- Orders / Payments: search by number, statuses, webhook logs.
- Users: card (Steam, trade link + verdict, balance, orders), ban, `wallet.adjust` with reason.
- Catalogue: import/sync status, search aliases, hide an item.
- Audit log.

## 11. i18n and copy

- ru/uz/en catalogs in `packages/i18n/locales/{ru,uz,en}/*.json`; every key in all three in
  the same PR; ICU plurals; `Intl.NumberFormat` for soʻm.
- Copy rules (owner): short sentences; outcome, not mechanism; no service meta (sync/refresh
  intervals); no refund/supplier internals in customer copy; concrete over abstract («в
  Узбекистане», not «в СНГ»); «вы», not «ты»; never claim «всегда дешевле».
- Never log PII: Steam ID, email, IP, trade-link token. Order numbers and amounts are fine.

## 12. Infra and deploy

- **VPS**: new, same provider as YuPay; 4 vCPU / 8 GB / ≥ 80 GB SSD. One
  `docker-compose.prod.yml`: caddy, api, worker, scheduler, web, admin, postgres 16, redis 7,
  prometheus, grafana, loki, promtail. No MinIO.
- **Domains**: `csmarket.uz` (web), `api.csmarket.uz`, `admin.csmarket.uz`,
  `grafana.csmarket.uz` (basic-auth). Cloudflare in front (WAF there; slowapi per route in
  FastAPI; no Caddy rate_limit).
- **Secrets**: `secrets/*.env` via sops + age, csmarket's own age key; acquirer keys, Waxpeer
  key, Steam Web API key (issued per domain — YuPay's does not work), JWT keys.
- **CI/CD**: `ci.yml` (lint-py incl. `check-no-yupay.sh`, lint-ts, test-py, test-ts,
  openapi-drift, docs-check), `build.yml` → GHCR `sha-xxxxxxx`, `deploy.yml` by `image_tag` over
  SSH; `IMAGE_TAG` pinned in the compose env so a plain `up -d` never rolls back.
- **Backups**: `pg_dump → age → rclone → Cloudflare R2`, own bucket, daily.
- **Alerts** (Prometheus → ops Telegram with `[csmarket]` prefix): API p95 high, `paid` orders
  older than 5 min, `trade_sent` without a poll result > 30 min, Waxpeer balance below
  threshold, audit divergences, webhook signature failures spike.
- **Sentry**: own project. **Prod restarts** always with `IMAGE_TAG`.

## 13. Security

- Webhooks verify signatures before parsing the body (raw-body middleware); each provider's
  IP allow-list where the provider publishes one.
- Every state-changing endpoint accepts `Idempotency-Key`; results persisted by key.
- Rate limits on every public route; `ip_guard` two-axis limiter on sign-in, trade-link check,
  order creation, top-up creation.
- Money as `Decimal` / `string`, minor units; never floats.
- Admin actions audited; `wallet.adjust` needs a reason.
- gitleaks pre-commit; secrets only via sops.

## 14. Testing

Same rules as YuPay's AGENTS.md §8: TDD for new modules and reproducible bugs; pytest +
testcontainers (Postgres/Redis); respx contract tests for Waxpeer (recordings ported from
YuPay); hypothesis on pricing and the ledger; coverage ≥ 95 % on `payments`, `wallet`,
`orders`, `skins`, ≥ 80 % elsewhere; each acquirer gateway: success / retryable failure /
idempotent re-call; Vitest on web and admin; Playwright e2e: sign-in (mocked Steam), buy from
balance, buy via mocked acquirer, refund on `returned`. `check-no-yupay.sh` in CI.

## 15. Milestones (each = its own plan, its own deploy)

| #   | Scope                                                                                                              | Done when                                                                 |
| --- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| M0  | Repo skeleton: tooling, CI, compose, Caddy, `core`, health, `AGENTS.md` (full YuPay-style), `check-no-yupay.sh`    | `csmarket.uz` answers a hello page from CI-built images                   |
| M1  | `auth` (Steam), `users`, roles, account page, trade link + advisory checks; admin shell with role gate             | a user signs in and saves a trade link; an admin steam_id opens the admin |
| M2  | `skins`: tables, ByMykel import, price sync, read API, `/`, `/item`, landings, sitemaps, SEO; admin catalogue page | the catalogue is browsable, no buying                                     |
| M3  | `fx`, `wallet`, `payments` + Click/Payme/Uzum, top-ups; admin users/wallet/payments                                | a balance is topped up through a real kassa                               |
| M4  | `orders`, worker buy, trades reconcile/audit, refunds, order page + WS, emails; admin trades/pricing/dashboard     | first real sale end to end                                                |
| M5  | Launch: VPS, secrets, backups, alerts, runbooks, Waxpeer whitelist, pricing seed, test buys (declined + accepted)  | prod, owner sign-off                                                      |

## 16. Owner to-dos before M5

- New Waxpeer account, funded, csmarket VPS IP whitelisted.
- Click / Payme / Uzum kassas for csmarket (separate from YuPay).
- VPS ordered; DNS for the four hosts in Cloudflare.
- Steam Web API key registered on `csmarket.uz`.
- Sentry project; R2 bucket; ops Telegram chat id (may reuse YuPay's).

## 17. Open questions (not blocking M0–M2)

- ~~Trade-hold links: `warn` or `bad`?~~ Decided 2026-10-01: `bad` (refuse), as in YuPay (§7.2).
- ~~Email provider?~~ Decided 2026-10-01: Resend.
- Paynet: only if the owner opens a kassa; the twin exists in YuPay and can be ported later.
- Sell side (skinslink): API shape unknown yet; the only MVP hooks are the `sell` module slot
  and the `sell_payout` ledger kind. **2026-10-06:** Skinslink became a **buy** source first
  (spec `2026-10-06-skinslink-buy-source-design.md`, ADR-0010); its client, webhook and
  models are what the sell side reuses later. Selling stays a separate spec.
- P2P selling (seller lists and sends the trade, 7-day hold, Chrome extension for trade
  checks): parked until after launch; the discussion is in `docs/product/p2p-later.md`.

## 18. References (source material in `~/Projects/yupay`)

- `AGENTS.md` — the rulebook this repo's `AGENTS.md` is derived from.
- `docs/decisions/0093-cs2-skins-via-waxpeer.md`; `docs/decisions/0064-*` (Postgres queue);
  `0028` (rate limits); `0010` (admin SPA, no SSR).
- `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` and the four skins plans in
  `docs/superpowers/plans/2026-09-2{8,9}-cs2-skins-*.md`.
- `apps/api/src/yupay/modules/skins/README.md`; `docs/product/flows/skins-buy.md`,
  `skins-browse.md`; `docs/runbooks/skins-purchase.md`; `docs/architecture/cache-keys.md`.
- `apps/api/src/yupay/modules/{auth,users,payments,click,payme,uzum,wallet,fx,admin,notifications,realtime}/`.
- `apps/worker/src/yupay_worker/consumer.py`; `apps/scheduler/src/yupay_scheduler/jobs/skins_*.py`.
- `apps/web/src/components/skins/`, `apps/web/src/app/[locale]/skins/`, `apps/web/src/lib/skin*.ts`,
  `apps/web/src/lib/prefer-balance.ts`; `apps/admin/src/features/` (skins, payments, users, wallet).
- `infra/`, `.github/workflows/`, `Makefile`, `docker-compose*.yml`, `scripts/`.
- YuPay memory notes (`~/.claude/projects/-Users-macbook-uz-Projects-yupay/memory/`):
  `cs2-skins-state.md`, `skinsavdo-competitor.md`, `skins-seo-keywords.md`, `csmarket-plan.md`,
  `deploy-push-cadence.md`, `prod-restart-needs-image-tag.md`, `never-pkill-by-pattern.md`.
