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

// One fresh account; one `order-create` hit (the test kassa pays it, no top-up).
const PREFIX = "7656119807";
const SLUG = "usp-s-kill-confirmed-field-tested";

test("the order page moves on the socket's nudge, not on its next poll", async ({
  page,
  request,
}) => {
  test.setTimeout(150_000);
  const steamId = uniqueSteamId(PREFIX);
  await devLogin(page, { steamId, name: "Live" });
  const token = await apiLogin(request, steamId, "Live");
  await saveTradeLink(request, token, steamId);
  const number = await buyThroughTestKassa(request, token, SLUG);
  await waitForOrder(request, token, number, "trade_sent");

  const nudges: number[] = [];
  page.on("websocket", (ws) => {
    ws.on("framereceived", ({ payload }) => {
      if (typeof payload === "string" && payload.includes(`"number":"${number}"`)) {
        nudges.push(Date.now());
      }
    });
  });
  let navigations = 0;
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) navigations += 1;
  });
  await page.goto(`/orders/${number}`);
  const status = page.getByTestId("order-status");
  await expect(status).toHaveAttribute("data-state", "trade_sent");
  const loaded = navigations;

  await devTrade(request, token, number, "accept");
  // The reconcile sweep (every 10 s) reads the fake and commits `delivered` with a nudge.
  await expect.poll(() => nudges.length, { timeout: 60_000 }).toBeGreaterThan(0);
  const nudgedAt = nudges[0] ?? 0;
  // A poll could take 8–16 s; the nudge re-reads at once.
  await expect(status).toHaveAttribute("data-state", "delivered", { timeout: 5_000 });
  expect(Date.now() - nudgedAt).toBeLessThan(5_000);
  await expect(page.getByText("Получено", { exact: true })).toBeVisible();
  expect(navigations).toBe(loaded);
});
