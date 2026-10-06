// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SellPage from "./page";

import type { SellItem } from "@/lib/sell";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => key),
  setRequestLocale: () => undefined,
}));
const skins = vi.hoisted(() => ({ getSkinsPage: vi.fn() }));
vi.mock("@/lib/skins", () => skins);
vi.mock("@/components/ComingSoon", () => ({ ComingSoon: () => null }));
const shown = vi.hoisted((): { inventory: SellItem[] | null } => ({ inventory: null }));
vi.mock("@/components/sell/SellView", () => ({
  SellView: ({ inventory }: { inventory: SellItem[] }) => {
    shown.inventory = inventory;
    return null;
  },
}));

import { ComingSoon } from "@/components/ComingSoon";

afterEach(() => {
  vi.unstubAllEnvs();
});

const page = () => SellPage({ params: Promise.resolve({ locale: "ru" }) });

describe("sell page", () => {
  it("in production it is still «Скоро» and asks the API for nothing", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const out = await page();
    expect(out.type).toBe(ComingSoon);
    expect(skins.getSkinsPage).not.toHaveBeenCalled();
  });

  it("in dev it shows the sell page on a demo inventory from the catalogue", async () => {
    vi.stubEnv("NODE_ENV", "development");
    skins.getSkinsPage.mockResolvedValue({
      items: [
        {
          slug: "ak",
          name: "AK-47 | Redline (Field-Tested)",
          category: "rifles",
          weapon: "AK-47",
          skin: "Redline",
          exterior: "FT",
          stattrak: false,
          rarity_color: null,
          image_url: "https://img.test/ak.png",
          price_uzs: "300000",
        },
      ],
      next_cursor: null,
    });
    render(await page());
    expect(shown.inventory).toHaveLength(1);
    expect(shown.inventory?.[0]?.priceUzs).toBe(240_000);
  });
});
