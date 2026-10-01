import { describe, expect, it, vi } from "vitest";

const calls = vi.hoisted((): { namespaces: unknown[] } => ({ namespaces: [] }));
vi.mock("next-intl/server", () => ({
  getTranslations: (opts: unknown) => {
    calls.namespaces.push(opts);
    return Promise.resolve((key: string) => `web.balance.${key}`);
  },
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/balance/TopupStatus", () => ({ TopupStatus: () => null }));

import TopupPage, { generateMetadata } from "./page";

describe("top-up page", () => {
  it("is titled in the route's locale and never indexed", async () => {
    const meta = await generateMetadata({
      params: Promise.resolve({ locale: "uz", number: "T1" }),
    });
    expect(meta).toEqual({
      title: "web.balance.title",
      robots: { index: false, follow: false },
    });
    expect(calls.namespaces).toContainEqual({ locale: "uz", namespace: "web.balance" });
  });

  it("hands the number and the locale to the status view", async () => {
    const page = await TopupPage({ params: Promise.resolve({ locale: "en", number: "T42" }) });
    expect(JSON.stringify(page.props)).toContain('"number":"T42"');
    expect(JSON.stringify(page.props)).toContain('"locale":"en"');
  });
});
