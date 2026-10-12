import { describe, expect, it, vi } from "vitest";

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve(Object.assign((k: string) => k, { rich: (k: string) => k })),
  setRequestLocale: () => undefined,
}));
const { getSkinDetail } = vi.hoisted(() => ({
  getSkinDetail: vi.fn<() => Promise<unknown>>().mockResolvedValue(null),
}));
vi.mock("@/lib/skins", () => ({ getSkinDetail, displayPrice: () => null }));
// The page's components import the locale-aware navigation, which loads Next's client router.
vi.mock("@/i18n/navigation", () => ({ Link: () => null, useRouter: () => ({}) }));

import SkinPage, { generateMetadata } from "./page";

const params = Promise.resolve({ locale: "ru", slug: "nope" });

describe("unknown item", () => {
  it("metadata calls notFound() too, so status and head agree", async () => {
    notFound.mockClear();
    await expect(generateMetadata({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });

  it("the page calls notFound() before rendering anything", async () => {
    notFound.mockClear();
    await expect(SkinPage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });
});

describe("item share picture", () => {
  it("og:image and twitter:image point at the generated 1200×630 card", async () => {
    getSkinDetail.mockResolvedValueOnce({
      slug: "awp-dragon-lore-mw",
      name: "AWP | Dragon Lore (Minimal Wear)",
      phase: null,
      image_url: "https://community.fastly.steamstatic.com/economy/image/abc",
      price_uzs: null,
      price_usd: null,
      count: 0,
    });
    const meta = await generateMetadata({
      params: Promise.resolve({ locale: "en", slug: "awp-dragon-lore-mw" }),
    });
    const url = "https://csmarket.uz/en/item/awp-dragon-lore-mw/og.png";
    expect(meta.openGraph?.images).toEqual([
      { url, width: 1200, height: 630, alt: "AWP | Dragon Lore (Minimal Wear)" },
    ]);
    expect(meta.twitter).toEqual({ card: "summary_large_image", images: [url] });
  });
});
