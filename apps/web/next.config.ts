import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Lint runs via `make lint` / CI; a Docker build must not conflate the two.
  eslint: { ignoreDuringBuilds: true },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.csmarket.uz" },
      // Steam CDN skin images (M2) — host rewritten to one reachable from Uzbekistan.
      { protocol: "https", hostname: "community.fastly.steamstatic.com" },
      { protocol: "https", hostname: "avatars.steamstatic.com" },
    ],
  },
  transpilePackages: ["@csmarket/ui", "@csmarket/api-client", "@csmarket/i18n", "@csmarket/utils"],
};

export default withNextIntl(nextConfig);
