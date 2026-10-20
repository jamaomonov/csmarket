// @vitest-environment jsdom
import messages from "@csmarket/i18n/locales/ru/web.json";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinHero } from "./SkinHero";
import { SkinOffersProvider, useSelectedOffer } from "./SkinOffers";

import type * as SkinsModule from "@/lib/skins";

import { fetchSkinListings } from "@/lib/skins";

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));

const lot = (id: number, usd: string, float: number, stickers: number) => ({
  listing_id: `wx:${String(id)}`,
  price_usd: usd,
  price_uzs: null,
  float_value: float,
  paint_seed: 7,
  stickers: Array.from({ length: stickers }, (_, i) => ({
    name: `Sticker | ${String(i)}`,
    image: `https://community.fastly.steamstatic.com/economy/image/s${String(i)}`,
    slot: i,
    wear: null,
  })),
  inspect_url: "steam://rungame/730/1/+csgo_econ_action_preview%20S1A1D1",
});

function Pick({ id }: { id: string }) {
  const { select } = useSelectedOffer();
  return (
    <button
      type="button"
      onClick={() => {
        select(id);
      }}
    >
      pick
    </button>
  );
}

function hero() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinOffersProvider slug="ak">
        <Pick id="wx:2" />
        <SkinHero
          image="https://x/economy/image/ak"
          name="AK-47 | Redline"
          exterior="FT"
          rarityColor={null}
        />
      </SkinOffersProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchSkinListings).mockResolvedValue({
    degraded: false,
    items: [lot(2, "31.00", 0.2, 0), lot(1, "30.00", 0.3692, 3)],
  });
});

it("shows the cheapest offer's float, wear, stickers and inspect on the picture", async () => {
  hero();
  expect(await screen.findByText("0.3692")).toBeInTheDocument();
  expect(screen.getByText("FT")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Sticker | 2" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Осмотр/ })).toHaveAttribute(
    "href",
    expect.stringContaining("steam://"),
  );
});

it("shows the wear and no float or inspect until offers load or when there are none", async () => {
  vi.mocked(fetchSkinListings).mockResolvedValue({ degraded: false, items: [] });
  hero();
  expect(await screen.findByText("FT")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Осмотр/ })).not.toBeInTheDocument();
  expect(screen.queryByText("0.3692")).not.toBeInTheDocument();
});

it("redraws the picture for the lot the buyer picked (float, stickers)", async () => {
  hero();
  expect(await screen.findByText("0.3692")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "pick" }));
  expect(screen.getByText("0.2000")).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: "Sticker | 2" })).not.toBeInTheDocument();
});
