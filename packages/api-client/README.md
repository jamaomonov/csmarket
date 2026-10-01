# @csmarket/api-client

Typed HTTP client for the csmarket backend. The HTTP layer is **generated** from
`docs/api/openapi.json` by `pnpm --filter @csmarket/api-client gen:api` (called by
`make gen-api`); `src/generated/` is gitignored. Consumers: `apps/web`, `apps/admin`.

`createApiClient({ baseUrl, getAuthHeader, getLocale })` returns a thin fetch wrapper that
throws `ApiError` on non-2xx responses.
