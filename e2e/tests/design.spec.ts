import { expect, test } from "@playwright/test";

test("catalogue: chips with a model menu, cards in the new style", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Скины КС2 (CS2)");
  const rifles = page.getByRole("button", { name: "Модели: Винтовки" });
  await rifles.click();
  const ak = page.getByRole("menuitem", { name: /AK-47/ });
  await expect(ak).toBeVisible();
  await ak.click();
  await expect(page).toHaveURL(/category=rifles/);
  await expect(page).toHaveURL(/weapon=AK-47/);
  await expect(page.getByRole("link", { name: /Винтовки · AK-47/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("language switch keeps the page and the filters", async ({ page, isMobile }) => {
  test.skip(isMobile, "desktop switcher");
  await page.goto("/?category=knives");
  await page.getByRole("button", { name: /Язык/ }).click();
  await page.getByRole("menuitem", { name: "English" }).click();
  await expect(page).toHaveURL(/\/en\/?\?category=knives/);
});

test("no horizontal overflow at 390", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await expect(page.getByRole("button", { name: "Меню" })).toBeVisible();
});

test("the catalogue hydrates without a mismatch", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(errors.filter((e) => /hydrat/i.test(e))).toEqual([]);
});
