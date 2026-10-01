import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("anonymous goes to the Steam login page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
    "href",
    /\/api\/v1\/auth\/steam\/start\?app=admin&locale=ru$/,
  );
});

test("a customer is refused", async ({ page }) => {
  await devLogin(page, { steamId: "76561198000000880" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Нет доступа" })).toBeVisible();
});

test("an admin gets in", async ({ page }) => {
  await devLogin(page, { steamId: "76561198000000881", name: "Owner", admin: true });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Дашборд" })).toBeVisible();
  await expect(page.getByText("Owner")).toBeVisible();
});
