import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { agentMarkdown, defaultLocaleRedirect, marketRedirect } from "./middleware";

const at = (url: string) => marketRedirect(new NextRequest(new URL(url, "https://csmarket.uz")));

describe("filtered root URLs move to /market", () => {
  it("redirects a catalogue query on the ru root, keeping the whole query", () => {
    const r = at("/?category=knives&utm_source=tg");
    expect(r?.status).toBe(301);
    expect(r?.headers.get("location")).toBe(
      "https://csmarket.uz/market?category=knives&utm_source=tg",
    );
  });

  it("redirects on the uz and en roots to their own market", () => {
    expect(at("/uz?q=ak")?.headers.get("location")).toBe("https://csmarket.uz/uz/market?q=ak");
    expect(at("/en/?sort=price")?.headers.get("location")).toBe(
      "https://csmarket.uz/en/market?sort=price",
    );
  });

  it("leaves the landing alone for a clean or tracked visit", () => {
    expect(at("/")).toBeNull();
    expect(at("/?utm_source=telegram&gclid=x")).toBeNull();
    expect(at("/uz")).toBeNull();
  });

  it("never touches other paths", () => {
    expect(at("/market?category=knives")).toBeNull();
    expect(at("/item/ak-47-redline-field-tested?q=x")).toBeNull();
  });
});

describe("the spelled-out default locale moves for good", () => {
  const ru = (url: string) =>
    defaultLocaleRedirect(new NextRequest(new URL(url, "https://csmarket.uz")));

  it("answers 308 to the unprefixed URL, keeping the query", () => {
    const r = ru("/ru/market?category=knives");
    expect(r?.status).toBe(308);
    expect(r?.headers.get("location")).toBe("https://csmarket.uz/market?category=knives");
    expect(ru("/ru")?.headers.get("location")).toBe("https://csmarket.uz/");
    expect(ru("/ru/")?.headers.get("location")).toBe("https://csmarket.uz/");
  });

  it("leaves other locales and look-alike paths alone", () => {
    expect(ru("/uz/market")).toBeNull();
    expect(ru("/rules")).toBeNull();
    expect(ru("/market")).toBeNull();
  });
});

describe("an AI agent asking for Markdown gets the page's twin", () => {
  const ask = (url: string, accept: string) =>
    agentMarkdown(new NextRequest(new URL(url, "https://csmarket.uz"), { headers: { accept } }));

  it("rewrites an item, a landing, the market and a home page", () => {
    const rewrite = (url: string) =>
      ask(url, "text/markdown")?.headers.get("x-middleware-rewrite") ?? null;
    expect(rewrite("/item/ak-47-redline-field-tested")).toBe(
      "https://csmarket.uz/md/ru/item/ak-47-redline-field-tested",
    );
    expect(rewrite("/uz/category/knives")).toBe("https://csmarket.uz/md/uz/category/knives");
    expect(rewrite("/en/market")).toBe("https://csmarket.uz/md/en/market");
    expect(rewrite("/")).toBe("https://csmarket.uz/md/ru");
  });

  it("marks the rewrite so the twin answers", () => {
    const res = ask("/market", "text/markdown");
    expect(res?.headers.get("x-middleware-request-x-csmarket-md")).toBe("1");
  });

  it("leaves browsers, other pages and HTML-first clients alone", () => {
    expect(ask("/market", "text/html,application/xhtml+xml,*/*;q=0.8")).toBeNull();
    expect(ask("/market", "text/html, text/markdown;q=0.5")).toBeNull();
    expect(ask("/account", "text/markdown")).toBeNull();
    expect(ask("/item", "text/markdown")).toBeNull();
  });
});
