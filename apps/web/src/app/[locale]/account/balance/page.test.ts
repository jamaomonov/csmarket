import { describe, expect, it, vi } from "vitest";

const calls = vi.hoisted((): { namespaces: unknown[] } => ({ namespaces: [] }));
vi.mock("next-intl/server", () => ({
  getTranslations: (opts: unknown) => {
    calls.namespaces.push(opts);
    return Promise.resolve((key: string) => `web.balance.${key}`);
  },
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/balance/BalanceView", () => ({ BalanceView: () => null }));

import { generateMetadata } from "./page";

describe("balance page metadata", () => {
  it("is titled in the route's locale and never indexed", async () => {
    const meta = await generateMetadata({ params: Promise.resolve({ locale: "uz" }) });
    expect(meta).toEqual({
      title: "web.balance.title",
      robots: { index: false, follow: false },
    });
    expect(calls.namespaces).toContainEqual({ locale: "uz", namespace: "web.balance" });
  });
});
