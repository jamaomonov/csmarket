import { describe, expect, it } from "vitest";

import { mdDoc, mdFaq, mdLink, mdTarget, mdText, prefersMarkdown } from "./agent-md";

describe("prefersMarkdown", () => {
  it("wants text/markdown named above text/html", () => {
    expect(prefersMarkdown("text/markdown")).toBe(true);
    expect(prefersMarkdown("text/markdown, text/html;q=0.9")).toBe(true);
    expect(prefersMarkdown("text/html;q=0.5, text/markdown")).toBe(true);
  });

  it("never for browsers, wildcards or an explicit zero", () => {
    expect(prefersMarkdown(null)).toBe(false);
    expect(prefersMarkdown("*/*")).toBe(false);
    expect(prefersMarkdown("text/html,application/xhtml+xml,*/*;q=0.8")).toBe(false);
    expect(prefersMarkdown("text/html, text/markdown")).toBe(false);
    expect(prefersMarkdown("text/markdown;q=0")).toBe(false);
  });
});

describe("mdTarget", () => {
  it("names the locale and the page", () => {
    expect(mdTarget("/")).toEqual({ locale: "ru", segments: [] });
    expect(mdTarget("/uz")).toEqual({ locale: "uz", segments: [] });
    expect(mdTarget("/en/item/awp-asiimov-field-tested")).toEqual({
      locale: "en",
      segments: ["item", "awp-asiimov-field-tested"],
    });
    expect(mdTarget("/market")).toEqual({ locale: "ru", segments: ["market"] });
  });

  it("refuses pages without a twin", () => {
    for (const path of ["/account", "/item", "/market/x", "/item/a/b", "/md/ru/market"]) {
      expect(mdTarget(path)).toBeNull();
    }
  });
});

describe("writing", () => {
  it("escapes what Markdown would read as markup", () => {
    expect(mdText("AK-47 | Redline [FT] *x* _y_")).toBe("AK-47 | Redline \\[FT\\] \\*x\\* \\_y\\_");
    expect(mdLink("★ Karambit", "https://csmarket.uz/item/karambit")).toBe(
      "[★ Karambit](https://csmarket.uz/item/karambit)",
    );
  });

  it("joins blocks and drops empty ones", () => {
    expect(mdDoc(["# A", null, "", false, "b"])).toBe("# A\n\nb\n");
    expect(mdFaq("FAQ", [])).toBe("");
    expect(mdFaq("FAQ", [{ question: "Q?", answer: "A." }])).toBe("## FAQ\n\n### Q?\n\nA.");
  });
});
