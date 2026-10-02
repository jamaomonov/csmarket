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

## A catalogue to browse

The Waxpeer key works only from the production IP, so a fresh dev database has no priced
items. `make seed-skins` fills it with about 60 items (a committed ByMykel subset with
fake, repeatable prices and a 12 700 soʻm rate) so every storefront page has data:

```bash
make dev-detached && make migrate && make seed-skins
```

Then open <http://localhost:3100/>. Run it again any time; it refuses to run in production.
It treats the fake snapshot as the whole market, so use it on a dev database only.

## Running one app on the host

Useful for a debugger or faster reloads. Stop that service in compose first
(`docker compose stop api`), keep Postgres and Redis up.

- **API** — `make dev-api` serves on `:8100` from `apps/api` and reads `apps/api/.env`.
  Copy it from `apps/api/.env.example`, which already points at the compose ports:
  `CSMARKET_DATABASE_URL=postgresql+asyncpg://csmarket_app:csmarket_app@localhost:5442/csmarket`,
  `CSMARKET_REDIS_URL=redis://localhost:6390/0`.
- **Worker / scheduler** — `make dev-worker`, `make dev-scheduler`; same `CSMARKET_*`
  variables, exported in the shell.
- **Storefront** — `make dev-web` runs `next dev` on `:3100` (stop compose `web` first). `apps/web/.env.example` holds
  `NEXT_PUBLIC_API_BASE_URL=http://localhost:8100`; copy it to `apps/web/.env.local`.
- **Admin** — `make dev-admin` runs Vite on `:3102` (stop compose `admin` first) and proxies
  `/api/*` to `http://localhost:8100` (`VITE_DEV_API_TARGET` overrides). Leave
  `VITE_API_BASE_URL` empty (as in `apps/admin/.env.example`) so requests go through that
  proxy.

## Signing in locally

Steam is the only sign-in, and **real Steam works on localhost**: `GET /api/v1/auth/steam/start`
sends you to steamcommunity.com and back to `http://localhost:3100/auth/steam/callback`. No
key is needed to sign in. Without `CSMARKET_STEAM_API_KEY` your display name and avatar stay
empty, and the trade-link hold check is skipped (the verdict comes from Waxpeer alone, and
without `CSMARKET_WAXPEER_API_KEY` the check answers "unavailable"; the link is still saved).

**Dev login** skips Steam. It is on in dev (`CSMARKET_DEV_LOGIN_ENABLED=true` in
`.env.example`) and always 404 in prod:

```bash
curl -s -c /tmp/cs.jar -X POST http://localhost:8100/api/v1/auth/dev-login \
  -H 'Content-Type: application/json' \
  -d '{"steam_id": "76561198000000001", "display_name": "Dev", "admin": true}'
```

It returns an access token and sets the `csmarket_refresh` cookie in the jar. For a browser
session, the Playwright helper `e2e/tests/helpers.ts` does the same. The ID must be a valid
SteamID64 (17 digits); use a made-up one, never a real person's.

**Becoming admin.** Sign in once (Steam or dev login), then:

```bash
docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 76561198000000001
```

It prints `granted`; reload `http://localhost:3102`. Or pass `"admin": true` to dev login.

JWT keys: leave `CSMARKET_JWT_PRIVATE_KEY` / `CSMARKET_JWT_PUBLIC_KEY` empty in dev. The API
makes an Ed25519 pair in memory, so access tokens die on an API restart; the refresh cookie
survives and the app re-mints one on the next load.

## Buying locally (the Waxpeer fake)

The dev compose runs the API, worker and scheduler with `CSMARKET_WAXPEER_FAKE=true`: a fake
Waxpeer whose trades live in Redis, so a local buy spends nothing. A paid order is bought at
once; the fake "sends" the offer 6 s later and the reconcile sweep (every 10 s, first run
~24 s after the dev compose's scheduler starts — it divides first runs by 10 with
`CSMARKET_SCHEDULER_FIRST_RUN_DIVISOR`; about 4 min for `make dev-scheduler` unless `.env`
sets it) moves the order to «обмен отправлен». With the fake
on, the trade-link check passes Waxpeer's half for any link. Drive the rest with dev login's
Bearer token:

```bash
# accept | decline | rollback (rollback only after accept)
curl -s -X POST http://localhost:8100/api/v1/dev/orders/<NUMBER>/trade \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"action": "accept"}'
# the fake's Waxpeer balance, in units (1000 = $1); default 10 000 000
curl -s -X POST http://localhost:8100/api/v1/dev/waxpeer/balance \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"units": 25000}'
```

`POST /dev/orders/<NUMBER>/pay` pays an order through the mock kassa first. **With a real
`CSMARKET_WAXPEER_API_KEY` and `CSMARKET_WAXPEER_FAKE=false`, a local buy is a real purchase
with real money.** Prod refuses to start with the fake on.

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
