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

import SkinWeaponPage, { generateMetadata } from "./page";

const FACETS = {
  categories: [],
  weapons: [
    { value: "AK-47", count: 594 },
    { value: "★ Karambit", count: 3 },
  ],
  exteriors: [],
  rarities: [],
};
const PAGE = { items: [], next_cursor: null };
const params = (weapon: string) => Promise.resolve({ locale: "ru", weapon });

describe("weapon landing", () => {
  beforeEach(() => {
    notFound.mockClear();
    getSkinFacets.mockReset().mockResolvedValue(FACETS);
    getSkinsPage.mockReset().mockResolvedValue(PAGE);
  });

  it("an unknown weapon 404s in metadata and page", async () => {
    await expect(generateMetadata({ params: params("xyz") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(SkinWeaponPage({ params: params("xyz") })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(2);
    expect(getSkinsPage).not.toHaveBeenCalled();
  });

  it("an API 404 for the facets is a 404", async () => {
    getSkinFacets.mockResolvedValue(null);
    await expect(SkinWeaponPage({ params: params("ak-47") })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("an outage is an error, never a 404 (ruling Q10)", async () => {
    getSkinFacets.mockRejectedValue(new Error("API 503"));
    await expect(SkinWeaponPage({ params: params("ak-47") })).rejects.toThrow("API 503");
    expect(notFound).not.toHaveBeenCalled();
  });

  it("a ★ weapon resolves from its slug and queries by its facet value", async () => {
    const meta = await generateMetadata({ params: params("karambit") });
    expect(meta.alternates?.canonical).toBe("https://csmarket.uz/weapon/karambit");
    expect(meta.robots).toMatchObject({ index: true, follow: true });
    expect(getSkinsPage).toHaveBeenCalledWith({ sort: "price", weapon: "★ Karambit" });
  });
});
