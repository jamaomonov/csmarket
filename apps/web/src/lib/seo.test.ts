import { describe, expect, it } from "vitest";

import { alternates, localeUrl, ogLocale, shareImage } from "./seo";

describe("seo", () => {
  it("ru has no prefix, others do", () => {
    expect(localeUrl("ru", "/item/ak")).toBe("https://csmarket.uz/item/ak");
    expect(localeUrl("uz", "/item/ak")).toBe("https://csmarket.uz/uz/item/ak");
    expect(localeUrl("en", "/")).toBe("https://csmarket.uz/en");
    expect(localeUrl("ru", "/")).toBe("https://csmarket.uz/");
  });
  it("alternates carry every locale and x-default → ru", () => {
    const a = alternates("uz", "/category/knives");
    expect(a.canonical).toBe("https://csmarket.uz/uz/category/knives");
    expect(a.languages).toEqual({
      ru: "https://csmarket.uz/category/knives",
      uz: "https://csmarket.uz/uz/category/knives",
      en: "https://csmarket.uz/en/category/knives",
      "x-default": "https://csmarket.uz/category/knives",
    });
  });
  it("og locale lists the other two", () => {
    expect(ogLocale("uz")).toEqual({ locale: "uz_UZ", alternateLocale: ["ru_RU", "en_US"] });
  });
  it("the share preview is the locale's own 1200×630 picture, unknown → ru", () => {
    expect(shareImage("uz", "alt")).toEqual({
      openGraph: [{ url: "https://csmarket.uz/og/uz.jpg", width: 1200, height: 630, alt: "alt" }],
      twitter: { card: "summary_large_image", images: ["https://csmarket.uz/og/uz.jpg"] },
    });
    expect(shareImage("xx", "a").openGraph[0]?.url).toBe("https://csmarket.uz/og/ru.jpg");
  });
});
