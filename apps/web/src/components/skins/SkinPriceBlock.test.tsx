// @vitest-environment jsdom
import messages from "@csmarket/i18n/locales/ru/web.json";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkinOffersProvider } from "./SkinOffers";
import { SkinPriceBlock } from "./SkinPriceBlock";

import type * as SkinsModule from "@/lib/skins";
import type { SkinListing } from "@csmarket/utils/skins";
import type { ReactNode } from "react";

import { fetchSkinListings } from "@/lib/skins";

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));
const mocked = vi.mocked(fetchSkinListings);

const wrap = (ui: ReactNode) =>
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      {ui}
    </NextIntlClientProvider>,
  );

const offer = (id: number, usd: string, uzs: string): SkinListing => ({
  listing_id: id,
  price_usd: usd,
  price_uzs: uzs,
  float_value: null,
  paint_seed: null,
  stickers: [],
  inspect_url: null,
});

const price = () => (
  <SkinOffersProvider slug="ak-ft">
    <SkinPriceBlock
      storedUzs="357300"
      storedUsd="28.13"
      steamUrl="https://steamcommunity.com/market/listings/730/x"
      locale="ru"
    />
  </SkinOffersProvider>
);

describe("SkinPriceBlock", () => {
  beforeEach(() => mocked.mockReset());

  it("headlines the cheapest live offer once offers load", async () => {
    mocked.mockResolvedValue({
      degraded: false,
      items: [offer(1, "28.40", "360700"), offer(2, "28.30", "359400")],
    });
    wrap(price());
    expect(await screen.findByText(/359\s?400/)).toBeInTheDocument();
    expect(screen.queryByText(/^от /)).not.toBeInTheDocument();
  });

  it("says «от» the stored price while offers load or when there are none", async () => {
    mocked.mockResolvedValue({ degraded: false, items: [] });
    wrap(price());
    expect(await screen.findByText(/от 357\s?300/)).toBeInTheDocument();
  });

  it("has no buy button or delivery promise, and the Steam link is nofollow", async () => {
    mocked.mockResolvedValue({ degraded: false, items: [] });
    wrap(price());
    expect(await screen.findByText(/от 357\s?300/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(/Мгновенная доставка/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Steam/ })).toHaveAttribute(
      "rel",
      expect.stringContaining("nofollow"),
    );
  });
});

describe("SkinPriceBlock vs Steam", () => {
  beforeEach(() => mocked.mockReset());

  it("prices the cheapest offer and says how much cheaper than Steam", async () => {
    mocked.mockResolvedValue({
      degraded: false,
      items: [offer(1, "28.40", "360700"), offer(2, "28.30", "359400")],
    });
    wrap(
      <SkinOffersProvider slug="ak-ft">
        <SkinPriceBlock
          storedUzs="357300"
          storedUsd="28.13"
          steamUsd="35.00"
          steamUrl="https://steamcommunity.com/market/listings/730/x"
          locale="ru"
        />
      </SkinOffersProvider>,
    );
    expect(await screen.findByText(/359\s?400/)).toBeInTheDocument();
    expect(screen.getByText("−19% к Steam")).toBeInTheDocument();
  });
});
