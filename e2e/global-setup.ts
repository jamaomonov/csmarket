/**
 * Warm the dev servers once, one route at a time. `next dev` and Vite compile a route on
 * its first request; with four workers and three projects opening cold routes together,
 * the first `page.goto` calls queue behind the compiler and time out. A failed warm-up is
 * not an error here: the specs report what is really broken.
 */
const WEB = process.env.WEB_BASE_URL ?? "http://localhost:3100";
const ADMIN = process.env.ADMIN_BASE_URL ?? "http://localhost:3102";

const WEB_ROUTES = [
  "/",
  "/uz",
  "/en",
  "/?category=knives",
  "/category/knives",
  "/weapon/ak-47",
  "/item/ak-47-redline-field-tested",
  "/item/warm-up-404",
  "/account",
  "/en/account",
  "/sitemap.xml",
  "/skins-sitemap/0.xml",
  "/skins-sitemap/landings.xml",
  "/robots.txt",
  "/warm-up-404",
];
const ADMIN_ROUTES = ["/", "/catalogue"];

async function warm(origin: string, path: string): Promise<void> {
  try {
    await fetch(origin + path, { signal: AbortSignal.timeout(120_000) });
  } catch {
    // see the file comment
  }
}

export default async function globalSetup(): Promise<void> {
  for (const path of WEB_ROUTES) await warm(WEB, path);
  for (const path of ADMIN_ROUTES) await warm(ADMIN, path);
}
