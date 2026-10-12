import { beforeEach, describe, expect, it, vi } from "vitest";

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve(
      Object.assign((k: string) => k, {
        raw: () => [
          { h: "One", p: "First." },
          { h: "Two", p: "Second." },
        ],
      }),
    ),
  setRequestLocale: () => undefined,
}));
vi.mock("@/i18n/navigation", () => ({ Link: () => null }));

import LegalDocPage, { generateMetadata, generateStaticParams } from "./page";

import type { ReactElement } from "react";

const params = (doc: string, locale = "ru") => Promise.resolve({ locale, doc });

describe("a legal document", () => {
  beforeEach(() => {
    notFound.mockClear();
  });

  it("is built for every document", () => {
    expect(generateStaticParams().map((p) => p.doc)).toEqual([
      "terms",
      "agreement",
      "sell",
      "privacy",
      "refunds",
      "imprint",
    ]);
  });

  it("an unknown document or locale 404s in metadata and page", async () => {
    await expect(generateMetadata({ params: params("nope") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(LegalDocPage({ params: params("nope") })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(LegalDocPage({ params: params("terms", "de") })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("has its own canonical, hreflang and title", async () => {
    const meta = await generateMetadata({ params: params("privacy", "uz") });
    expect(meta.title).toBe("privacy.title");
    expect(meta.description).toBe("privacy.intro");
    expect(meta.alternates?.canonical).toBe("https://csmarket.uz/uz/legal/privacy");
    expect(meta.alternates?.languages).toMatchObject({
      ru: "https://csmarket.uz/legal/privacy",
      "x-default": "https://csmarket.uz/legal/privacy",
    });
    expect(meta.robots).toMatchObject({ index: true, follow: true });
  });

  it("passes the document's texts and every section to the frame", async () => {
    const el = (await LegalDocPage({ params: params("refunds") })) as ReactElement<{
      title: string;
      updated: string;
      intro: string;
      children: ReactElement<{ children: ReactElement[] }>;
    }>;
    expect(el.props.title).toBe("refunds.title");
    expect(el.props.updated).toBe("refunds.updated");
    expect(el.props.intro).toBe("refunds.intro");
    expect(el.props.children.props.children).toHaveLength(2);
  });
});
