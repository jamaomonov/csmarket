import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => `web.transactions.${key}`),
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/balance/BalanceView", () => ({ BalanceView: () => null }));

import TransactionsPage, { generateMetadata } from "./page";

const page = (type?: string) =>
  TransactionsPage({
    params: Promise.resolve({ locale: "ru" }),
    searchParams: Promise.resolve(type === undefined ? {} : { type }),
  });

describe("transactions page", () => {
  it("is titled «Транзакции» and never indexed", async () => {
    const meta = await generateMetadata({ params: Promise.resolve({ locale: "ru" }) });
    expect(meta).toEqual({
      title: "web.transactions.title",
      robots: { index: false, follow: false },
    });
  });

  it("reads the filter from ?type, anything else is «all»", async () => {
    expect(JSON.stringify((await page()).props)).toContain('"type":"all"');
    expect(JSON.stringify((await page("topup")).props)).toContain('"type":"topup"');
    expect(JSON.stringify((await page("withdrawal")).props)).toContain('"type":"withdrawal"');
    expect(JSON.stringify((await page("junk")).props)).toContain('"type":"all"');
  });
});
