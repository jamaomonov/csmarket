import { expect, test } from "@playwright/test";

const CASES = [
  { path: "/", lang: "ru", h1: "Скины КС2 (CS2) в Узбекистане" },
  { path: "/uz", lang: "uz-Latn", h1: "Oʻzbekistonda CS2 skinlari" },
  { path: "/en", lang: "en", h1: "CS2 skins in Uzbekistan" },
];

for (const c of CASES) {
  test(`hello page renders in ${c.lang}`, async ({ page }) => {
    await page.goto(c.path);
    await expect(page.locator("html")).toHaveAttribute("lang", c.lang);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(c.h1);
  });
}

test("unknown path is a real 404", async ({ page }) => {
  const response = await page.goto("/nope-" + Date.now().toString());
  expect(response?.status()).toBe(404);
});

test("robots.txt disallows everything before launch", async ({ request }) => {
  const body = await (await request.get("/robots.txt")).text();
  expect(body).toContain("Disallow: /");
});
