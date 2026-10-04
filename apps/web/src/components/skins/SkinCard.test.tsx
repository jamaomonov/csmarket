// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import messages from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { SkinCard } from "./SkinCard";

import type { SkinItem } from "@csmarket/utils/skins";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const item: SkinItem = {
  slug: "ak-47-redline-field-tested",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: "Redline",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  rarity: "Classified",
  rarity_color: "#d32ce6",
  image_url: "https://community.fastly.steamstatic.com/economy/image/x",
  price_usd: "30.37",
  price_uzs: "385700",
  steam_price_usd: "43.794",
  discount_percent: 31,
  count: 49,
  min_float: "0.1",
  max_float: "0.7",
};

function renderCard(over: Partial<SkinItem> = {}) {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinCard item={{ ...item, ...over }} locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("SkinCard", () => {
  it("shows skin, weapon, wear, price in som and discount", () => {
    renderCard();
    expect(screen.getByText("Redline")).toBeInTheDocument();
    expect(screen.getByText(/AK-47/)).toBeInTheDocument();
    expect(screen.getByText("FT")).toBeInTheDocument();
    expect(screen.getByText(/385\s?700/)).toBeInTheDocument();
    // The lot count read as noise on a card («×84077»); the item page has it.
    expect(screen.queryByText("×49")).not.toBeInTheDocument();
    expect(screen.getByText("−31%")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/item/ak-47-redline-field-tested");
  });

  it("marks StatTrak and hides a missing discount", () => {
    renderCard({ stattrak: true, discount_percent: null });
    expect(screen.getByText("ST™")).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it("says sold out without a price", () => {
    renderCard({ price_uzs: null, price_usd: null, count: 0 });
    expect(screen.getByText("Нет в наличии")).toBeInTheDocument();
  });
  it("variant B: wear, ST™, pieces, discount badge, green price and the Steam line", () => {
    renderCard({ discount_percent: 19, exterior: "MW", count: 3, stattrak: true });
    const card = screen.getByRole("link");
    expect(within(card).getByText("MW")).toBeInTheDocument();
    expect(within(card).getByText("ST™")).toBeInTheDocument();
    expect(within(card).getByText("3 шт.")).toBeInTheDocument();
    expect(within(card).getByText("−19%")).toBeInTheDocument();
    expect(within(card).getByText("Steam дороже на 19%")).toBeInTheDocument();
    expect(card.querySelector(".text-accent.num")).not.toBeNull();
  });

  it("no Steam line and no badge under 5 %", () => {
    renderCard({ discount_percent: 3 });
    expect(screen.queryByText(/Steam дороже/)).toBeNull();
    expect(screen.queryByText("−3%")).toBeNull();
  });
});

describe("SkinCard badges and names", () => {
  it("shows a discount only from 5 %", () => {
    renderCard({ discount_percent: 4 });
    expect(screen.queryByText("−4%")).not.toBeInTheDocument();
  });

  it("calls a vanilla knife vanilla instead of repeating its name", () => {
    renderCard({
      name: "★ Karambit",
      category: "knives",
      weapon: "Karambit",
      skin: null,
      exterior: null,
    });
    expect(screen.getByText("Ванильный")).toBeInTheDocument();
    expect(screen.queryByText("★ Karambit")).not.toBeInTheDocument();
  });
});

describe("SkinCard without an FX rate", () => {
  it("shows the dollar price instead of calling an in-stock item sold out", () => {
    renderCard({ price_uzs: null, price_usd: "30.37" });
    expect(screen.getByText("$30.37")).toBeInTheDocument();
    expect(screen.queryByText("Нет в наличии")).not.toBeInTheDocument();
  });
});
