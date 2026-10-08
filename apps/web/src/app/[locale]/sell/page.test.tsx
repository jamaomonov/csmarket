// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import SellPage from "./page";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => key),
  setRequestLocale: () => undefined,
}));
const server = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/server-api", () => server);
vi.mock("@/components/ComingSoon", () => ({ ComingSoon: () => null }));
vi.mock("@/components/sell/SellView", () => ({ SellView: () => null }));

import { ComingSoon } from "@/components/ComingSoon";
import { SellView } from "@/components/sell/SellView";

const page = () => SellPage({ params: Promise.resolve({ locale: "ru" }) });

describe("sell page", () => {
  it("is «Скоро» while selling is switched off", async () => {
    server.apiGet.mockResolvedValue({ enabled: false });
    expect((await page()).type).toBe(ComingSoon);
  });

  it("is «Скоро» when the API cannot say", async () => {
    server.apiGet.mockRejectedValue(new Error("down"));
    expect((await page()).type).toBe(ComingSoon);
  });

  it("shows the sell page with the config when selling is on", async () => {
    const config = { enabled: true, balance_bonus_pct: "2" };
    server.apiGet.mockResolvedValue(config);
    const out = await page();
    expect(server.apiGet).toHaveBeenCalledWith("/sell/config", { noStore: true });
    // The page returns a JSX element; its props are untyped, so the child is narrowed by shape.
    const view = (out.props as { children: unknown }).children as {
      type: unknown;
      props: { config: unknown };
    };
    expect(view.type).toBe(SellView);
    expect(view.props.config).toBe(config);
  });
});
