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

import SkinColorPage, { generateMetadata } from "./page";

const FACETS = {
  categories: [],
  weapons: [],
  exteriors: [],
  rarities: [],
  colors: [
    { value: "red", count: 1200 },
    { value: "beige", count: 4 },
  ],
};
const PAGE = { items: [], next_cursor: null };
const params = (color: string) => Promise.resolve({ locale: "ru", color });

describe("colour landing", () => {
  beforeEach(() => {
    notFound.mockClear();
    getSkinFacets.mockReset().mockResolvedValue(FACETS);
    getSkinsPage.mockReset().mockResolvedValue(PAGE);
  });

  it("an unknown colour 404s before any read", async () => {
    await expect(generateMetadata({ params: params("teal") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(SkinColorPage({ params: params("teal") })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(getSkinFacets).not.toHaveBeenCalled();
  });

  it("a colour with no items is a 404", async () => {
    await expect(SkinColorPage({ params: params("white") })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("reads the colour's items and is indexable", async () => {
    const meta = await generateMetadata({ params: params("red") });
    expect(meta.robots).toMatchObject({ index: true });
    expect(getSkinsPage).toHaveBeenCalledWith({ sort: "price", color: "red" });
    await SkinColorPage({ params: params("red") });
    expect(getSkinsPage).toHaveBeenCalledWith({ sort: "popular", color: "red" });
  });

  it("a thin colour stays out of the index", async () => {
    const meta = await generateMetadata({ params: params("beige") });
    expect(meta.robots).toMatchObject({ index: false, follow: true });
  });
});
