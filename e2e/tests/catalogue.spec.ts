import { expect, test } from "@playwright/test";

import { API } from "./helpers";

const CARDS = 'a[href^="/item/"]';

test("the home page is the catalogue, in soʻm", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Скины КС2 (CS2)");
  const cards = page.locator(CARDS);
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(10);
  await expect(page.getByText(/сум/).first()).toBeVisible();
});

test("a category filter narrows the grid and is noindex", async ({ page }) => {
  await page.goto("/?category=knives");
  const cards = page.locator(CARDS);
  await expect(cards.first()).toBeVisible();
  const names = await cards.allInnerTexts();
  expect(names.length).toBeGreaterThan(0);
  expect(names.length).toBeLessThan(10);
  expect(names.every((n) => /Karambit|Butterfly Knife/.test(n))).toBe(true);
  // The card's image alt carries the full market name, which starts with ★ for a knife.
  const alts = await cards
    .locator("img")
    .evaluateAll((imgs) => imgs.map((i) => i.getAttribute("alt")));
  expect(alts.every((a) => a?.startsWith("★"))).toBe(true);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});

test("tracking params keep the home page indexable", async ({ page }) => {
  await page.goto("/?utm_source=telegram");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /^index/);
});

test("search suggests and opens an item", async ({ page }) => {
  await page.goto("/");
  const search = page.getByRole("search");
  const suggestion = search.getByRole("link", { name: /Redline/ }).first();
  // A fill before hydration never reaches React's onChange; retry until the dropdown opens.
  await expect(async () => {
    await search.getByPlaceholder("Название скина…").fill("");
    await search.getByPlaceholder("Название скина…").fill("redline");
    await expect(suggestion).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 30_000 });
  await suggestion.click();
  // The first visit to /item compiles the route in `next dev`.
  await expect(page).toHaveURL(/\/item\/(stattrak-)?ak-47-redline/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Redline");
});

test("item page: wears, offers from the snapshot, JSON-LD, no buy button", async ({ page }) => {
  await page.goto("/item/ak-47-redline-field-tested");
  // The H1 is the skin name; the weapon sits in the line above it.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Redline");
  await expect(page.getByText("AK-47").first()).toBeVisible();
  await expect(page.locator('script[type="application/ld+json"]').first()).toBeAttached();
  const ld = await page.locator('script[type="application/ld+json"]').allTextContents();
  expect(
    ld.some((s) => s.includes('"@type":"Product"') && s.includes('"priceCurrency":"UZS"')),
  ).toBe(true);
  expect(ld.some((s) => s.includes('"@type":"BreadcrumbList"'))).toBe(true);
  expect(ld.some((s) => s.includes('"@type":"FAQPage"'))).toBe(true);
  await expect(page.getByRole("button", { name: /Купить|Buy/ })).toHaveCount(0);
});

for (const path of [
  "/item/no-such-skin-xyz",
  "/category/no-such",
  "/weapon/no-such",
  "/en/item/no-such-skin-xyz",
]) {
  test(`real 404 for ${path}`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(404);
  });
}

test("landings render and link items", async ({ page }) => {
  await page.goto("/category/knives");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ножи КС2 (CS2)");
  await page.goto("/weapon/ak-47");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Скины AK-47 КС2 (CS2)");
  await expect(page.locator('a[href^="/item/ak-47-"]').first()).toBeVisible();
});

test("sitemaps: index → chunk → item URLs with alternates", async ({ request }) => {
  const index = await (await request.get("/sitemap.xml")).text();
  expect(index).toContain("<sitemapindex");
  expect(index).toContain("/skins-sitemap/0.xml");
  expect(index).toContain("/skins-sitemap/landings.xml");
  const chunk = await (await request.get("/skins-sitemap/0.xml")).text();
  expect(chunk).toContain("https://csmarket.uz/item/");
  expect(chunk).toContain('hreflang="x-default"');
  const landings = await request.get("/skins-sitemap/landings.xml");
  expect(landings.status()).toBe(200);
  expect((await request.get("/skins-sitemap/99.xml")).status()).toBe(404);
});

test("the API answers soʻm and dollars", async ({ request }) => {
  const body = (await (await request.get(`${API}/api/v1/skins/catalog?limit=1`)).json()) as {
    items: { price_usd: string; price_uzs: string }[];
  };
  const item = body.items[0];
  expect(item?.price_usd).toMatch(/^\d+\.\d{2}$/);
  expect(item?.price_uzs).toMatch(/^\d+00$/);
});
