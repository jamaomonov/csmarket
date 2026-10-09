import { expect, test } from "@playwright/test";

test("the root is the SEO landing with live skins", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("в Узбекистане");
  await expect(page.locator('a[href^="/item/"]').first()).toBeVisible();
  const ld = await page.locator('script[type="application/ld+json"]').allTextContents();
  const types = ld.map((t) => (JSON.parse(t) as { "@type": string })["@type"]);
  expect(types).toEqual(expect.arrayContaining(["FAQPage", "Organization", "WebSite"]));
});

test("the landing search opens the market with the query", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("search").getByRole("searchbox").fill("redline");
  await page.getByRole("search").getByRole("button").click();
  await expect(page).toHaveURL(/\/market\?q=redline/, { timeout: 30_000 });
});

test("an old filtered root URL lands on the market", async ({ page }) => {
  await page.goto("/?category=knives");
  await expect(page).toHaveURL(/\/market\?category=knives/);
});

test("the Uzbek landing is in Uzbek", async ({ page }) => {
  await page.goto("/uz");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Oʻzbekistonda");
});

test("no horizontal overflow at 390 on the landing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
