import { beforeEach, expect, test, vi } from "vitest";

const facets = vi.hoisted((): { current: SkinFacets | null } => ({ current: null }));
vi.mock("@/lib/skins", () => ({ getSkinFacets: () => Promise.resolve(facets.current) }));

import { dynamic, GET } from "./route";

import type { SkinFacets } from "@csmarket/utils/skins";

beforeEach(() => {
  facets.current = {
    categories: [
      { value: "knives", count: 5000 },
      { value: "rifles", count: 30000 },
    ],
    weapons: [],
    exteriors: [],
    rarities: [],
  };
});

test("describes the shop and links its sections, with live counts", async () => {
  const res = await GET();
  expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
  const body = await res.text();
  expect(body.startsWith("# csmarket.uz\n")).toBe(true);
  expect(body).toContain("Uzbekistan");
  expect(body).toContain("Click, Payme");
  expect(body).toContain("35,000 skins");
  expect(body).toContain("[Knives](https://csmarket.uz/category/knives): 5,000 skins");
  expect(body).toContain("https://csmarket.uz/market");
  expect(body).toContain("https://docs.csmarket.uz/llms.txt");
  expect(body).toContain("https://csmarket.uz/uz");
});

test("tells an assistant how buying, refunds and the terms work", async () => {
  const body = await (await GET()).text();
  expect(body).toContain("https://csmarket.uz/pay/click");
  expect(body).toContain("https://csmarket.uz/cheap");
  expect(body).toContain("## Refunds");
  expect(body).toContain("support@csmarket.uz");
  expect(body).toContain("[Public offer](https://csmarket.uz/legal/terms)");
});

test("tells an assistant how selling works, without percents or fees (owner)", async () => {
  const body = await (await GET()).text();
  const selling = body.slice(body.indexOf("## Selling skins"), body.indexOf("## Refunds"));
  expect(selling).toContain(
    "[Sell CS2 (CS:GO) skins and cash out to a card](https://csmarket.uz/sell)",
  );
  expect(selling).toContain("Uzcard, Humo or Uzum Visa");
  expect(selling).toContain("7 days");
  expect(selling).not.toMatch(/%|fee|commission/i);
});

test("an API outage still answers, without numbers", async () => {
  facets.current = null;
  const body = await (await GET()).text();
  expect(body).toContain("https://csmarket.uz/market");
  expect(body).not.toMatch(/\d+,\d{3} skins/);
});

test("is rendered per request", () => {
  expect(dynamic).toBe("force-dynamic");
});
