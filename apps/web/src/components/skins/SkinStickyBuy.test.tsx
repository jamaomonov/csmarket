// @vitest-environment jsdom
import ru from "@csmarket/i18n/locales/ru/web.json";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SkinOffersProvider } from "./SkinOffers";
import { SkinStickyBuy } from "./SkinStickyBuy";

import type * as SkinsModule from "@/lib/skins";

import { fetchSkinListings } from "@/lib/skins";

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));

let seen: (entries: { isIntersecting: boolean }[]) => void = () => undefined;

beforeEach(() => {
  vi.mocked(fetchSkinListings).mockResolvedValue({
    degraded: false,
    items: [
      {
        listing_id: "wx:1",
        price_usd: "30.00",
        price_uzs: "381000",
        float_value: 0.2,
        paint_seed: 1,
        stickers: [],
        inspect_url: null,
      },
    ],
  });
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(cb: typeof seen) {
        seen = cb;
      }
      observe = vi.fn();
      disconnect = vi.fn();
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function page() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru }}>
      <SkinOffersProvider slug="ak">
        <section id="buy" />
        <SkinStickyBuy locale="ru" />
      </SkinOffersProvider>
    </NextIntlClientProvider>,
  );
}

describe("SkinStickyBuy", () => {
  it("keeps the selected offer's price and «Купить» at the bottom, and goes to the panel", async () => {
    page();
    const bar = await screen.findByTestId("sticky-buy");
    expect(bar).toHaveTextContent(/381\s000/);
    const panel = document.getElementById("buy");
    if (panel === null) throw new Error("no panel");
    const scroll = vi.fn();
    panel.scrollIntoView = scroll;
    fireEvent.click(screen.getByRole("button", { name: "Купить" }));
    expect(scroll).toHaveBeenCalled();
  });

  it("hides while the buy panel is on screen", async () => {
    page();
    const bar = await screen.findByTestId("sticky-buy");
    act(() => {
      seen([{ isIntersecting: true }]);
    });
    expect(bar).not.toBeVisible();
    act(() => {
      seen([{ isIntersecting: false }]);
    });
    expect(bar).toBeVisible();
  });
});
