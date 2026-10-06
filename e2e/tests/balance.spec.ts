import { expect, request as apiRequest, test } from "@playwright/test";

import { API, devLogin, uniqueSteamId } from "./helpers";

// `topup-create` is ip_guard-limited (per IP, and per IP + account): this file opens two
// top-ups per run, each for its own fresh account.
const PREFIX = "7656119803";

test("top up 50 000 soʻm through the test kassa and see it on the balance", async ({ page }) => {
  await devLogin(page, { steamId: uniqueSteamId(PREFIX), name: "Buyer" });
  await page.goto("/account/transactions");
  await expect(page.getByRole("heading", { level: 1, name: "Транзакции" })).toBeVisible();
  await expect(page.getByText("Пока пусто.")).toBeVisible();
  // The top-up has its own page, «Кошелёк».
  await page.locator("#main-content").getByRole("link", { name: "Пополнить" }).click();
  await expect(page).toHaveURL(/\/deposit$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1, name: "Кошелёк" })).toBeVisible();

  await page.getByLabel("Сумма", { exact: true }).fill("50000");
  const mock = page.getByRole("button", { name: "Тестовая оплата" });
  await mock.click();
  await expect(mock).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: /^Пополнить на 50\s000/ }).click();

  // `?go=1` is spent on the first answer; the mock kassa never opens anything. The client
  // navigation waits on `next dev` compiling the status route under the suite's load.
  await expect(page).toHaveURL(/\/account\/balance\/topups\/T[0-9A-Z]{7}$/, { timeout: 30_000 });
  const number = /T[0-9A-Z]{7}$/.exec(page.url())?.[0] ?? "";
  const status = page.getByTestId("topup-status");
  await expect(status).toHaveAttribute("data-state", "pending");
  await expect(page.getByRole("heading", { name: "Ждём оплату" })).toBeVisible();

  await page.getByRole("button", { name: "Оплатить (тест)" }).click();
  await expect(status).toHaveAttribute("data-state", "succeeded");
  await expect(page.getByRole("heading", { name: /^Баланс пополнен на 50\s000/ })).toBeVisible();

  await page.getByRole("link", { name: "К балансу" }).click();
  await expect(page).toHaveURL(/\/account\/transactions$/, { timeout: 30_000 });
  // The header shows the balance too: read the one on the page.
  await expect(page.locator("#main-content").getByText(/^50\s000\sсум$/)).toBeVisible();
  const entry = page.getByRole("listitem").filter({ hasText: number });
  await expect(entry).toHaveCount(1);
  await expect(entry.getByText("Пополнение", { exact: true })).toBeVisible();
  await expect(entry.getByTestId("entry-amount")).toHaveText(/^\+50\s000\sсум$/);
});

test("an amount below the minimum is refused in the form", async ({ page }) => {
  await devLogin(page, { steamId: uniqueSteamId(PREFIX) });
  await page.goto("/deposit");
  await page.getByLabel("Сумма", { exact: true }).fill("999");
  await page.getByRole("button", { name: "Тестовая оплата" }).click();
  await page.getByRole("button", { name: /^Пополнить на 999/ }).click();
  // Scoped to the form: Next's route announcer is a second, empty `alert` on every page.
  await expect(page.locator("form").getByRole("alert")).toHaveText(
    /^Сумма от 1\s000\sсум до 10\s000\s000\sсум/,
  );
  // Refused before any request: no top-up was opened.
  await expect(page).toHaveURL(/\/deposit$/);
});

test("someone else's top-up number shows not found", async ({ page, request }) => {
  // The owner opens a real top-up through the API, on a context of its own.
  const owner = await apiRequest.newContext();
  try {
    const login = await owner.post(`${API}/api/v1/auth/dev-login`, {
      data: { steam_id: uniqueSteamId(PREFIX), display_name: null, admin: false },
    });
    expect(login.ok()).toBe(true);
    // Known-shape JSON from our own dev-login (`TokensOut`).
    const { access_token: token } = (await login.json()) as { access_token: string };
    const created = await owner.post(`${API}/api/v1/wallet/topups`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": `e2e-topup-${crypto.randomUUID()}`,
      },
      data: { amount_uzs: 10000, provider: "mock", locale: "ru" },
    });
    expect(created.status()).toBe(201);
    // Known-shape JSON from our own API (`TopupOut`).
    const { number } = (await created.json()) as { number: string };

    // Another account opens it: not found, never a hint that it exists.
    await devLogin(page, { steamId: uniqueSteamId(PREFIX) });
    await page.goto(`/account/balance/topups/${number}`);
    await expect(page.getByTestId("topup-status")).toHaveAttribute("data-state", "notFound");
    await expect(page.getByText("Пополнение не найдено.")).toBeVisible();
    expect((await request.get(`${API}/api/v1/wallet/topups/${number}`)).status()).toBe(401);
  } finally {
    await owner.dispose();
  }
});
