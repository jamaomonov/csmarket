import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => `web.transactions.${key}`),
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/transactions/TransactionsView", () => ({ TransactionsView: () => null }));

import TransactionsPage, { generateMetadata } from "./page";

const page = (tab?: string) =>
  TransactionsPage({
    params: Promise.resolve({ locale: "ru" }),
    searchParams: Promise.resolve(tab === undefined ? {} : { tab }),
  });

describe("transactions page", () => {
  it("is never indexed", async () => {
    const meta = await generateMetadata({ params: Promise.resolve({ locale: "ru" }) });
    expect(meta.robots).toEqual({ index: false, follow: false });
  });

  it("opens purchases unless the balance tab is asked for", async () => {
    expect(JSON.stringify((await page()).props)).toContain('"tab":"purchases"');
    expect(JSON.stringify((await page("balance")).props)).toContain('"tab":"balance"');
    expect(JSON.stringify((await page("junk")).props)).toContain('"tab":"purchases"');
  });
});
