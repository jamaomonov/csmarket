# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS base
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
    pnpm install --frozen-lockfile=false

FROM base AS builder
COPY --from=deps /app /app
COPY . .
# Next.js inlines NEXT_PUBLIC_* into the client bundle at build time, so these
# must be present here (not just at runtime). CI passes them as build-args.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN pnpm --filter @csmarket/web build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN npm i -g corepack@latest && corepack enable && corepack prepare pnpm@9.12.0 --activate
COPY --from=builder /app /app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost:3000/ || exit 1
CMD ["pnpm", "--filter", "@csmarket/web", "start"]
