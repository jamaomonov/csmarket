import { fileURLToPath } from "node:url";

import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The image ships `.next/standalone` (a traced server and only the modules it needs) and
  // runs it as `node`, not the whole workspace as root (review 2026-10-20). The root is
  // the monorepo, so the workspace packages are traced too.
  output: "standalone",
  outputFileTracingRoot: fileURLToPath(new URL("../..", import.meta.url)),
  // Metadata before the first byte for every client, not only Next's list of "HTML-limited"
  // bots: with streamed metadata a `notFound()` in `generateMetadata` arrives after the 200
  // has gone out, and Googlebot sees a soft 404 (a 200 around «Страница не найдена»). Item,
  // category and weapon pages check existence in `generateMetadata`; a real 404 needs this.
  htmlLimitedBots: /.*/,
  typedRoutes: true,
  // Lint runs via `make lint` / CI; a Docker build must not conflate the two.
  eslint: { ignoreDuringBuilds: true },
  images: {
    // Steam image URLs are content-addressed: a cached copy never goes stale.
    minimumCacheTTL: 2_592_000,
    remotePatterns: [
      { protocol: "https", hostname: "**.csmarket.uz" },
      // Steam CDN skin images (M2) — host rewritten to one reachable from Uzbekistan.
      { protocol: "https", hostname: "community.fastly.steamstatic.com" },
      // Sticker and charm icons by game path are served by Steam's cdn.* hosts only.
      { protocol: "https", hostname: "cdn.fastly.steamstatic.com", pathname: "/apps/730/icons/**" },
      { protocol: "https", hostname: "avatars.steamstatic.com" },
    ],
  },
  transpilePackages: ["@csmarket/ui", "@csmarket/api-client", "@csmarket/i18n", "@csmarket/utils"],
};

export default withNextIntl(nextConfig);
