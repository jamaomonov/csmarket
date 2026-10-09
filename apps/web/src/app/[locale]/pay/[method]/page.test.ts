import { beforeEach, describe, expect, it, vi } from "vitest";

const { notFound, getPopular } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  getPopular: vi.fn(),
}));
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve(
      Object.assign(
        (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
        { raw: () => [{ q: "Q {method}", a: "A {method}" }] },
      ),
    ),
  setRequestLocale: () => undefined,
}));
vi.mock("@/lib/landing", () => ({ getPopular }));
vi.mock("@/i18n/navigation", () => ({ Link: () => null, useRouter: () => ({}) }));

import PayPage, { generateMetadata } from "./page";

const params = (method: string, locale = "ru") => Promise.resolve({ locale, method });

describe("payment-method landing", () => {
  beforeEach(() => {
    notFound.mockClear();
    getPopular.mockReset().mockResolvedValue([]);
  });

  it("an unknown method 404s in metadata and page", async () => {
    await expect(generateMetadata({ params: params("visa") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(PayPage({ params: params("visa") })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(getPopular).not.toHaveBeenCalled();
  });

  it("is indexable with its own canonical, title and the brand name", async () => {
    const meta = await generateMetadata({ params: params("payme", "uz") });
    expect(meta.alternates?.canonical).toBe("https://csmarket.uz/uz/pay/payme");
    expect(meta.robots).toMatchObject({ index: true, follow: true });
    expect(meta.title).toBe('title:{"method":"Payme"}');
  });

  it("lists popular skins and answers its questions with the method's name", async () => {
    const el = await PayPage({ params: params("click") });
    expect(getPopular).toHaveBeenCalledWith("popular");
    const props = el.props as { faq: { entries: { question: string; answer: string }[] } };
    expect(props.faq.entries).toEqual([{ question: "Q Click", answer: "A Click" }]);
  });
});
