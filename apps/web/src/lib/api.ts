import { createSessionClient } from "@csmarket/api-client";

/** Public API origin; inlined at build (NEXT_PUBLIC_*). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8100").replace(
  /\/$/,
  "",
);

/** One browser session client for the storefront (access token in memory, ruling P2). */
export const session = createSessionClient({
  baseUrl: API_BASE,
  hintKey: "csmarket.web.has_session",
  lockName: "csmarket-web-token-refresh",
});
