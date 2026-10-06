import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => `web.trades.${key}`),
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/trades/TradesView", () => ({ TradesView: () => null }));

import TradesPage, { generateMetadata } from "./page";

const page = (type?: string) =>
  TradesPage({
    params: Promise.resolve({ locale: "ru" }),
    searchParams: Promise.resolve(type === undefined ? {} : { type }),
  });

describe("trades page", () => {
  it("is titled «Обмены» and never indexed", async () => {
    const meta = await generateMetadata({ params: Promise.resolve({ locale: "ru" }) });
    expect(meta).toEqual({ title: "web.trades.title", robots: { index: false, follow: false } });
  });

  it("reads the filter from ?type, anything else is «all»", async () => {
    expect(JSON.stringify((await page()).props)).toContain('"type":"all"');
    expect(JSON.stringify((await page("purchases")).props)).toContain('"type":"purchases"');
    expect(JSON.stringify((await page("sales")).props)).toContain('"type":"sales"');
    expect(JSON.stringify((await page("junk")).props)).toContain('"type":"all"');
  });
});
