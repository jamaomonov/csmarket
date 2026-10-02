import { expect, test } from "@playwright/test";

import { devLogin, tradeLinkFor } from "./helpers";

test("a visitor sees Steam sign-in pointing at the API", async ({ page }) => {
  await page.goto("/");
  const link = page.getByRole("link", { name: "Войти через Steam" });
  await expect(link).toHaveAttribute("href", /\/api\/v1\/auth\/steam\/start\?app=web&locale=ru$/);
});

test("signed in: account, trade link save and check, sign out", async ({ page }) => {
  const steamId = `7656119800000${String(Date.now()).slice(-4)}`;
  await devLogin(page, { steamId, name: "E2E Player" });
  await page.goto("/account");
  await expect(page.getByText("E2E Player").first()).toBeVisible();

  await page.getByText("Где взять?").click();
  await expect(page.getByRole("link", { name: "Открыть страницу в Steam" })).toBeVisible();

  await page.getByLabel("Ссылка на обмен").fill(tradeLinkFor(steamId));
  await page.getByRole("button", { name: "Сохранить" }).first().click();
  // The dev Waxpeer fake passes every link and there is no Steam key for the hold check.
  await expect(page.getByText("Ссылка работает — скин придёт сразу.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Ссылка на обмен")).toHaveValue(tradeLinkFor(steamId));

  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page.getByRole("link", { name: "Войти через Steam" }).first()).toBeVisible();
});

test("someone else's trade link is refused with a reason", async ({ page }) => {
  const steamId = "76561198000000777";
  await devLogin(page, { steamId });
  await page.goto("/account");
  await page.getByLabel("Ссылка на обмен").fill(tradeLinkFor("76561198000000778"));
  await page.getByRole("button", { name: "Сохранить" }).first().click();
  await expect(page.getByText(/ссылка другого аккаунта Steam/)).toBeVisible();
});

test("account page asks a visitor to sign in", async ({ page }) => {
  await page.goto("/en/account");
  await expect(page.getByText("Sign in with Steam to open your account.")).toBeVisible();
});
