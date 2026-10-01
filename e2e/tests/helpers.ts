import type { Page } from "@playwright/test";

export const API = process.env.API_BASE_URL ?? "http://localhost:8100";

/**
 * Dev-only sign-in (ruling P6). Sets the refresh cookie in the browser context and
 * the apps' session hints — without a hint the apps skip the boot-time refresh, the
 * way a real Steam sign-in would have set it.
 */
export async function devLogin(
  page: Page,
  opts: { steamId: string; name?: string; admin?: boolean },
): Promise<void> {
  const r = await page.context().request.post(`${API}/api/v1/auth/dev-login`, {
    data: { steam_id: opts.steamId, display_name: opts.name ?? null, admin: opts.admin ?? false },
  });
  if (!r.ok()) throw new Error(`dev-login ${r.status().toString()}`);
  await page.addInitScript(() => {
    localStorage.setItem("csmarket.web.has_session", "1");
    localStorage.setItem("csmarket.admin.has_session", "1");
  });
}

/** steamid64 → a matching fake trade link (redrawn token, never a real one). */
export function tradeLinkFor(steamId: string, token = "E2eTok12"): string {
  const partner = (BigInt(steamId) - 76561197960265728n).toString();
  return `https://steamcommunity.com/tradeoffer/new/?partner=${partner}&token=${token}`;
}

/**
 * A fresh steamid64 per call: a 10-digit prefix of the spec's own (so files never share an
 * account) and 7 random digits (so parallel tests and repeated runs don't either).
 */
export function uniqueSteamId(prefix: string): string {
  const tail = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return `${prefix}${tail}`;
}
