import { describe, expect, it, vi } from "vitest";

const calls = vi.hoisted((): { namespaces: unknown[] } => ({ namespaces: [] }));
vi.mock("next-intl/server", () => ({
  getTranslations: (opts: unknown) => {
    calls.namespaces.push(opts);
    return Promise.resolve((key: string) => `web.orders.${key}`);
  },
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/account/OrdersList", () => ({ OrdersList: () => null }));

import OrdersPage, { generateMetadata } from "./page";

describe("my orders page", () => {
  it("is titled in the route's locale and never indexed", async () => {
    const meta = await generateMetadata({ params: Promise.resolve({ locale: "uz" }) });
    expect(meta).toEqual({ title: "web.orders.title", robots: { index: false, follow: false } });
    expect(calls.namespaces).toContainEqual({ locale: "uz", namespace: "web.orders" });
  });

  it("titles the list and hands it the locale", async () => {
    const page = await OrdersPage({ params: Promise.resolve({ locale: "en" }) });
    const json = JSON.stringify(page.props);
    expect(json).toContain("web.orders.title");
    expect(json).toContain('"locale":"en"');
  });
});
