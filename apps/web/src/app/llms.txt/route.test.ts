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

test("an API outage still answers, without numbers", async () => {
  facets.current = null;
  const body = await (await GET()).text();
  expect(body).toContain("https://csmarket.uz/market");
  expect(body).not.toMatch(/\d+,\d{3} skins/);
});

test("is rendered per request", () => {
  expect(dynamic).toBe("force-dynamic");
});
