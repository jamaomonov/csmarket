import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => key),
  setRequestLocale: () => undefined,
}));

// The page's components import the locale-aware navigation, which loads Next's client router.
vi.mock("@/i18n/navigation", () => ({ Link: () => null, useRouter: () => ({}) }));

import { generateMetadata } from "./page";

const meta = (searchParams: Record<string, string>) =>
  generateMetadata({
    params: Promise.resolve({ locale: "ru" }),
    searchParams: Promise.resolve(searchParams),
  });

describe("home indexability (ruling Q9)", () => {
  it("clean and tracked visits are indexable with canonical /", async () => {
    for (const sp of [{}, { utm_source: "telegram" }, { fbclid: "abc" }, { gclid: "x" }]) {
      const m = await meta(sp);
      expect(m.robots).toMatchObject({ index: true, follow: true });
      expect(m.alternates?.canonical).toBe("https://csmarket.uz/");
    }
  });
  it("a filtered view is noindex,follow with the same canonical", async () => {
    const m = await meta({ category: "knives" });
    expect(m.robots).toEqual({ index: false, follow: true });
    expect(m.alternates?.canonical).toBe("https://csmarket.uz/");
  });
});
