# @csmarket/admin

Backoffice SPA — React 19 + Vite + TypeScript. Not Next.js by design: SEO is
irrelevant, hydration cost is wasted, and a plain SPA keeps the deploy/CDN story tiny.

## Stack

- **Vite 5** (build), **React 19** (UI), **TypeScript strict**.
- **React Router v7** data API (routing + loaders + actions).
- **TanStack Query v5** (server state, caching, optimistic updates).
- **Tailwind v4** + `@csmarket/ui` (shared design system).
- **Zustand** (auth slice; the rest of state lives in TanStack Query).

## Auth

Same Steam sign-in as the storefront with a `return_to` on this host; `/admin/*` requires the `admin` role on a named `steam_id` (M1).

## Running locally

```bash
make dev                # full stack
# then open
open http://localhost:3102
```

Vite dev server proxies `/api/*` to the backend on `:8100` (`VITE_DEV_API_TARGET` overrides).

## Routes

| Path            | What                                                            |
| --------------- | --------------------------------------------------------------- |
| `/`             | Dashboard (placeholder)                                         |
| `/catalogue`    | Catalogue status, hide/show items, search aliases               |
| `/users`        | Users: search by name or Steam ID                               |
| `/users/:id`    | User card: profile, balance, history, top-ups; ban, adjust      |
| `/payments`     | Payments: search by number, filters; `?q=` pre-fills the search |
| `/payments/:id` | Payment: fields, top-up, kassa transactions (read-only)         |
| `/audit`        | Audit log: filters by action, target type, target id            |
| `*`             | 404                                                             |
