import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("an admin hides an item and the storefront 404s it, then shows it again", async ({
  page,
  request,
}) => {
  await devLogin(page, { steamId: "76561198000000882", name: "Owner", admin: true });
  await page.goto("/catalogue");
  await expect(page.getByRole("heading", { level: 1, name: "Каталог" })).toBeVisible();
  await page.getByLabel("Найти скин").fill("redline field-tested");
  // The items are a list; anchored so the StatTrak™ twin does not match.
  const row = page.getByRole("listitem").filter({ hasText: /^AK-47 \| Redline \(Field-Tested\)/ });
  await row.getByRole("button", { name: "Скрыть" }).click();
  await expect(row.getByRole("button", { name: "Показать" })).toBeVisible();

  const web = process.env.WEB_BASE_URL ?? "http://localhost:3100";
  expect((await request.get(`${web}/item/ak-47-redline-field-tested`)).status()).toBe(404);

  await row.getByRole("button", { name: "Показать" }).click();
  await expect(row.getByRole("button", { name: "Скрыть" })).toBeVisible();
  expect((await request.get(`${web}/item/ak-47-redline-field-tested`)).status()).toBe(200);
});
