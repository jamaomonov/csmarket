# syntax=mirror.gcr.io/docker/dockerfile:1.7
FROM mirror.gcr.io/library/node:22-alpine AS base
RUN npm i -g corepack@latest && corepack enable && corepack prepare pnpm@9.12.0 --activate
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/api-client/package.json packages/api-client/package.json
COPY packages/i18n/package.json packages/i18n/package.json
COPY packages/utils/package.json packages/utils/package.json
COPY packages/config-eslint/package.json packages/config-eslint/package.json
COPY packages/config-tsconfig/package.json packages/config-tsconfig/package.json
COPY packages/config-tailwind/package.json packages/config-tailwind/package.json
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

FROM base AS builder
COPY --from=deps /app /app
COPY . .
# Next.js inlines NEXT_PUBLIC_* into the client bundle at build time, so these
# must be present here (not just at runtime). CI passes them as build-args.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8100
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN pnpm --filter @csmarket/web build

# Only Next's traced standalone server, its static files and the OG assets it reads from
# disk, run as the image's unprivileged `node` user — no source, no dev dependencies, no
# package manager (review 2026-10-20).
FROM mirror.gcr.io/library/node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
COPY --from=builder --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=node:node /app/apps/web/public ./apps/web/public
# `og-assets.ts` reads fonts and images from process.cwd(), which server.js sets to its dir.
COPY --from=builder --chown=node:node /app/apps/web/assets ./apps/web/assets
USER node
EXPOSE 3000
# 127.0.0.1, not localhost: busybox resolves localhost to ::1 and the server listens on IPv4.
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:3000/ || exit 1
CMD ["node", "apps/web/server.js"]
