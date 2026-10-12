import { expect, test } from "@playwright/test";

test("the footer leads to the documents and each opens", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Документы" })
    .getByRole("link", { name: "Публичная оферта" })
    .click();
  await expect(page).toHaveURL(/\/legal\/terms$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Публичная оферта");
  await page.goto("/en/legal");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Documents");
  await expect(page.getByRole("link", { name: /Seller details/ })).toBeVisible();
});

for (const path of ["/legal/no-such", "/en/legal/no-such"]) {
  test(`real 404 for ${path}`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(404);
  });
}
