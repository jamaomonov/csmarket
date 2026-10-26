import { describe, expect, it } from "vitest";

import { articleSlugOf, isSection, sectionHref } from "./articles";

describe("articles paths", () => {
  it("tells sections from articles", () => {
    expect(isSection("news")).toBe(true);
    expect(isSection("top-knives")).toBe(false);
    expect(sectionHref(null)).toBe("/articles");
    expect(sectionHref("tops")).toBe("/articles/tops");
  });

  it("finds an article's slug in a localised path, never a section's", () => {
    expect(articleSlugOf("/articles/top-knives")).toBe("top-knives");
    expect(articleSlugOf("/uz/articles/top-knives")).toBe("top-knives");
    expect(articleSlugOf("/en/articles/news")).toBeNull();
    expect(articleSlugOf("/articles")).toBeNull();
    expect(articleSlugOf("/market")).toBeNull();
  });
});

describe("switchTarget", () => {
  it("keeps the path unless it is an article without that language", async () => {
    const { switchTarget } = await import("./articles");
    expect(switchTarget("/articles/top", ["ru", "en"], "en")).toBe("/articles/top");
    expect(switchTarget("/articles/top", ["ru", "en"], "uz")).toBe("/articles");
    expect(switchTarget("/articles/news", [], "uz")).toBe("/articles/news");
    expect(switchTarget("/market", [], "uz")).toBe("/market");
  });
});

describe("pageLanguages", () => {
  it("reads the hreflang links of the page", async () => {
    const { pageLanguages } = await import("./articles");
    const doc = {
      querySelectorAll: () => [
        { getAttribute: () => "ru" },
        { getAttribute: () => "x-default" },
        { getAttribute: () => "en" },
      ],
    };
    expect(pageLanguages(doc)).toEqual(["ru", "en"]);
  });
});
