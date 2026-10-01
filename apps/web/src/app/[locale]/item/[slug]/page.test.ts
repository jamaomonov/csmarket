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
vi.mock("@/lib/skins", () => ({ getSkinDetail: vi.fn().mockResolvedValue(null) }));
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
