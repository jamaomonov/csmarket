# e2e

Playwright smoke and journeys. Needs the dev stack up (`make dev`, then `make migrate` and `make seed-skins` — the catalogue specs read the 62 seeded items). Run with `make test-e2e`.

Projects:

- `web-chromium` — storefront (`home`, `auth`, `catalogue`, `balance`, `buy` specs) on `WEB_BASE_URL` (default `http://localhost:3100`).
- `web-iphone` — storefront (`home` spec) on an iPhone 14 viewport.
- `admin-chromium` — admin SPA (`admin`, `admin-catalogue`, `admin-money`, `admin-orders` specs) on `ADMIN_BASE_URL` (default `http://localhost:3102`).

Signed-in specs use the dev-only login, `POST {API_BASE_URL}/api/v1/auth/dev-login` (default `http://localhost:8100`). It exists only while `CSMARKET_DEV_LOGIN_ENABLED=true` and the environment is not prod; the dev compose enables it by default. `tests/helpers.ts` calls it and sets the apps' session hints in `localStorage`. Trade links in specs are fake (redrawn tokens).

Money specs (M3):

- `balance` tops up through the test kassa (provider `mock`, offered only outside prod) and pays with the dev-only `POST /api/v1/dev/topups/{number}/pay`, which also needs the dev login enabled. No real kassa is called.
- `admin-money` credits a customer, is refused a clawback below zero, bans the customer and reads both actions back from the audit log, filtered by the customer's id (the log is shared by parallel specs).
- Every money spec signs in fresh accounts from `uniqueSteamId(prefix)`, so balances, bans and the audit rows a spec reads are its own. Each spec file has its own 10-digit prefix.
- Opening a top-up is rate-limited (`ip_guard` bucket `topup-create`: 60 a minute per IP, 10 per IP and account). `balance` opens two; keep new specs well under the per-IP ceiling, since every worker shares one address.

Order specs (M4a) need the dev Waxpeer fake (`CSMARKET_WAXPEER_FAKE`, on by default in the dev compose) and buying switched on (`CSMARKET_SKINS_BUY_ENABLED`, set by the dev compose). Nothing is bought for real: the fake "sends" the offer ~6 s after the buy, and the dev-only `POST /api/v1/dev/orders/{number}/trade {action}` accepts or declines it.

- `buy` buys from the balance (top-up through the test kassa first) → offer sent → accepted → «Получено» and a «Покупка» entry; buys through the test kassa with an empty balance → `buying`; and a declined offer → «Возврат на баланс», the balance back where it was.
- `admin-orders` has a customer buy through the API (test kassa, accepted at the fake), then an admin finds the order by number on «Заказы», sees its trade (Waxpeer status 4, Steam offer link) and finds it under «Обмены».
- The order page moves when the scheduler's reconcile sweep reads the fake (every 10 s, **first run ~4 min after the scheduler starts**). Start the suite at least 4 minutes after `make dev`, or the first steps wait out their 60 s timeouts.
- `order-create` and `order-pay` are rate-limited like `topup-create` (60 a minute per IP, 10 per IP and account). A run opens four orders and four top-ups in all.
- The trade-link check passes every link under the fake (`auth` expects «Ссылка работает»); without the fake it would say the check is unavailable.
