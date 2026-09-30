# AGENTS.md — csmarket.uz

> Read this whole file first. It is the handoff from the conversation that designed this
> project (held in the YuPay repo on 2026-10-01) to whoever continues it here. Milestone M0
> replaces it with a full YuPay-style rulebook; keep the **Handoff**, **Owner rules** and
> **YuPay access** sections when you do.

## What this is

**csmarket.uz** — a standalone CS2-skins shop for Uzbekistan: browse ~35k items, pay in soʻm
(Click / Payme / Uzum or an internal balance), get the skin as a Steam trade offer bought from
**Waxpeer**. Own repo, database, VPS, Waxpeer account and acquirer kassas. Shares nothing at
runtime with YuPay; most code is **ported** from it. MVP = buying; selling (skinslink) comes
later.

**The design is the spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md`. Every
decision in it was approved by the owner in conversation. Do not re-litigate them; ask only
about what the spec leaves open (§17).

## Handoff — where we are

- **Done:** brainstorming (architectural path), design approved section by section, spec
  written and committed (this commit).
- **Next:** the owner reviews the written spec. When they say it is fine, invoke the
  `superpowers:writing-plans` skill for **milestone M0** (spec §15) and save the plan to
  `docs/superpowers/plans/2026-MM-DD-m0-skeleton.md`. Then execute it (owner picks the
  execution method). Milestones M1–M5 each get their own plan.
- No code exists yet beyond this file and the spec. The repo is a fresh `git init`, no remote.
  The owner creates the GitHub repo (`jamaomonov/csmarket`) and says when to push.

## YuPay access

The source material lives in **`/Users/macbook_uz/Projects/yupay`**. You may **read** it
freely — code, docs, ADRs, specs, plans, and its memory notes at
`/Users/macbook_uz/.claude/projects/-Users-macbook-uz-Projects-yupay/memory/`. You must
**never write** to that repo: no edits, no commits, no branch changes, no `git` commands that
mutate it, nothing in its `.claude/`. Copy from it into this repo, then adapt here. Spec §18
lists the exact paths worth reading.

Porting is by allow-list (spec §4): bring a module by the list of tables, functions and routes
the plan names; re-declare models with only the columns spec §5 lists; rename everything
(`csmarket`, env prefix `CSMARKET_`); ported tests come along; `scripts/check-no-yupay.sh`
in CI fails on `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`,
`merchant_api`, `voucher`, `game_id` in source.

## Stack (same as YuPay)

Python 3.12 + FastAPI + SQLAlchemy 2 async + Alembic + Pydantic v2 + `uv`; PostgreSQL 16, Redis 7;
Postgres-native queue (FOR UPDATE SKIP LOCKED + LISTEN/NOTIFY) drained by `apps/worker`;
APScheduler in `apps/scheduler`; Next.js 15 App Router + TS strict + Tailwind v4 + shadcn/ui +
next-intl v4 (`apps/web`); Vite 5 + React 19 + React Router 7 SPA (`apps/admin`);
`@hey-api/openapi-ts` client; pnpm workspaces + Turborepo + uv workspace + Makefile; Caddy 2;
Prometheus/Grafana/Loki/Promtail; Sentry; sops + age; GitHub Actions → GHCR → SSH deploy.
Coding standards, commit conventions (Conventional Commits, scope = app/module), test rules
(TDD, ≥ 95 % on money modules) and doc rules are YuPay's `AGENTS.md` §6–§14 until M0 writes
this repo's own copy.

## Owner rules (durable — learned over months on YuPay)

- **Reply in Russian, tersely.** Lead with the answer; no preamble; the owner reads on a phone
  and acts on the conclusion.
- **Commit locally; NEVER push or deploy without an explicit command in that message.** Batch
  pushes (GitHub Actions minutes). Before any push run `npx prettier --check .`.
- The owner usually says «тесты локально не гоняй» when ordering a deploy — CI runs them.
  Otherwise `make lint typecheck test` before calling work done.
- **Prod restarts always with `IMAGE_TAG`** — a plain `docker compose up -d` rolls back to a
  stale `:main` image silently.
- **Kill processes by PID only.** Never `pkill -f <pattern>` (it once killed Docker Desktop).
- On servers, never touch anything that can drop or delete data without asking.
- **Never log PII**: Steam ID, email, IP, trade-link token. Never print a real trade-link token
  in chat, docs or tests — use redrawn/fake ones.
- **Copy:** short sentences; outcome, not mechanism; no service meta («цены обновляются каждые
  5 минут»); no refund/supplier internals for customers; concrete over abstract («в
  Узбекистане»); «вы», not «ты»; never claim «всегда дешевле» — date any price comparison.
- **UI:** cleaner AND clearer; inline «где найти?» hints instead of raw forms.
- **Never invent business logic**; ask when two valid approaches differ materially.
- Don't create summary/report files unless asked; notes go in the PR description.
- Keys pasted in chat are never stored in the repo or in files; tell the owner to rotate them.

## Skills

Use the superpowers skills as YuPay does: `brainstorming` for anything new,
`writing-plans` → `executing-plans` / `subagent-driven-development` per milestone,
`test-driven-development` on every task, `systematic-debugging` for bugs,
`verification-before-completion` before claiming done.
