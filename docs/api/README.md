# API

`openapi.json` is generated — never hand-edit. Regenerate with `make gen-api`; CI's
`openapi-drift` job fails when the committed file differs from the app.

- Base path: `https://api.csmarket.uz/api/v1`. Probes: `/healthz` (liveness), `/readyz`
  (readiness: Postgres + Redis, 503 when either fails). `/metrics` is scraped on the
  internal network and answers 404 from the public host.
- Errors: RFC 7807 `application/problem+json` with `type` under `https://csmarket.uz/errors/`;
  429s carry `Retry-After`.
- Every state-changing endpoint accepts `Idempotency-Key` (≥ 16 chars) — spec §13.
- Auth (M1): Steam OpenID → HttpOnly cookies, 15-min EdDSA access, 30-day rotating refresh.
