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
    pnpm install --frozen-lockfile

FROM base AS builder
# Vite reads VITE_* env at build time and inlines them into the bundle. Pass them as
# build args from docker-compose so a rebuild picks up .env changes.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
COPY --from=deps /app /app
COPY . .
# Source maps stay in the builder stage: nginx would serve any .map in dist to
# whoever appends ".map" to a public bundle name.
RUN pnpm --filter @csmarket/admin build \
 && find apps/admin/dist -name '*.map' -delete

FROM nginx:alpine AS runner
COPY --from=builder /app/apps/admin/dist /usr/share/nginx/html
COPY infra/docker/admin-nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
