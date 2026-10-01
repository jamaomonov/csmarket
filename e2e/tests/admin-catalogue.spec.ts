import { expect, test } from "@playwright/test";

import { API, devLogin } from "./helpers";

// A seeded item no other spec reads: the hide window must not be visible to specs that run
// in parallel (`fullyParallel`, one shared worker pool).
const SLUG = "glock-18-water-elemental-well-worn";
const STEAM_ID = "76561198000000882";

test("an admin hides an item and the storefront 404s it, then shows it again", async ({
  page,
  request,
}) => {
  const web = process.env.WEB_BASE_URL ?? "http://localhost:3100";
  try {
    await devLogin(page, { steamId: STEAM_ID, name: "Owner", admin: true });
    await page.goto("/catalogue");
    await expect(page.getByRole("heading", { level: 1, name: "Каталог" })).toBeVisible();
    await page.getByLabel("Найти скин").fill("water elemental well-worn");
    const row = page
      .getByRole("listitem")
      .filter({ hasText: /^Glock-18 \| Water Elemental \(Well-Worn\)/ });
    // A run that died mid-way may have left the item hidden: start from «shown».
    await expect(row.getByRole("button").first()).toBeVisible();
    if (await row.getByRole("button", { name: "Показать" }).isVisible()) {
      await row.getByRole("button", { name: "Показать" }).click();
    }
    await expect(row.getByRole("button", { name: "Скрыть" })).toBeVisible();
    expect((await request.get(`${web}/item/${SLUG}`)).status()).toBe(200);

    await row.getByRole("button", { name: "Скрыть" }).click();
    await expect(row.getByRole("button", { name: "Показать" })).toBeVisible();
    expect((await request.get(`${web}/item/${SLUG}`)).status()).toBe(404);

    await row.getByRole("button", { name: "Показать" }).click();
    await expect(row.getByRole("button", { name: "Скрыть" })).toBeVisible();
    expect((await request.get(`${web}/item/${SLUG}`)).status()).toBe(200);
  } finally {
    // Whatever happened above, leave the item shown (a retry must start clean).
    const login = await request.post(`${API}/api/v1/auth/dev-login`, {
      data: { steam_id: STEAM_ID, display_name: "Owner", admin: true },
    });
    const { access_token: token } = (await login.json()) as { access_token: string };
    await request.patch(`${API}/api/v1/admin/skins/items/${SLUG}`, {
      data: { hidden: false },
      headers: {
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": crypto.randomUUID(),
      },
    });
  }
});
