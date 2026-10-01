# csmarket.uz

> CS2 skins for Uzbekistan: browse, pay in soʻm (Click / Payme / Uzum or balance), receive the
> skin as a Steam trade offer. Storefront + admin + FastAPI backend in one repo.

## Read this first

- **[AGENTS.md](./AGENTS.md)** — the rulebook and the Definition of Done. Mandatory.
- **[docs/superpowers/specs/2026-10-01-csmarket-design.md](./docs/superpowers/specs/2026-10-01-csmarket-design.md)** — the approved design.
- **[docs/onboarding/local-setup.md](./docs/onboarding/local-setup.md)** — local stack.

## Stack

| Area     | Choice                                                                                |
| -------- | ------------------------------------------------------------------------------------- |
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, uv                  |
| Queue    | Postgres-native (`FOR UPDATE SKIP LOCKED` + `LISTEN/NOTIFY`) drained by `apps/worker` |
| Frontend | Next.js 15 (App Router), TypeScript strict, Tailwind v4, next-intl (ru / uz / en)     |
| Admin    | Vite 5 + React 19 + React Router 7 SPA                                                |
| Data     | PostgreSQL 16, Redis 7                                                                |
| Infra    | Docker Compose, Caddy 2, Prometheus + Grafana + Loki, Sentry                          |
| CI/CD    | GitHub Actions → GHCR → SSH deploy                                                    |

## Common commands

```bash
make bootstrap   # deps + pre-commit + api client
make dev         # full stack via docker compose
make test        # Python + TS
make lint        # ruff + eslint + prettier + check-no-yupay
make typecheck   # mypy + tsc
make gen-api     # openapi.json + TS client
make migrate     # alembic upgrade head
```
