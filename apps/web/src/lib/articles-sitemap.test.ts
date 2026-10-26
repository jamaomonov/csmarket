import { describe, expect, it } from "vitest";

import { articlesXml } from "./articles-sitemap";

describe("articlesXml", () => {
  it("lists each live translation with its lastmod and only live alternates", () => {
    const xml = articlesXml(
      [
        { slug: "top", locale: "ru", updated_at: "2026-10-21T10:00:00Z" },
        { slug: "top", locale: "en", updated_at: "2026-10-21T10:00:00Z" },
      ],
      { ru: ["tops"], uz: [], en: ["tops"] },
    );
    expect(xml).toContain(
      "<url><loc>https://csmarket.uz/articles/top</loc><lastmod>2026-10-21</lastmod>",
    );
    expect(xml).toContain("<loc>https://csmarket.uz/en/articles/top</loc>");
    expect(xml).not.toContain("https://csmarket.uz/uz/articles/top");
    expect(xml).toContain('hreflang="x-default" href="https://csmarket.uz/articles/top"');
  });

  it("lists the article lists and sections that have articles in each language", () => {
    const xml = articlesXml([], { ru: ["news", "tops"], uz: [], en: ["tops"] });
    expect(xml).toContain("<loc>https://csmarket.uz/articles</loc>");
    expect(xml).toContain("<loc>https://csmarket.uz/articles/news</loc>");
    expect(xml).toContain("<loc>https://csmarket.uz/en/articles/tops</loc>");
    expect(xml).not.toContain("<loc>https://csmarket.uz/en/articles/news</loc>");
    expect(xml).not.toContain("https://csmarket.uz/uz/articles");
  });
});
