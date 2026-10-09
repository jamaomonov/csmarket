import { beforeEach, describe, expect, it, vi } from "vitest";

const { getSkinsPage, getPopular } = vi.hoisted(() => ({
  getSkinsPage: vi.fn(),
  getPopular: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve((k: string, v?: Record<string, unknown>) =>
      v ? `${k}:${JSON.stringify(v)}` : k,
    ),
  setRequestLocale: () => undefined,
}));
vi.mock("@/lib/skins", () => ({
  getSkinsPage,
  displayPrice: (_l: string, uzs: string | null) => `${uzs ?? "?"} сум`,
}));
vi.mock("@/lib/landing", () => ({
  CHEAP_MAX_UZS: 100000,
  CHEAP_MIX: ["rifles", "pistols"],
  getPopular,
}));
vi.mock("@/i18n/navigation", () => ({ Link: () => null, useRouter: () => ({}) }));

import CheapPage, { generateMetadata } from "./page";

const item = (slug: string, price: string) => ({
  slug,
  name: `Skin ${slug}`,
  price_uzs: price,
  price_usd: "1",
});
const params = Promise.resolve({ locale: "ru" });

describe("cheap skins landing", () => {
  beforeEach(() => {
    getPopular
      .mockReset()
      .mockResolvedValue([
        item("a", "50000"),
        item("b", "20000"),
        item("d", "70000"),
        item("e", "1"),
      ]);
    getSkinsPage.mockReset().mockImplementation((q: { category: string }) =>
      Promise.resolve({
        items: [item(`cheap-${q.category}`, q.category === "pistols" ? "900" : "1500")],
        next_cursor: null,
      }),
    );
  });

  it("shows weapon skins only: the landing's cheap mix and the cheapest of its categories", async () => {
    await CheapPage({ params });
    expect(getPopular).toHaveBeenCalledWith("cheap");
    expect(getSkinsPage).toHaveBeenCalledWith({
      sort: "price",
      category: "rifles",
      maxUzs: 100000,
    });
    expect(getSkinsPage).toHaveBeenCalledWith({
      sort: "price",
      category: "pistols",
      maxUzs: 100000,
    });
  });

  it("answers from live numbers: the cheapest skin and the top three", async () => {
    const el = await CheapPage({ params });
    const { faq } = el.props as { faq: { entries: { question: string; answer: string }[] } };
    expect(faq.entries.map((e) => e.question)).toEqual(["cheapestQ", "popularQ", "howQ"]);
    expect(faq.entries[0]?.answer).toBe(
      'cheapestA:{"name":"Skin cheap-pistols","price":"900 сум"}',
    );
    expect(faq.entries[1]?.answer).toBe(
      'popularA:{"list":"Skin a — 50000 сум, Skin b — 20000 сум, Skin d — 70000 сум"}',
    );
  });

  it("is indexable with the price in its description", async () => {
    const meta = await generateMetadata({ params });
    expect(meta.alternates?.canonical).toBe("https://csmarket.uz/cheap");
    expect(meta.description).toBe('description:{"price":"900 сум"}');
  });

  it("an empty catalogue drops the live answers and the price", async () => {
    getSkinsPage.mockResolvedValue({ items: [], next_cursor: null });
    getPopular.mockResolvedValue([]);
    const el = await CheapPage({ params });
    const { faq } = el.props as { faq: { entries: { question: string }[] } };
    expect(faq.entries.map((e) => e.question)).toEqual(["howQ"]);
    expect((await generateMetadata({ params })).description).toBe("descriptionNoPrice");
  });
});
