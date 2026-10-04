import { expect, test, type Page } from "@playwright/test";

import { apiLogin, devLogin, devTrade, saveTradeLink, topUp, uniqueSteamId } from "./helpers";

// Each test signs in a fresh account (this file's own prefix). `topup-create`, `order-create`
// and `order-pay` are ip_guard-limited per IP and per IP + account: a run of this file opens
// two top-ups, three orders and two pay calls (plus one test-kassa settle, keyless).
const PREFIX = "7656119806";
// Seeded items (`make seed-skins`) whose cheapest offer is under the 300 000 top-up, and one
// over any balance here. Under the dev Waxpeer fake the offers are the seed's snapshot.
const CHEAP = "mp9-starlight-protector-minimal-wear";
const CHEAPER = "desert-eagle-blaze-factory-new";
const DEAR = "negev-mjolnir-battle-scarred";
const TOP_UP = 300_000;

/** Whole soʻm as the storefront prints it: `43 500 сум`, any space between the groups. */
function sum(amount: number): string {
  return amount
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, "\\s")
    .concat("\\sсум");
}

/** Open the item, wait for the panel to settle on the cheapest offer, return its price. */
async function openItem(page: Page, slug: string): Promise<number> {
  await page.goto(`/item/${slug}`);
  const panel = page.getByRole("region", { name: "Купить" });
  const buy = panel.getByRole("button", { name: /^Купить за / });
  await expect(buy).toBeVisible({ timeout: 30_000 });
  // The cheapest offer is the one pre-selected (the seed's three offers are 100/105/110 %).
  await expect(page.getByRole("button", { name: "Выбран" })).toHaveCount(1);
  const label = (await buy.textContent()) ?? "";
  return Number(label.replace(/\D/g, ""));
}

/** Click the buy button and land on the order page; returns the order number. */
async function buy(page: Page): Promise<string> {
  const button = page.getByRole("region", { name: "Купить" }).getByRole("button", {
    name: /^Купить за /,
  });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page).toHaveURL(/\/orders\/[0-9A-Z]{8}(\?.*)?$/, { timeout: 30_000 });
  return /\/orders\/([0-9A-Z]{8})/.exec(page.url())?.[1] ?? "";
}

test("buy from the balance: the trade arrives and is accepted", async ({ page, request }) => {
  // Two sweep-driven waits of up to 60 s each, after a top-up and a buy: more than the
  // config's 90 s per test.
  test.setTimeout(150_000);
  const steamId = uniqueSteamId(PREFIX);
  await devLogin(page, { steamId, name: "Buyer" });
  // A session of its own for the API calls: the page rotates the browser's session.
  const token = await apiLogin(request, steamId, "Buyer");
  await saveTradeLink(request, token, steamId);
  await topUp(request, token, TOP_UP);

  const price = await openItem(page, CHEAP);
  expect(price).toBeGreaterThan(0);
  expect(price).toBeLessThan(TOP_UP);
  // The balance covers it: pre-selected.
  await expect(page.getByRole("button", { name: /^Баланс/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const number = await buy(page);

  const status = page.getByTestId("order-status");
  await expect(page.getByRole("heading", { level: 1, name: `Заказ #${number}` })).toBeVisible();
  // Paid from the balance in one step; the worker buys at once. The fake sends the offer
  // ~6 s later and the reconcile sweep (every 10 s) reads it; the live page (M4b) may show
  // the sent offer by the time it has loaded.
  await expect(status).toHaveAttribute("data-state", /^(paid|buying|trade_sent)$/);
  await expect(status).toHaveAttribute("data-state", "trade_sent", { timeout: 60_000 });
  const trade = page.getByRole("region", { name: "Обмен в Steam" });
  await expect(trade.getByText("Обмен отправлен — примите его в Steam.")).toBeVisible();
  await expect(trade.getByRole("link", { name: "Открыть обмен в Steam" })).toHaveAttribute(
    "href",
    /^https:\/\/steamcommunity\.com\/tradeoffer\/\d+\/?$/,
  );

  await devTrade(request, token, number, "accept");
  await expect(status).toHaveAttribute("data-state", "delivered", { timeout: 60_000 });
  await expect(trade.getByText("Получено", { exact: true })).toBeVisible();
  await expect(page.getByTestId("order-status-label")).toHaveText("Получен");

  await page.goto("/account/balance");
  await expect(
    page.locator("#main-content").getByText(new RegExp(`^${sum(TOP_UP - price)}$`)),
  ).toBeVisible();
  const entry = page.getByRole("listitem").filter({ hasText: number });
  await expect(entry).toHaveCount(1);
  await expect(entry.getByText("Покупка", { exact: true })).toBeVisible();
  await expect(entry.getByTestId("entry-amount")).toHaveText(new RegExp(`^−${sum(price)}$`));
});

test("buy through the test kassa with an empty balance", async ({ page, request }) => {
  const steamId = uniqueSteamId(PREFIX);
  await devLogin(page, { steamId, name: "Kassa buyer" });
  // A session of its own for the API calls: the page rotates the browser's session.
  const token = await apiLogin(request, steamId, "Kassa buyer");
  await saveTradeLink(request, token, steamId);

  await openItem(page, DEAR);
  // An empty balance is not pre-selected; it says how much is missing.
  const balance = page.getByRole("button", { name: /^Баланс/ });
  await expect(balance).toContainText("Не хватает");
  await expect(balance).not.toHaveAttribute("aria-pressed", "true");
  const kassa = page.getByRole("button", { name: "Тестовая оплата" });
  await kassa.click();
  await expect(kassa).toHaveAttribute("aria-pressed", "true");
  await buy(page);

  const status = page.getByTestId("order-status");
  await expect(status).toHaveAttribute("data-state", "pending");
  await expect(page.getByTestId("order-status-label")).toHaveText("Ждёт оплаты");
  // The test kassa never opens a page: the picker keeps it and the button says so.
  await page.getByRole("button", { name: "Оплатить (тест)" }).click();
  // Paid → the worker buys at once; the offer may already be out by the next poll.
  await expect(status).toHaveAttribute("data-state", /^(buying|trade_sent)$/, {
    timeout: 30_000,
  });
  await expect(page.getByRole("button", { name: "Оплатить (тест)" })).toBeHidden();
});

test("a declined trade puts the money back on the balance", async ({ page, request }) => {
  // Two sweep-driven waits of up to 60 s each, after a top-up and a buy: more than the
  // config's 90 s per test.
  test.setTimeout(150_000);
  const steamId = uniqueSteamId(PREFIX);
  await devLogin(page, { steamId, name: "Decliner" });
  // A session of its own for the API calls: the page rotates the browser's session.
  const token = await apiLogin(request, steamId, "Decliner");
  await saveTradeLink(request, token, steamId);
  await topUp(request, token, TOP_UP);

  await openItem(page, CHEAPER);
  await expect(page.getByRole("button", { name: /^Баланс/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const number = await buy(page);
  const status = page.getByTestId("order-status");
  await expect(status).toHaveAttribute("data-state", "trade_sent", { timeout: 60_000 });

  await devTrade(request, token, number, "decline");
  await expect(status).toHaveAttribute("data-state", "returned", { timeout: 60_000 });
  const trade = page.getByRole("region", { name: "Обмен в Steam" });
  await expect(
    trade.getByText("Обмен не состоялся — деньги вернулись на баланс.", { exact: true }),
  ).toBeVisible();

  await trade.getByRole("link", { name: "Открыть баланс" }).click();
  await expect(page).toHaveURL(/\/account\/balance$/, { timeout: 30_000 });
  // Back to what it was before the purchase.
  await expect(
    page.locator("#main-content").getByText(new RegExp(`^${sum(TOP_UP)}$`)),
  ).toBeVisible();
  const entries = page.getByRole("listitem").filter({ hasText: number });
  await expect(entries).toHaveCount(2);
  await expect(entries.getByText("Возврат на баланс", { exact: true })).toBeVisible();
  await expect(entries.getByText("Покупка", { exact: true })).toBeVisible();
});
