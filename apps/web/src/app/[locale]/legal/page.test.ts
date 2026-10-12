import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((k: string) => k),
  setRequestLocale: () => undefined,
}));
vi.mock("@/i18n/navigation", () => ({ Link: () => null }));

import LegalIndexPage, { generateMetadata } from "./page";

import type { ReactElement } from "react";

describe("the documents index", () => {
  it("is indexable under /legal", async () => {
    const meta = await generateMetadata({ params: Promise.resolve({ locale: "en" }) });
    expect(meta.title).toBe("index.title");
    expect(meta.alternates?.canonical).toBe("https://csmarket.uz/en/legal");
  });

  it("lists every document", async () => {
    const el = (await LegalIndexPage({
      params: Promise.resolve({ locale: "ru" }),
    })) as ReactElement<{
      children: ReactElement<{ children: ReactElement[] }>;
    }>;
    expect(el.props.children.props.children).toHaveLength(6);
  });

  it("404s an unknown locale", async () => {
    await expect(LegalIndexPage({ params: Promise.resolve({ locale: "de" }) })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
  });
});
