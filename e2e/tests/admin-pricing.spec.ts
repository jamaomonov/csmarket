import { expect, test } from "@playwright/test";

import { API, apiAdminLogin, devLogin, uniqueSteamId } from "./helpers";

// Changes the live rules for one weapon only (Nova: no other spec buys it), then puts the
// document back, so the parallel buy specs' prices never move under them.
const PREFIX = "7656119809";
const WEB = process.env.WEB_BASE_URL ?? "http://localhost:3100";
const WEAPON = "Nova";

interface Rules {
  weapon_pp: Record<string, string>;
  [field: string]: unknown;
}

test("a weapon markup previews before saving and reprices the storefront after", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const steamId = uniqueSteamId(PREFIX);
  const token = await apiAdminLogin(request, steamId);
  const headers = { Authorization: `Bearer ${token}` };
  const saved = await request.get(`${API}/api/v1/admin/skins/pricing`, { headers });
  // Known-shape JSON from our own API (`PricingOut`).
  const original = ((await saved.json()) as { rules: Rules }).rules;
  const items = await request.get(`${API}/api/v1/admin/skins/items?q=nova`, { headers });
  // Known-shape JSON from our own API (`AdminSkinItemsOut`).
  const nova = (
    (await items.json()) as { items: { slug: string; name: string; active: boolean }[] }
  ).items.find((i) => i.active);
  if (nova === undefined) throw new Error("no priced Nova in the seed");
  const priceOf = async (): Promise<string> => {
    const r = await request.get(`${API}/api/v1/skins/${nova.slug}`);
    // Known-shape JSON from our own API (`SkinDetailOut`): the price field we read.
    return JSON.stringify((await r.json()) as unknown);
  };
  const before = await priceOf();

  try {
    await devLogin(page, { steamId, name: "E2E admin", admin: true });
    await page.goto("/pricing");
    await expect(page.getByRole("heading", { name: "Цены" })).toBeVisible();

    const preview = page.locator("section").filter({ hasText: "Проверить цену" });
    await preview.getByLabel("Найти скин").fill("nova");
    await preview.getByRole("button", { name: nova.name }).click();
    const price = preview.getByText(/^\$\d+\.\d{2}$/);
    await expect(price).toBeVisible({ timeout: 15_000 });
    const was = await price.textContent();

    await page.getByRole("button", { name: "Добавить оружие" }).click();
    await page.getByLabel("Оружие", { exact: true }).last().fill(WEAPON);
    await page.getByLabel("Надбавка оружия, п.п.").last().fill("40");
    await expect(page.getByText("Есть несохранённые изменения")).toBeVisible();
    await expect(price).not.toHaveText(was ?? "", { timeout: 15_000 });

    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await page.getByRole("button", { name: "Да, сохранить" }).click();
    await expect(page.getByText("Есть несохранённые изменения")).toBeHidden({ timeout: 30_000 });

    await expect.poll(priceOf, { timeout: 15_000 }).not.toBe(before);
    await page.goto(`${WEB}/item/${nova.slug}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  } finally {
    const back = await request.put(`${API}/api/v1/admin/skins/pricing`, {
      headers: { ...headers, "Idempotency-Key": `e2e-restore-${crypto.randomUUID()}` },
      data: original,
    });
    expect(back.status(), "restore the rules").toBe(200);
  }
});
