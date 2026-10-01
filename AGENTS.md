# AGENTS.md — Briefing for AI Agents Working on csmarket.uz

> Read this entire file before making any changes. It is the contract between you and the
> project. A task is only complete when it satisfies the **Definition of Done** (§15).
> `CLAUDE.md` is a symlink to this file. Humans follow the same rules.

---

## 0. Status and handoff

- **Spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md`, approved by the owner on
  2026-10-01. **The design is the spec.** Every decision in it was approved in conversation —
  do not re-litigate; ask only about what spec §17 leaves open.
- **Milestones** (spec §15), each with its own plan written with `superpowers:writing-plans`
  and saved to `docs/superpowers/plans/`, and its own deploy:

  | #   | Scope                                                            | Plan                                                      |
  | --- | ---------------------------------------------------------------- | --------------------------------------------------------- |
  | M0  | Repo skeleton: tooling, CI, compose, Caddy, `core`, health, docs | `docs/superpowers/plans/2026-10-01-m0-skeleton.md`        |
  | M1  | `auth` (Steam), `users`, roles, account page, trade link         | `docs/superpowers/plans/2026-10-01-m1-auth-users.md`      |
  | M2  | `skins` catalogue: import, price sync, read API, storefront, SEO | `docs/superpowers/plans/2026-10-01-m2-skins-catalogue.md` |
  | M3  | `fx`, `wallet`, `payments` + Click / Payme / Uzum, top-ups       | not written yet                                           |
  | M4  | `orders`, worker buy, trade tracking, refunds, order page, email | not written yet                                           |
  | M5  | Launch: VPS, secrets, backups, alerts, runbooks, test buys       | not written yet                                           |

- **Where things stand:** M0–M2 merged on local `main`. There is no git remote yet; nothing
  is pushed or deployed. M0 is done for good when `https://csmarket.uz/` answers from CI-built
  images. Next: the M3 plan, when the owner asks for it.
- **Owner inputs still pending:** the M0 deploy needs the GitHub repo, the VPS, DNS for the
  hosts in Cloudflare and the repo secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`
  (`docs/runbooks/first-deploy.md`). Everything later is listed in spec §16.

---

## 1. Project identity

**csmarket.uz** is a standalone CS2-skins shop for Uzbekistan. A visitor browses a catalogue of
~35k items (ours, imported from ByMykel/CSGO-API), signs in with Steam (the only sign-in), pays
in soʻm through Click, Payme or Uzum or from an internal balance, and receives the skin as a
Steam trade offer. **Waxpeer is the only supply**: the worker buys the listing at payment and
Waxpeer's seller sends the offer straight to the buyer's trade link. A failed or declined trade
is refunded to the balance. Web only, in ru / uz / en; no Mini App, no bot.

The project has its own repo, database, VPS, Waxpeer account and acquirer kassas, and shares
**nothing at runtime** with YuPay — most of the code is ported from YuPay by allow-list (§6).
**MVP = the buy side.** Selling skins to us (via the skinslink aggregator) comes later; the MVP
only leaves room for it. Main competitor: skinsavdo.uz — the aim is parity with a fair margin,
not a price war.

---

## 2. Tech stack at a glance

| Area                | Choice                                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------------------- |
| Backend             | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, `uv`                               |
| Background work     | Postgres-native queue (`FOR UPDATE SKIP LOCKED` + `LISTEN/NOTIFY`) drained by `apps/worker`          |
| Periodic work       | APScheduler in `apps/scheduler`                                                                      |
| Data                | PostgreSQL 16, Redis 7                                                                               |
| Storefront          | Next.js 15 (App Router, RSC), TypeScript strict, Tailwind v4, next-intl v4                           |
| Admin SPA           | Vite 5 + React 19 + React Router 7, TanStack Query v5, Zustand. No SSR                               |
| Shared UI           | `@csmarket/ui` (shadcn-style: class-variance-authority + tailwind-merge), lucide icons               |
| API client          | `@hey-api/openapi-ts` generated from FastAPI's OpenAPI 3.1 schema                                    |
| Monorepo            | pnpm workspaces + Turborepo (TS) + uv workspace (Python) + top-level `Makefile`                      |
| Reverse proxy / TLS | Caddy 2 (own edge, Let's Encrypt) behind Cloudflare — ADR-0003                                       |
| Observability       | Prometheus + Alertmanager (Telegram) + Grafana + Loki + Promtail, Sentry SaaS                        |
| Email               | Resend (M4)                                                                                          |
| Secrets             | env files on the server (`secrets/*.env`); sops + age from M5                                        |
| Backups             | `pg_dump` → age → rclone → Cloudflare R2, nightly                                                    |
| CI/CD               | GitHub Actions → GHCR (`sha-xxxxxxx` tags) → SSH deploy by image tag                                 |
| Tests               | pytest + testcontainers + respx + hypothesis (Py); Vitest + Testing Library + Playwright (TS)        |
| Lint / format       | ruff, mypy --strict (Py); eslint flat config, prettier, tsc (TS); pre-commit + commitlint + gitleaks |

---

## 3. Repository layout

```text
csmarket/
├── apps/
│   ├── api/          FastAPI modular monolith, package `csmarket`
│   │                 (src/csmarket/{core,modules,api}, migrations/, tests/{unit,integration})
│   ├── worker/       Postgres-queue consumer (`csmarket_worker`)
│   ├── scheduler/    APScheduler process (`csmarket_scheduler`, jobs/)
│   ├── web/          Next.js storefront, ru / uz / en
│   └── admin/        Vite + React SPA
├── packages/
│   ├── ui/  api-client/  i18n/  utils/
│   └── config-eslint/  config-tsconfig/  config-tailwind/
├── e2e/              Playwright smoke and journeys
├── infra/
│   ├── docker/       one Dockerfile per app (+ *.dev.Dockerfile for the dev compose)
│   ├── caddy/        Caddyfile.dev, Caddyfile.prod
│   ├── prometheus/  alertmanager/  grafana/  loki/  promtail/
│   ├── postgres/init/  backup/  secrets-example/
├── docs/
│   ├── architecture/  decisions/  runbooks/  api/  onboarding/  security/
│   └── superpowers/   specs/ and plans/ — the design spec is the source of truth
├── scripts/          bootstrap.sh, check-no-yupay.sh (+ .allow), gen-secret.sh, port-rename.sed
├── .github/          workflows/{ci,build,deploy}.yml, PR and issue templates, dependabot
├── AGENTS.md         ← you are here (CLAUDE.md → symlink)
├── README.md  CONTRIBUTING.md  SECURITY.md  LICENSE
├── Makefile          single entrypoint for common tasks
├── docker-compose.yml        dev
├── docker-compose.prod.yml   the one VPS
└── turbo.json  pnpm-workspace.yaml  package.json  pyproject.toml  uv.lock  .python-version  .nvmrc
```

---

## 4. Where to put new code

| You are adding…         | It goes in…                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A backend domain module | `apps/api/src/csmarket/modules/<name>/` with `api.py` (the interface other modules import), `routes.py`, `service.py`, `models.py`, `schemas.py`, `README.md`. Mount the router in `apps/api/src/csmarket/api/v1/router.py` (never in the package `__init__.py`: `api/v1/deps.py` importers run it first, closing an import cycle). Import its models in `apps/api/migrations/env.py`, and in `apps/scheduler/src/csmarket_scheduler/main.py` once a job touches it, so relationship mappers resolve. Tests in `apps/api/tests/{unit,integration}/` |
| A payment provider      | `modules/payments/gateways/<provider>.py` + its webhook twin module (`modules/click`, `payme`, `uzum`) — M3. The webhook route goes on the `bootstrap._exempt_self_authenticating_routes` list                                                                                                                                                                                                                                                                                                                                                      |
| Background work         | A table with a claimable status, written together with `NOTIFY <channel>` in the same transaction; a `Queue` entry in `apps/worker/src/csmarket_worker/consumer.py::_queues`, with the channel constant imported from the module that notifies. Handlers are idempotent — a claim can always be re-run                                                                                                                                                                                                                                              |
| A periodic job          | `apps/scheduler/src/csmarket_scheduler/jobs/<name>.py` exposing `register(scheduler)`, called from `main.build_scheduler`. Long periods use `startup.first_run_after(n)`, staggered ≥ 15 s apart. Jobs only time work; the logic lives in a module's service                                                                                                                                                                                                                                                                                        |
| A storefront page       | `apps/web/src/app/[locale]/<segment>/page.tsx` (+ `loading.tsx`, `error.tsx`). Unmatched paths render the root `app/not-found.tsx`. A page that calls `notFound()` must stay non-streaming, and a test must see a real 404 status (Next 15 otherwise answers an empty shell)                                                                                                                                                                                                                                                                        |
| An admin page           | `apps/admin/src/features/<area>/<Page>.tsx`, route in `apps/admin/src/app/router.tsx`. The `features/` folder arrives with the first ported area (M1); M0's shell pages sit in `src/routes/`                                                                                                                                                                                                                                                                                                                                                        |
| Translations            | `packages/i18n/locales/{ru,uz,en}/<namespace>.json` — all three in the same PR                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| A shared UI component   | `packages/ui/src/components/<Name>/` with `<Name>.tsx`, `<Name>.test.tsx`, `index.ts`                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| A shared TS utility     | `packages/utils/src/<feature>.ts`, tests next to it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| A dependency            | `uv add` in the owning `apps/*/pyproject.toml` / `pnpm add --filter <pkg>`; commit `uv.lock` / `pnpm-lock.yaml` with it (images install with `pnpm install --frozen-lockfile` and fail on a stale lockfile). A new dependency needs an ADR                                                                                                                                                                                                                                                                                                          |
| A setting               | a field on `Settings` in `apps/api/src/csmarket/core/config.py` (read as `CSMARKET_<NAME>`), plus `.env.example` and, if prod needs it, `infra/secrets-example/api.env`                                                                                                                                                                                                                                                                                                                                                                             |
| Infra                   | `infra/<service>/`; update both `docker-compose.yml` and `docker-compose.prod.yml` where it applies. A new `make` target also goes in §13                                                                                                                                                                                                                                                                                                                                                                                                           |

---

## 5. Where to put documentation (MANDATORY)

> **A PR is incomplete if code changes do not bring the matching doc changes.** CI's
> `docs-check` job fails a PR that touches `apps/api/src/csmarket/modules/` without touching
> `docs/`. When unsure, document first, code second — the doc forces the design.

| Change                                                                | Required doc update                                                                                                                                 |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| New module or boundary change                                         | `docs/architecture/module-map.md` + the module's `README.md` + a Mermaid diagram in `docs/architecture/sequence-diagrams/<flow>.mmd` for a new flow |
| Architectural decision (new dependency, pattern, infra service, swap) | New ADR `docs/decisions/NNNN-<title>.md` from `docs/decisions/0000-template.md`                                                                     |
| New operational concern (alert, failure mode, manual step)            | New or updated file in `docs/runbooks/`; an alert's `runbook:` annotation links to it                                                               |
| New or changed endpoint                                               | `make gen-api` and commit `docs/api/openapi.json` + the client; notes in `docs/api/README.md` for auth / idempotency / limits                       |
| User-facing flow change                                               | `docs/product/flows/<flow>.md` with a Mermaid sequence diagram                                                                                      |
| New Redis key                                                         | `docs/architecture/cache-keys.md` (created with the first key)                                                                                      |
| New domain metric                                                     | `docs/architecture/metrics.md` (written in M1 with the first counter)                                                                               |
| Security- or PII-relevant change                                      | `docs/security/pii-handling.md`                                                                                                                     |

---

## 6. Porting from YuPay — the allow-list rule

- **Source:** `/Users/macbook_uz/Projects/yupay` and its memory notes at
  `/Users/macbook_uz/.claude/projects/-Users-macbook-uz-Projects-yupay/memory/`. You may
  **read** them freely — code, docs, ADRs, specs, plans. You must **never write** there: no
  edits, no commits, no branch changes, no `git` command that mutates it, nothing in its
  `.claude/`. Copy into this repo, then adapt here. Spec §18 lists the paths worth reading.
- **Allow-list, not copy-paste.** Bring a module by the explicit list of tables, functions and
  routes the milestone plan names. Re-declare models with only the columns spec §5 lists. Do
  not carry YuPay columns, settings, routes or dependencies "just in case".
- **Rename on the way in:** `csmarket`, `csmarket_worker`, `csmarket_scheduler`, `@csmarket/*`,
  the `CSMARKET_` env prefix, and cookie, metric (`csmarket_*`), logger (`csmarket.*`) and
  Redis key names. `scripts/port-rename.sed` does the mechanical part:
  `sed -f scripts/port-rename.sed <yupay file> > <csmarket file>`.
- **CI guard:** `scripts/check-no-yupay.sh` (in `make lint` and CI `lint-py`) scans
  `apps/{api,worker,scheduler,web,admin}/src` and `packages/*/src` and fails on `yupay`,
  `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`, `merchant_api`,
  `voucher`, `game_id` — case-insensitive substrings, except `sku`, which is matched by
  identifier shape (`sku`, `skus`, `sku_id`, `SkuId` hit; `skull`, `skunk` do not). Exit
  codes: 0 clean, 1 hits, 2 a guard failure (bad allow regex, missing perl or find).
  Exceptions go in `scripts/check-no-yupay.allow`, one regex per line, with a reason —
  today only Click's `merchant_trans_id`. `CHECK_NO_YUPAY_ALLOW` overrides the allow-file
  path (the tests use it). Tests, docs and infra are not scanned and may name YuPay.
- **Tests and docs travel with code.** A ported module brings its YuPay tests, adapted, and a
  `README.md` describing what it owns here (not YuPay's README verbatim). (Spec §4; ADR-0002.)

---

## 7. Coding standards

### Python

- Format and lint with **ruff** (`line-length = 100`, `target-version = "py312"`).
- Type-check with **mypy --strict**. Every function — including private — has full
  annotations. **No `Any` unless justified with an inline comment.**
- Docstrings: **Google style**, on every public function, class and module.
- Pydantic v2 only. No mutable dataclasses in the domain layer; use `pydantic.BaseModel`
  (with `model_config = ConfigDict(frozen=True)` for value objects).
- **Async everywhere on the request path.** No `requests`, no `time.sleep`, no sync DB calls.
- No business logic in routers — routers parse and dispatch.
- File length soft limit: **400 LOC**; split before 500. Function length soft limit:
  **50 LOC**; cyclomatic complexity ≤ 10 (ruff `C901`).

### TypeScript

- `strict: true`, `noUncheckedIndexedAccess: true`, `exactOptionalPropertyTypes: true`
  (`packages/config-tsconfig/base.json`).
- **No `any`.** No `as` casts except for narrowing a known-shape JSON or DOM type, with a
  comment.
- All component props are explicit `interface`s; prefer `type` for unions.
- Exhaustive `switch` with a `never` default-case helper.
- Server Components are the default; `"use client"` only when necessary and as deep in the
  tree as possible.
- File length soft limit: **300 LOC**.
- We stay on Next 15.5. next-intl 4 deprecates `setRequestLocale` in favour of a Next 16 API;
  static rendering still needs it, so its call sites carry targeted
  `@typescript-eslint/no-deprecated` disables until the move to Next 16.
- A suppressed lint rule names its reason inline
  (`// eslint-disable-next-line <rule> -- <why>`); lint-staged runs eslint with
  `--max-warnings 0`.

### Naming

- Python: `snake_case` modules and functions, `PascalCase` classes, `UPPER_SNAKE` constants.
- TS: `camelCase` variables and functions, `PascalCase` components and types, `UPPER_SNAKE`
  env vars and constants.
- Files: components `PascalCase.tsx`, hooks `useThing.ts`, utilities `kebab-case.ts`.

---

## 8. Commit & PR conventions

- **Conventional Commits**, enforced by `commitlint` (`commitlint.config.mjs`). Types: `feat`,
  `fix`, `perf`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`, `revert`. Header ≤ 100
  characters, subject not capitalised.
- Scope = the app or module: `api/<module>` (`feat(api/orders): …`), `worker`, `scheduler`,
  `web/<area>`, `admin/<area>`, `packages/<name>`, `infra`, `ci`, `docs`.
- Commit locally after every task. **Never push or deploy without the owner's explicit
  command** (§14).
- One logical change per PR; aim for **< 400 LOC diff** excluding generated files. The PR
  template (`.github/PULL_REQUEST_TEMPLATE.md`) asks for a summary, testing notes, the doc
  checklist, breaking changes and a rollback plan.
- CI checks (`.github/workflows/ci.yml`): `commitlint` and `docs-check` (on PRs), `lint-py`
  (ruff, mypy, check-no-yupay), `lint-ts` (eslint, tsc, prettier), `test-py`, `test-ts`,
  `openapi-drift`.
- Squash-merge to `main`. Release tags are `vMAJOR.MINOR.PATCH`; `build.yml` builds images on
  every push to `main` and on `v*.*.*` tags.

---

## 9. Testing rules

- **TDD** when building a module or fixing a reproducible bug: the failing test first.
- **Coverage gates:** Python ≥ 80 % (enforced: `fail_under = 80` in `pyproject.toml`, CI
  `--cov-fail-under=80`). `payments`, `wallet`, `orders`, `skins` ≥ 95 % — the per-module
  gate is wired in M3; until then CI enforces only the 80 % floor. TS ≥ 70 % is a target; no
  threshold is configured yet.
- **Locations:**
  - Python unit: `apps/api/tests/unit/`; worker and scheduler: `apps/{worker,scheduler}/tests/`.
  - Python integration: `apps/api/tests/integration/`. Each pytest-xdist worker starts its own
    Postgres **and** Redis testcontainers — Docker is the only prerequisite. Never point
    tests at a shared localhost Postgres or Redis (another project's dev stack may be on it).
  - Python contract tests for Waxpeer, respx recordings ported from YuPay:
    `apps/api/tests/contract/` (M2).
  - TS unit: beside the source as `*.test.ts(x)` (Vitest + Testing Library).
  - E2E: `e2e/` at the repo root, Playwright against the dev stack.
- **hypothesis** on pricing (M2) and the ledger (M3).
- **No acquirer gateway or Waxpeer call path merges without tests** for success, retryable
  failure and idempotent re-call.
- **Never disable a failing test.** If a test is wrong, fix it in the same PR and say why in
  the commit body.

---

## 10. Security rules

- Webhooks verify signatures **before** parsing the body (raw-body middleware); provider IP
  allow-lists where published.
- **Never log PII**: Steam ID, email, IP, trade-link token (and the `partner` id inside a trade
  link). Order numbers and amounts are fine. Never print a real trade-link token in chat,
  docs or tests — use redrawn/fake ones. `core/logging.py` redacts by key and stem. Metric
  labels are bounded and never about a person (`core/metrics.py`). Sentry runs with
  `send_default_pii=False` and `include_local_variables=False`. Inventory:
  `docs/security/pii-handling.md`.
- Every state-changing endpoint accepts `Idempotency-Key` (≥ 16 chars) and persists by it
  (`core/idempotency.py`). Advisory `POST`s that write nothing (`/me/trade-link/check`, M1)
  say in their docstring why they are keyless.
- Money as `Decimal` / `string`, never floats; UZS whole units, USD six decimals for Waxpeer
  prices.
- Auth (M1, ADR-0004): 15-min EdDSA JWT access (in memory, Bearer), 30-day rotating refresh in an `HttpOnly` cookie, server-side blocklist; admin =
  Steam sign-in + `admin` role on named `steam_id`s. No passwords anywhere.
- Rate limits: slowapi per route in FastAPI (`bootstrap._build_limiter`, in-process, keyed by
  client IP) + Redis `ip_guard` (M1) on sign-in, trade-link check, order creation, top-up
  creation. Acquirer webhooks are exempt from the coarse tier
  (`bootstrap._exempt_self_authenticating_routes`, one audited list — empty until M3). No
  Caddy `rate_limit`; the volumetric tier is Cloudflare's WAF.
- Client IP = the first `X-Forwarded-For` entry (`core/client_ip.py`), which our Caddy
  overwrites with `{client_ip}` (Cloudflare's `Cf-Connecting-Ip` honoured only from
  Cloudflare's ranges). ADR-0003. Changing Caddy to append breaks both limiters.
- gitleaks pre-commit; secrets only in `secrets/*.env` on the server (sops + age from M5).
  Keys pasted in chat are never stored in the repo or in files; tell the owner to rotate them.

---

## 11. Performance rules

- No synchronous external HTTP in request handlers on the money path. **One advisory
  carve-out**: `GET /skins/{slug}/listings` (M2) calls Waxpeer search-by-name on a cache
  miss — 90 s fresh / 1 h stale cache, process-wide budget 18/min (under Waxpeer's 20/min),
  2-min breaker, 4 s timeout, degrades to the 5-min snapshot with `degraded: true`, own
  `ip_guard` bucket. A
  second carve-out: `POST /me/trade-link/check` (M1; Waxpeer `check-tradelink` + Steam
  `GetTradeHoldDurations`), advisory, 4 s timeouts, 10-min Redis cache keyed by a hash of
  the link. A new one needs an ADR and a line here — and its route in the `handler` regexes
  of `ApiHighLatency` / `ApiWaxpeerLatency` (`infra/prometheus/alerts/api.yml`).
- N+1 guarded by query-count tests on list endpoints; cache keys catalogued in
  `docs/architecture/cache-keys.md`; indices land in the same migration as the query.
- One uvicorn process per API container: CPU an endpoint burns is a ceiling for the whole API.
  The DB pool is 20 connections per process (`core/db.py`); never hold a session across an
  upstream call you can avoid.

---

## 12. i18n and copy

- ru / uz / en catalogs in `packages/i18n/locales`; every key in all three (the parity test in
  `packages/i18n` fails CI otherwise); ICU plurals; `Intl.NumberFormat` for soʻm; dates ISO
  8601 UTC in DB and transit. Never hardcode user-facing strings.
- Copy rules (owner): short sentences; outcome, not mechanism; no service meta («цены
  обновляются каждые 5 минут»); no refund/supplier internals for customers; concrete over
  abstract («в Узбекистане»); «вы», not «ты»; never claim «всегда дешевле» — date any
  price comparison. RU titles say «КС2 (CS2)»; skin names and rarity names stay English.
- UI: cleaner AND clearer; inline «где найти?» hints instead of raw forms.

---

## 13. How to run things

All entrypoints live in the root `Makefile` (`make help` lists them). **Prefer `make` targets
over raw tools.**

| Target                                            | What it does                                                                        |
| ------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `make bootstrap`                                  | Install deps (pnpm + `uv sync --all-packages --all-groups`), pre-commit, API client |
| `make dev` / `make dev-detached`                  | Dev stack via `docker-compose.yml` (foreground / background)                        |
| `make down`                                       | Stop the dev stack                                                                  |
| `make dev-api`                                    | API as a host process on `:8100` (needs dev Postgres + Redis up)                    |
| `make dev-worker` / `make dev-scheduler`          | Worker / scheduler as host processes                                                |
| `make dev-web` / `make dev-admin`                 | Storefront (`next dev`, `:3100`) / admin (Vite, `:3102`) as host processes          |
| `make logs service=api`                           | Tail one dev service                                                                |
| `make migrate`                                    | `alembic upgrade head` inside the dev `api` container                               |
| `make seed-skins`                                 | Dev only: a priced ~60-item catalogue (refuses in prod)                             |
| `make migration name=add_x`                       | Autogenerate an Alembic revision inside the dev `api` container                     |
| `make psql`                                       | psql into the dev database                                                          |
| `make test`                                       | `test-py` + `test-ts`                                                               |
| `make test-py` / `make test-ts` / `make test-e2e` | pytest `-n auto` / Vitest via turbo / Playwright (needs the dev stack)              |
| `make lint` / `make lint-fix`                     | ruff + check-no-yupay + eslint + prettier / autofix                                 |
| `make check-no-yupay`                             | The port guard on its own                                                           |
| `make typecheck`                                  | mypy + tsc                                                                          |
| `make gen-api`                                    | Regenerate `docs/api/openapi.json` + `packages/api-client`                          |
| `make build`                                      | Build the dev compose images                                                        |
| `make deploy tag=sha-xxxxxxx`                     | Dispatch `deploy.yml` to production with that image tag (`docs/runbooks/deploy.md`) |
| `make backup` / `make restore file=… identity=…`  | One-off backup / restore against the **prod** compose (run on the server)           |

Auth helpers (not `make` targets; `docs/onboarding/local-setup.md`, `docs/runbooks/admin-bootstrap.md`):

- Make an account admin (it must have signed in once):
  `docker compose exec api python -m csmarket.scripts.grant_admin --steam-id <17 digits>`;
  add `--revoke` to take it back. Prod: `docker compose -f docker-compose.prod.yml exec api …`.
- Dev login, `POST /api/v1/auth/dev-login {steam_id, display_name?, admin?}`, signs in without
  Steam. **Dev only**: it needs `CSMARKET_DEV_LOGIN_ENABLED=true` and answers 404 in prod
  regardless (`test_prod_never_exposes_dev_login`). Keep the flag `false` in
  `infra/secrets-example/api.env`.

Dev ports (`docker-compose.yml`; csmarket's own block so it can run beside another stack —
each is env-overridable, container ports unchanged):

| Service  | Host                          | Override                                                | In container |
| -------- | ----------------------------- | ------------------------------------------------------- | ------------ |
| api      | `localhost:8100`              | `CSMARKET_API_PORT`                                     | 8000         |
| web      | `localhost:3100`              | `CSMARKET_WEB_PORT`                                     | 3000         |
| admin    | `localhost:3102`              | `CSMARKET_ADMIN_PORT`                                   | 5173         |
| postgres | `127.0.0.1:5442`              | `POSTGRES_PORT`                                         | 5432         |
| redis    | `127.0.0.1:6390`              | `REDIS_PORT`                                            | 6379         |
| caddy    | `:8180` (HTTP), `:8543` (TLS) | `CSMARKET_CADDY_HTTP_PORT`, `CSMARKET_CADDY_HTTPS_PORT` | 80, 443      |

Setup walkthrough: `docs/onboarding/local-setup.md`. Deploys: `docs/runbooks/`.

---

## 14. Owner rules (durable — learned over months on YuPay) and agent etiquette

- **Reply in Russian, tersely.** Lead with the answer; no preamble; the owner reads on a
  phone and acts on the conclusion.
- **Commit locally; NEVER push or deploy without an explicit command in that message.**
  Batch pushes (GitHub Actions minutes). Before any push run `npx prettier --check .`.
- The owner usually says «тесты локально не гоняй» when ordering a deploy — CI runs them.
  Otherwise `make lint typecheck test` before calling work done.
- **Prod restarts always with `IMAGE_TAG`** — a plain `docker compose up -d` must never roll
  back to a stale `:main` image. Mechanism: every deploy pins `IMAGE_TAG=<tag>` in the server
  checkout's git-ignored `~/opt/csmarket/.env`, and `docker-compose.prod.yml` refuses to run
  without it; never `export` a different one by hand. Verify with
  `docker inspect … --format '{{.Config.Image}}'`.
- **Kill processes by PID only.** Never `pkill -f <pattern>` (it once killed Docker Desktop).
  On this laptop, touch only csmarket's own containers (`csmarket-dev`): another project's
  dev stack may be running beside it.
- On servers, never touch anything that can drop or delete data without asking.
- **Never log PII** and the copy/UI rules are owner rules too — see §10 and §12.
- **Never invent business logic**; ask when two valid approaches differ materially, when a
  change crosses module boundaries unexpectedly, or when a destructive operation is implied.
- Don't create summary/report files unless asked; notes go in the PR description.
- Never commit secrets, even in tests. Never disable a failing test or a lint rule without a
  reason in the commit body.
- Write an ADR for a new dependency, a pattern choice, a public-contract change.
- Update this file when a rule is contradicted by reality or a convention emerges. Tools do
  not write here: `turbo.json` sets `"agentGuidance": false`; delete any block a tool injects.
- Use the superpowers skills: `brainstorming` for anything new, `writing-plans` →
  `executing-plans` / `subagent-driven-development` per milestone, `test-driven-development`
  on every task, `systematic-debugging` for bugs, `verification-before-completion` before
  claiming done.

---

## 15. Definition of Done

A task is **done** only when **all** of the following are true:

- [ ] All acceptance criteria from the plan / spec are met.
- [ ] `make lint typecheck test` passes locally (unless the owner said «тесты локально не
      гоняй») and in CI.
- [ ] `scripts/check-no-yupay.sh` passes (it runs inside `make lint`).
- [ ] New code has tests; coverage gates are met (§9).
- [ ] OpenAPI schema and TS client regenerated (`make gen-api`); no drift.
- [ ] Affected documentation updated in the same change (§5: architecture, ADR, runbook,
      module README, as applicable).
- [ ] All three locales (ru / uz / en) updated for any new user-facing string.
- [ ] No new `TODO` or `FIXME` without a tracked issue link.
- [ ] No secrets, PII or large binary blobs committed.
- [ ] Conventional Commit message(s); PR description with summary, testing notes,
      screenshots (UI) and rollback plan.
- [ ] Nothing pushed or deployed without the owner's explicit word.
