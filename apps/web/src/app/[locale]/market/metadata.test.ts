import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve((key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
    ),
  setRequestLocale: () => undefined,
}));

// The page's components import the locale-aware navigation, which loads Next's client router.
vi.mock("@/i18n/navigation", () => ({ Link: () => null, useRouter: () => ({}) }));

const facets = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/skins", () => ({
  getSkinFacets: () => Promise.resolve(facets.current),
  getSkinsPage: () => Promise.resolve({ items: [], next_cursor: null }),
}));

import { generateMetadata } from "./page";

const meta = (searchParams: Record<string, string>) =>
  generateMetadata({
    params: Promise.resolve({ locale: "ru" }),
    searchParams: Promise.resolve(searchParams),
  });

describe("market indexability (ruling Q9)", () => {
  it("clean and tracked visits are indexable with canonical /market", async () => {
    for (const sp of [{}, { utm_source: "telegram" }, { fbclid: "abc" }, { gclid: "x" }]) {
      const m = await meta(sp);
      expect(m.robots).toMatchObject({ index: true, follow: true });
      expect(m.alternates?.canonical).toBe("https://csmarket.uz/market");
    }
  });
  it("a filtered view is noindex,follow with the same canonical", async () => {
    const m = await meta({ category: "knives" });
    expect(m.robots).toEqual({ index: false, follow: true });
    expect(m.alternates?.canonical).toBe("https://csmarket.uz/market");
  });
});

describe("market title and description", () => {
  it("say how many skins are in stock", async () => {
    facets.current = {
      categories: [
        { value: "rifles", count: 30000 },
        { value: "knives", count: 5000 },
      ],
      weapons: [],
      exteriors: [],
      rarities: [],
    };
    const m = await meta({});
    expect(m.title).toBe("meta.title");
    expect(m.description).toBe('meta.marketDescription:{"count":35000}');
  });
  it("fall back to the plain description without facets", async () => {
    facets.current = null;
    expect((await meta({})).description).toBe("meta.description");
  });
});
