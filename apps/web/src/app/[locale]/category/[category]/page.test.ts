import { beforeEach, describe, expect, it, vi } from "vitest";

const { notFound, getSkinFacets, getSkinsPage } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  getSkinFacets: vi.fn(),
  getSkinsPage: vi.fn(),
}));
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve(Object.assign((k: string) => k, { rich: (k: string) => k })),
  setRequestLocale: () => undefined,
}));
vi.mock("@/lib/skins", () => ({
  getSkinFacets,
  getSkinsPage,
  displayPrice: () => "100 сум",
}));
vi.mock("@/i18n/navigation", () => ({ Link: () => null, useRouter: () => ({}) }));

import SkinCategoryPage, { generateMetadata } from "./page";

const FACETS = {
  categories: [{ value: "knives", count: 21 }],
  weapons: [{ value: "★ Karambit", count: 3 }],
  exteriors: [],
  rarities: [],
};
const PAGE = { items: [], next_cursor: null };
const params = (category: string) => Promise.resolve({ locale: "ru", category });

describe("category landing", () => {
  beforeEach(() => {
    notFound.mockClear();
    getSkinFacets.mockReset().mockResolvedValue(FACETS);
    getSkinsPage.mockReset().mockResolvedValue(PAGE);
  });

  it("an unknown category 404s in metadata and page, without touching the API", async () => {
    await expect(generateMetadata({ params: params("xyz") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(SkinCategoryPage({ params: params("xyz") })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(2);
    expect(getSkinFacets).not.toHaveBeenCalled();
  });

  it("a category the catalogue does not list 404s", async () => {
    await expect(generateMetadata({ params: params("rifles") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(SkinCategoryPage({ params: params("rifles") })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("an API 404 for the facets is a 404", async () => {
    getSkinFacets.mockResolvedValue(null);
    await expect(SkinCategoryPage({ params: params("knives") })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("an outage is an error, never a 404 (ruling Q10)", async () => {
    getSkinFacets.mockRejectedValue(new Error("API 503"));
    await expect(SkinCategoryPage({ params: params("knives") })).rejects.toThrow("API 503");
    await expect(generateMetadata({ params: params("knives") })).rejects.toThrow("API 503");
    expect(notFound).not.toHaveBeenCalled();
  });

  it("a known category is indexable with canonical and x-default", async () => {
    const meta = await generateMetadata({ params: params("knives") });
    expect(meta.robots).toMatchObject({ index: true, follow: true });
    expect(meta.alternates?.canonical).toBe("https://csmarket.uz/category/knives");
    expect(meta.alternates?.languages).toMatchObject({
      uz: "https://csmarket.uz/uz/category/knives",
      "x-default": "https://csmarket.uz/category/knives",
    });
  });

  it("answers price and how-to-buy, the knife question, and shows the category's text", async () => {
    getSkinsPage.mockImplementation((q: { sort: string }) =>
      Promise.resolve(
        q.sort === "price"
          ? {
              items: [{ name: "★ Karambit | Safari Mesh", price_uzs: "1", price_usd: "1" }],
              next_cursor: null,
            }
          : PAGE,
      ),
    );
    const el = await SkinCategoryPage({ params: params("knives") });
    const props = el.props as {
      faq: { entries: { question: string }[] };
      after?: { props: { children: string } };
    };
    expect(props.faq.entries.map((e) => e.question)).toEqual([
      "priceQ",
      "landing.cheapestKnifeQ",
      "howQ",
    ]);
    expect(props.after?.props.children).toBe("text.knives");
  });
});
