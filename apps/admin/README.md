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
open http://localhost:3002
```

Vite dev server proxies `/api/*` to the backend on `:8000` (`VITE_DEV_API_TARGET` overrides).

## Routes

| Path | What                    |
| ---- | ----------------------- |
| `/`  | Dashboard (placeholder) |
| `*`  | 404                     |
