import { expect, type APIRequestContext, type Page } from "@playwright/test";

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

function auth(token: string, keyed = false): Record<string, string> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (keyed) headers["Idempotency-Key"] = `e2e-${crypto.randomUUID()}`;
  return headers;
}

/**
 * Dev-only sign-in on an API context alone; returns the access token for the helpers below.
 * Call it on the test's `request` fixture, never on the page's context: this opens a
 * session of its own, so the page refreshing (rotating) its session never kills the token.
 */
export async function apiLogin(
  request: APIRequestContext,
  steamId: string,
  name?: string,
): Promise<string> {
  const r = await request.post(`${API}/api/v1/auth/dev-login`, {
    data: { steam_id: steamId, display_name: name ?? null, admin: false },
  });
  expect(r.status(), "dev-login").toBe(200);
  // Known-shape JSON from our own dev-login (`TokensOut`).
  const { access_token: token } = (await r.json()) as { access_token: string };
  return token;
}

/** Save the account's own (fake) trade link through the API; nothing upstream is called. */
export async function saveTradeLink(
  request: APIRequestContext,
  token: string,
  steamId: string,
): Promise<void> {
  const r = await request.put(`${API}/api/v1/me/trade-link`, {
    headers: auth(token, true),
    data: { url: tradeLinkFor(steamId) },
  });
  expect(r.status(), "save trade link").toBe(200);
}

/**
 * Top the balance up through the test kassa (`mock`) and pay it with the dev-only
 * `POST /dev/topups/{number}/pay`. One `topup-create` hit — that bucket is ip_guard-limited.
 * Returns the top-up's number.
 */
export async function topUp(
  request: APIRequestContext,
  token: string,
  amountUzs: number,
): Promise<string> {
  const created = await request.post(`${API}/api/v1/wallet/topups`, {
    headers: auth(token, true),
    data: { amount_uzs: amountUzs, provider: "mock", locale: "ru" },
  });
  expect(created.status(), "open top-up").toBe(201);
  // Known-shape JSON from our own API (`TopupOut`).
  const { number } = (await created.json()) as { number: string };
  const paid = await request.post(`${API}/api/v1/dev/topups/${number}/pay`, {
    headers: auth(token),
  });
  expect(paid.status(), "pay top-up").toBe(200);
  return number;
}

export type DevTradeAction = "accept" | "decline" | "rollback";

/**
 * Move the order's trade at the dev Waxpeer fake. The order itself follows on the next
 * reconcile tick (every 10 s), as it would with Waxpeer.
 */
export async function devTrade(
  request: APIRequestContext,
  token: string,
  number: string,
  action: DevTradeAction,
): Promise<void> {
  const r = await request.post(`${API}/api/v1/dev/orders/${number}/trade`, {
    headers: auth(token),
    data: { action },
  });
  expect(r.status(), `dev trade ${action}`).toBe(200);
}

/** The account's order status, through the API. */
async function orderStatus(
  request: APIRequestContext,
  token: string,
  number: string,
): Promise<string> {
  const r = await request.get(`${API}/api/v1/orders/${number}`, { headers: auth(token) });
  expect(r.status(), "read order").toBe(200);
  // Known-shape JSON from our own API (`OrderOut`).
  const { status } = (await r.json()) as { status: string };
  return status;
}

/**
 * Wait until the order reaches `status`. The fake sends the offer ~6 s after the buy and
 * the reconcile sweep reads it every 10 s, so a step takes up to ~20 s.
 */
export async function waitForOrder(
  request: APIRequestContext,
  token: string,
  number: string,
  status: string,
): Promise<void> {
  await expect
    .poll(() => orderStatus(request, token, number), {
      timeout: 60_000,
      intervals: [1_000, 2_000],
    })
    .toBe(status);
}

/** A seeded item's cheapest offer at our price (the snapshot under the fake). */
export async function cheapestOffer(
  request: APIRequestContext,
  slug: string,
): Promise<{ listingId: number; priceUzs: number }> {
  const r = await request.get(`${API}/api/v1/skins/${slug}/listings`);
  expect(r.status(), "listings").toBe(200);
  // Known-shape JSON from our own API (`SkinListingsOut`).
  const { items } = (await r.json()) as {
    items: { listing_id: number; price_uzs: string | null }[];
  };
  const priced = items.flatMap((i) =>
    i.price_uzs === null ? [] : [{ listingId: i.listing_id, priceUzs: Number(i.price_uzs) }],
  );
  const best = priced.sort((a, b) => a.priceUzs - b.priceUzs)[0];
  if (best === undefined) throw new Error(`no priced offer for ${slug}`);
  return best;
}

/**
 * Open an order for a seeded item's cheapest offer and pay it through the test kassa with
 * the dev-only `POST /dev/orders/{number}/pay` (one `order-create` hit, no top-up, no
 * `order-pay`). Returns the order's number.
 */
export async function buyThroughTestKassa(
  request: APIRequestContext,
  token: string,
  slug: string,
): Promise<string> {
  const offer = await cheapestOffer(request, slug);
  const created = await request.post(`${API}/api/v1/orders`, {
    headers: auth(token, true),
    data: { slug, listing_id: offer.listingId, price_uzs: offer.priceUzs },
  });
  expect(created.status(), "create order").toBe(201);
  // Known-shape JSON from our own API (`OrderOut`).
  const { number } = (await created.json()) as { number: string };
  const paid = await request.post(`${API}/api/v1/dev/orders/${number}/pay`, {
    headers: auth(token),
  });
  expect(paid.status(), "pay order").toBe(200);
  return number;
}
