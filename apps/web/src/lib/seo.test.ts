import { describe, expect, it } from "vitest";

import { alternates, localeUrl, ogLocale } from "./seo";

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
});
