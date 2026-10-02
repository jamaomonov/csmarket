import { expect, test } from "@playwright/test";

import {
  apiLogin,
  buyThroughTestKassa,
  devLogin,
  saveTradeLink,
  uniqueSteamId,
  waitForLetter,
} from "./helpers";

// One fresh account; one `order-create` hit.
const PREFIX = "7656119808";
const SLUG = "usp-s-kill-confirmed-minimal-wear";

test("confirm the email by its link, then a paid order sends a receipt", async ({
  page,
  request,
}) => {
  test.setTimeout(150_000);
  const steamId = uniqueSteamId(PREFIX);
  const address = `e2e-${steamId}@example.uz`;
  await devLogin(page, { steamId, name: "Mail" });
  const token = await apiLogin(request, steamId, "Mail");

  await page.goto("/account");
  const form = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Email" }) });
  await form.getByRole("textbox", { name: "Email" }).fill(address);
  await form.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText("Мы отправили письмо со ссылкой — откройте его.")).toBeVisible();

  const verify = await waitForLetter(request, token, "verify");
  expect(verify.subject).toBe("Подтвердите почту");
  expect(JSON.stringify(verify)).not.toContain(address);
  const link = /https?:\/\/\S+\/account\/email\/confirm\?token=[\w-]+/.exec(verify.text)?.[0];
  expect(link, "a confirmation link in the letter").toBeTruthy();
  const url = new URL(link ?? "");
  await page.goto(`${url.pathname}${url.search}`);
  await expect(
    page.getByText("Почта подтверждена. Теперь письма о заказах будут приходить на неё."),
  ).toBeVisible();
  expect(page.url()).not.toContain("token=");

  await page.goto("/account");
  await expect(page.getByText("Подтверждена", { exact: true })).toBeVisible();

  await saveTradeLink(request, token, steamId);
  const number = await buyThroughTestKassa(request, token, SLUG);
  const receipt = await waitForLetter(request, token, "receipt", (l) => l.subject.includes(number));
  expect(receipt.subject).toBe(`Заказ #${number} оплачен`);
  expect(receipt.text).toContain(`/orders/${number}`);
  expect(receipt.text).not.toContain("tradeoffer");
});
