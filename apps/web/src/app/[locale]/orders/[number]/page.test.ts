import { describe, expect, it, vi } from "vitest";

const calls = vi.hoisted((): { namespaces: unknown[]; values: unknown[] } => ({
  namespaces: [],
  values: [],
}));
vi.mock("next-intl/server", () => ({
  getTranslations: (opts: unknown) => {
    calls.namespaces.push(opts);
    return Promise.resolve((key: string, values?: unknown) => {
      calls.values.push(values);
      return `web.orders.${key}`;
    });
  },
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/order/OrderView", () => ({ OrderView: () => null }));

import OrderPage, { generateMetadata } from "./page";

describe("order page", () => {
  it("is titled with the number in the route's locale and never indexed", async () => {
    const meta = await generateMetadata({
      params: Promise.resolve({ locale: "uz", number: "A7" }),
    });
    expect(meta).toEqual({
      title: "web.orders.number",
      robots: { index: false, follow: false },
    });
    expect(calls.namespaces).toContainEqual({ locale: "uz", namespace: "web.orders" });
    expect(calls.values).toContainEqual({ number: "A7" });
  });

  it("hands the number and the locale to the order view", async () => {
    const page = await OrderPage({ params: Promise.resolve({ locale: "en", number: "A42" }) });
    expect(JSON.stringify(page.props)).toContain('"number":"A42"');
    expect(JSON.stringify(page.props)).toContain('"locale":"en"');
  });
});
