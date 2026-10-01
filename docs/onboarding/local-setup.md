# Local setup

## Prerequisites

| Tool              | Version                  | Install hint                                                    |
| ----------------- | ------------------------ | --------------------------------------------------------------- |
| Docker            | 24+                      | <https://docs.docker.com/get-docker/>                           |
| Docker Compose v2 | —                        | bundled with Docker Desktop / the `docker-compose-plugin`       |
| Node              | 22 (`.nvmrc`)            | `nvm install`                                                   |
| pnpm              | 9.12 (pinned)            | `corepack enable` — `make bootstrap` activates the pinned one   |
| Python            | 3.12 (`.python-version`) | `uv python install 3.12` or pyenv                               |
| uv                | latest                   | `curl -LsSf https://astral.sh/uv/install.sh \| sh`              |
| pre-commit        | latest                   | `uv tool install pre-commit`                                    |
| Make, perl        | any                      | preinstalled on macOS and Linux (`check-no-yupay.sh` uses perl) |

Docker is also the only prerequisite for the Python integration tests: they start their own
Postgres and Redis containers.

## First-time bootstrap

```bash
git clone git@github.com:jamaomonov/csmarket.git
cd csmarket
make bootstrap      # pnpm install, uv sync --all-packages --all-groups, pre-commit, API client
cp .env.example .env
```

The root `.env` is read by Docker Compose (ports, Postgres credentials). It is git-ignored.

## Running the stack

```bash
make dev            # foreground; `make dev-detached` for background, `make down` to stop
make migrate        # alembic upgrade head inside the api container
```

csmarket uses its own host-port block, so it can run beside another project's dev stack.
Every port is overridable in `.env`; container ports stay the defaults.

| What        | URL                                                                             | Override                                          |
| ----------- | ------------------------------------------------------------------------------- | ------------------------------------------------- |
| API         | <http://localhost:8100> (`/healthz`, `/readyz`, `/docs`)                        | `CSMARKET_API_PORT`                               |
| Storefront  | <http://localhost:3100>                                                         | `CSMARKET_WEB_PORT`                               |
| Admin       | <http://localhost:3102>                                                         | `CSMARKET_ADMIN_PORT`                             |
| Postgres    | `127.0.0.1:5442` (`make psql`)                                                  | `POSTGRES_PORT`                                   |
| Redis       | `127.0.0.1:6390`                                                                | `REDIS_PORT`                                      |
| Caddy (TLS) | <https://csmarket.localhost:8543>, `api.localhost:8543`, `admin.localhost:8543` | `CSMARKET_CADDY_HTTPS_PORT` (`…_HTTP_PORT`, 8180) |

Caddy's dev certificates come from its own local CA (`tls internal`); the browser warns until
you trust it.

## Running one app on the host

Useful for a debugger or faster reloads. Stop that service in compose first
(`docker compose stop api`), keep Postgres and Redis up.

- **API** — `make dev-api` serves on `:8100` from `apps/api` and reads `apps/api/.env`.
  Create it from `apps/api/.env.example` and point it at the compose ports:
  `CSMARKET_DATABASE_URL=postgresql+asyncpg://csmarket_app:csmarket_app@localhost:5442/csmarket`,
  `CSMARKET_REDIS_URL=redis://localhost:6390/0`.
- **Worker / scheduler** — `make dev-worker`, `make dev-scheduler`; same `CSMARKET_*`
  variables, exported in the shell.
- **Storefront** — `make dev-web` runs `next dev` on `:3000`. `apps/web/.env.example` holds
  `NEXT_PUBLIC_API_BASE_URL=http://localhost:8100`; copy it to `apps/web/.env.local`.
- **Admin** — `make dev-admin` runs Vite on `:5173` and proxies `/api/*` to
  `http://localhost:8100` (`VITE_DEV_API_TARGET` overrides). Leave `VITE_API_BASE_URL` unset
  so requests go through that proxy.

## Common commands

```bash
make lint typecheck test       # what "done" means locally (AGENTS.md § 15)
make test-py                   # pytest -n auto; Docker must be running
make test-ts                   # Vitest across packages and apps
make test-e2e                  # Playwright against the running dev stack
make migration name=add_users  # autogenerate an Alembic revision (dev stack up)
make gen-api                   # openapi.json + TS client after an API change
make logs service=api
make help                      # everything else
```

Playwright needs its browsers once: `pnpm --filter @csmarket/e2e exec playwright install chromium webkit`
(the suite runs a desktop Chrome and an iPhone project). `WEB_BASE_URL` points it elsewhere
than `http://localhost:3100`.

## Editor

VS Code with Python, Pylance, Ruff, ESLint, Prettier and Tailwind CSS IntelliSense.

## Troubleshooting

- **Port already in use** — another stack holds it. Change the port in `.env` rather than
  stopping a container that is not csmarket's.
- **Pre-commit fails on the first commit** — `pre-commit run --all-files` shows every error
  at once.
- **`openapi-drift` fails in CI** — run `make gen-api` and commit the regenerated files.
- **`check-no-yupay` fails** — a YuPay-specific token reached source; rename it, or, if it is
  a third party's own field name, add an allow-list line with a reason (`AGENTS.md` § 6).
