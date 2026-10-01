# e2e

Playwright smoke and journeys. Needs the dev stack up (`make dev`, then `make migrate` and `make seed-skins` — the catalogue specs read the 62 seeded items). Run with `make test-e2e`.

Projects:

- `web-chromium` — storefront (`home`, `auth`, `catalogue` specs) on `WEB_BASE_URL` (default `http://localhost:3100`).
- `web-iphone` — storefront (`home` spec) on an iPhone 14 viewport.
- `admin-chromium` — admin SPA (`admin`, `admin-catalogue` specs) on `ADMIN_BASE_URL` (default `http://localhost:3102`).

Signed-in specs use the dev-only login, `POST {API_BASE_URL}/api/v1/auth/dev-login` (default `http://localhost:8100`). It exists only while `CSMARKET_DEV_LOGIN_ENABLED=true` and the environment is not prod; the dev compose enables it by default. `tests/helpers.ts` calls it and sets the apps' session hints in `localStorage`. Trade links in specs are fake (redrawn tokens).
