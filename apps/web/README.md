# @csmarket/web — public storefront

Next.js 15 (App Router, RSC). M0 ships a hello page in three languages; the catalogue arrives in M2.

- Locale routing: `/[locale]/...` with `localePrefix: "as-needed"` (`ru` is bare, `en`/`uz`
  are prefixed). No browser-language redirect and no locale cookie: a URL means one language.
- Server Components by default; `"use client"` only when necessary.
- API client: `@csmarket/api-client` (generated from FastAPI's OpenAPI 3.1 schema).
- Design system: `@csmarket/ui` + `@csmarket/config-tailwind`.

```bash
make dev-web   # foreground, requires the API to be reachable
```

## Environment

| Variable                   | Description                                                                              |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | Base URL of the FastAPI backend (e.g. `https://api.csmarket.uz`). Inlined at build time. |
| `API_INTERNAL_URL`         | Server-to-server API URL used by Server Components (in compose: `http://api:8000`).      |
