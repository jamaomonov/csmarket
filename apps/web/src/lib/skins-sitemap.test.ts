import { describe, expect, it } from "vitest";

import { chunkCount, SKINS_PER_SITEMAP, sitemapIndexXml, urlsetXml } from "./skins-sitemap";

describe("skins sitemap", () => {
  it("splits the items so no file nears the 50 000-URL limit in three locales", () => {
    expect(SKINS_PER_SITEMAP * 3).toBeLessThan(50_000);
    expect(chunkCount(0)).toBe(0);
    expect(chunkCount(SKINS_PER_SITEMAP)).toBe(1);
    expect(chunkCount(SKINS_PER_SITEMAP + 1)).toBe(2);
  });

  it("lists every page in every locale with hreflang alternates", () => {
    const xml = urlsetXml(["/item/ak-47-redline-field-tested"], "2026-10-01");
    expect(xml).toContain("<loc>https://csmarket.uz/item/ak-47-redline-field-tested</loc>");
    expect(xml).toContain("<loc>https://csmarket.uz/en/item/ak-47-redline-field-tested</loc>");
    expect(xml).toContain("<loc>https://csmarket.uz/uz/item/ak-47-redline-field-tested</loc>");
    expect(xml.match(/<url>/g)).toHaveLength(3);
    expect(xml).toContain(
      '<xhtml:link rel="alternate" hreflang="uz" href="https://csmarket.uz/uz/item/ak-47-redline-field-tested"/>',
    );
    expect(xml).toContain("<lastmod>2026-10-01</lastmod>");
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
  });

  it("carries x-default → ru on every url, like the pages' own alternates (ruling Q11)", () => {
    const xml = urlsetXml(["/item/a"], "2026-10-01");
    const link =
      '<xhtml:link rel="alternate" hreflang="x-default" href="https://csmarket.uz/item/a"/>';
    // one per <url>, each listing it among its alternates
    expect(xml.split(link)).toHaveLength(4);
  });

  it("writes the home page as the bare apex and /en, /uz", () => {
    const xml = urlsetXml(["/"], "2026-10-01");
    expect(xml).toContain("<loc>https://csmarket.uz/</loc>");
    expect(xml).toContain("<loc>https://csmarket.uz/en</loc>");
    expect(xml).toContain("<loc>https://csmarket.uz/uz</loc>");
  });

  it("escapes what XML cannot hold raw", () => {
    expect(urlsetXml(["/item/a&b"], "2026-10-01")).toContain("/item/a&amp;b");
  });

  it("indexes the files", () => {
    const xml = sitemapIndexXml(["https://csmarket.uz/skins-sitemap/0.xml"], "2026-10-01");
    expect(xml).toContain("<sitemapindex");
    expect(xml).toContain("<loc>https://csmarket.uz/skins-sitemap/0.xml</loc>");
  });
});
