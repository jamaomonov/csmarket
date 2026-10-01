import { expect, test } from "@playwright/test";

import { devLogin, uniqueSteamId } from "./helpers";

const WEB = process.env.WEB_BASE_URL ?? "http://localhost:3100";

test("an admin credits, refuses an over-clawback, bans, and the audit shows it", async ({
  page,
  browser,
}) => {
  // A fresh customer, signed in on the storefront in a context of its own.
  const custId = uniqueSteamId("7656119804");
  const custName = `Cust ${custId.slice(-7)}`;
  const customerContext = await browser.newContext({ baseURL: WEB });
  try {
    const customer = await customerContext.newPage();
    await devLogin(customer, { steamId: custId, name: custName });
    await customer.goto("/account");
    await expect(customer.getByText(custName).first()).toBeVisible();

    await devLogin(page, { steamId: uniqueSteamId("7656119805"), name: "Owner", admin: true });
    await page.goto("/users");
    await page.getByLabel("Имя или Steam ID").fill(custId);
    await page.getByTestId("users-table").getByRole("link", { name: custName }).click();
    await expect(page).toHaveURL(/\/users\/[^/]+$/);
    const userId = new URL(page.url()).pathname.split("/").pop() ?? "";
    await expect(page.getByRole("heading", { level: 1, name: custName })).toBeVisible();
    const balance = page.getByTestId("user-balance");
    await expect(balance).toHaveText(/^Баланс: 0\sсум$/);

    // Credit 25 000.
    await page.getByRole("button", { name: "Изменить баланс" }).click();
    await page.getByLabel("Сумма, сум").fill("25000");
    await page.getByLabel("Причина изменения").fill("Компенсация за ожидание");
    await page.getByRole("button", { name: "Продолжить" }).click();
    await expect(page.getByTestId("adjust-confirm")).toHaveText(/^Начислить 25\s000\sсум$/);
    await page.getByTestId("adjust-confirm").click();
    await expect(balance).toHaveText(/^Баланс: 25\s000\sсум$/);

    // Claw back more than is there: refused, balance untouched.
    await page.getByRole("button", { name: "Изменить баланс" }).click();
    await page.getByLabel("Сумма, сум").fill("-30000");
    await page.getByLabel("Причина изменения").fill("Проверка списания");
    await page.getByRole("button", { name: "Продолжить" }).click();
    await expect(page.getByTestId("adjust-confirm")).toHaveText(/^Списать 30\s000\sсум$/);
    await page.getByTestId("adjust-confirm").click();
    await expect(page.getByTestId("adjust-confirm-step").getByRole("alert")).toHaveText(
      "На балансе меньше, чем вы хотите списать.",
    );
    await expect(balance).toHaveText(/^Баланс: 25\s000\sсум$/);

    // Ban.
    await page.getByRole("button", { name: "Заблокировать" }).click();
    const dialog = page.getByRole("dialog", { name: "Заблокировать пользователя" });
    await dialog.getByLabel("Причина").fill("Тест блокировки");
    await dialog.getByRole("button", { name: "Заблокировать", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId("user-banned")).toHaveText(/^Заблокирован .*: Тест блокировки$/);
    await expect(page.getByRole("button", { name: "Разблокировать" })).toBeVisible();

    // The audit has the credit and the ban for this customer — and nothing for the refusal.
    await page.goto("/audit");
    await page.getByLabel("Id цели").fill(userId);
    await expect(page).toHaveURL(new RegExp(`target_id=${userId}`));
    const rows = page.getByTestId("audit-table").locator("tbody tr");
    await expect(rows).toHaveCount(2);
    const adjust = rows.filter({
      has: page.getByRole("cell", { name: "Изменение баланса", exact: true }),
    });
    await expect(adjust).toHaveCount(1);
    await expect(adjust).toContainText(/сумма: \+25\s000\sсум/);
    await expect(adjust).toContainText("причина: Компенсация за ожидание");
    await expect(adjust).toContainText("Owner");
    const ban = rows.filter({
      has: page.getByRole("cell", { name: "Блокировка", exact: true }),
    });
    await expect(ban).toHaveCount(1);
    await expect(ban).toContainText("причина: Тест блокировки");

    // The customer's storefront says the account is blocked. `devLogin`'s init script
    // re-sets the session hint on every navigation, so this reload does not prove that the
    // hint survives a suspended refresh; `packages/api-client` unit tests cover that.
    await customer.reload();
    await expect(customer.getByText("Аккаунт заблокирован.")).toBeVisible();
  } finally {
    await customerContext.close();
  }
});
