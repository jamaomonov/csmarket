import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { clientMessages, isLegalDoc, LEGAL_DOCS, legalPaths } from "./legal";

const LOCALES_DIR = resolve(__dirname, "../../../../packages/i18n/locales");

interface Doc {
  title: string;
  intro: string;
  updated: string;
  sections: { h: string; p: string }[];
}

function load(locale: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(LOCALES_DIR, locale, "legal.json"), "utf8")) as Record<
    string,
    unknown
  >;
}

describe("legal documents", () => {
  it("knows its slugs and nothing else", () => {
    expect(LEGAL_DOCS).toEqual(["terms", "agreement", "sell", "privacy", "refunds", "imprint"]);
    expect(isLegalDoc("privacy")).toBe(true);
    expect(isLegalDoc("no-such")).toBe(false);
    expect(isLegalDoc("index")).toBe(false);
  });

  it("gives the sitemap the index and every document", () => {
    expect(legalPaths()).toEqual([
      "/legal",
      "/legal/terms",
      "/legal/agreement",
      "/legal/sell",
      "/legal/privacy",
      "/legal/refunds",
      "/legal/imprint",
    ]);
  });

  it("keeps the texts out of the client catalogue", () => {
    const all = { common: { a: "1" }, web: { b: "2" }, legal: { c: "3" } };
    expect(clientMessages(all)).toEqual({ common: { a: "1" }, web: { b: "2" } });
  });

  for (const locale of ["ru", "uz", "en"]) {
    it(`${locale}: every document has a title, a date, a lead and filled sections`, () => {
      const catalogue = load(locale);
      for (const slug of LEGAL_DOCS) {
        // A known shape from our own JSON.
        const doc = catalogue[slug] as Doc;
        expect(doc.title, slug).not.toBe("");
        expect(doc.updated, slug).not.toBe("");
        expect(doc.intro, slug).not.toBe("");
        expect(doc.sections.length, slug).toBeGreaterThan(0);
        for (const s of doc.sections) {
          expect(s.h.trim(), slug).not.toBe("");
          expect(s.p.trim(), slug).not.toBe("");
        }
        // Section headings are React keys and anchor ids: unique within a document.
        expect(new Set(doc.sections.map((s) => s.h)).size, slug).toBe(doc.sections.length);
      }
    });

    it(`${locale}: names the seller, the INN and the support address`, () => {
      const text = JSON.stringify(load(locale));
      expect(text).toContain("OMONOV JAMSHID IBROHIM OʻGʻLI");
      expect(text).toContain("50304056560048");
      expect(text).toContain("support@csmarket.uz");
      expect(text).not.toMatch(/yupay|telegram|\+998/i);
    });
  }
});
