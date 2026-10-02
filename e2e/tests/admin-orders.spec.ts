import { expect, test } from "@playwright/test";

import {
  apiLogin,
  buyThroughTestKassa,
  devLogin,
  devTrade,
  saveTradeLink,
  uniqueSteamId,
  waitForOrder,
} from "./helpers";

// A seeded item (`make seed-skins`); the customer pays through the test kassa, so this file
// opens one order and no top-up (ip_guard buckets `order-create`, `topup-create`).
const SLUG = "p90-asiimov-battle-scarred";

test("an admin finds a delivered order, its trade, and the trade under «Обмены»", async ({
  page,
  request,
}) => {
  // Two sweep-driven waits (sent, then delivered) before the admin pages: more than 90 s.
  test.setTimeout(150_000);
  // A fresh customer buys through the API and accepts the offer at the dev Waxpeer fake.
  const custId = uniqueSteamId("7656119807");
  const token = await apiLogin(request, custId, `Cust ${custId.slice(-7)}`);
  await saveTradeLink(request, token, custId);
  const number = await buyThroughTestKassa(request, token, SLUG);
  // The fake sends the offer ~6 s after the buy; the reconcile sweep reads it every 10 s.
  await waitForOrder(request, token, number, "trade_sent");
  await devTrade(request, token, number, "accept");
  await waitForOrder(request, token, number, "delivered");

  await devLogin(page, { steamId: uniqueSteamId("7656119808"), name: "Owner", admin: true });
  await page.goto("/orders");
  await expect(page.getByRole("heading", { level: 1, name: "Заказы" })).toBeVisible();
  await page.getByLabel("Номер заказа или название").fill(number);
  await expect(page).toHaveURL(new RegExp(`q=${number}`));
  const table = page.getByTestId("orders-table");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table.getByTestId("order-status")).toHaveText("получен");
  await table.getByRole("link", { name: number, exact: true }).click();

  await expect(page).toHaveURL(new RegExp(`/orders/${number}$`));
  await expect(page.getByRole("heading", { level: 1, name: `Заказ ${number}` })).toBeVisible();
  const trade = page.getByRole("region", { name: "Обмен", exact: true });
  await expect(trade).toContainText("4 — предложение отправлено");
  await expect(trade).toContainText("fake_seller");
  const offer = trade.getByRole("link", { name: /^\d+$/ });
  await expect(offer).toHaveAttribute("href", /^https:\/\/steamcommunity\.com\/tradeoffer\/\d+\/$/);
  await expect(page.getByRole("region", { name: "Платежи", exact: true })).toBeVisible();

  await page.goto("/trades");
  await expect(page.getByRole("heading", { level: 1, name: "Обмены" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^Все/ })).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByTestId("trades-table").getByRole("link", { name: number, exact: true }),
  ).toBeVisible();
});
