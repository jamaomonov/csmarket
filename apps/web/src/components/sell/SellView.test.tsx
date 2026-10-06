// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SellView } from "./SellView";

import type { SellItem } from "@/lib/sell";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/lib/api", () => ({ session: { apiPut: vi.fn(), apiPost: vi.fn() } }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const item = (over: Partial<SellItem>): SellItem => ({
  assetId: "1",
  slug: "ak",
  name: "AK-47 | Redline (Field-Tested)",
  category: "rifles",
  weapon: "AK-47",
  skin: "Redline",
  exterior: "FT",
  stattrak: false,
  imageUrl: "https://img.test/ak.png",
  rarityColor: "#d32ce6",
  priceUzs: 300_000,
  unavailable: null,
  ...over,
});

const INVENTORY: SellItem[] = [
  item({}),
  item({
    assetId: "2",
    slug: "awp",
    name: "AWP | Asiimov (Field-Tested)",
    weapon: "AWP",
    skin: "Asiimov",
    priceUzs: 900_000,
  }),
  item({
    assetId: "3",
    slug: "knife",
    name: "★ Karambit | Fade",
    category: "knives",
    weapon: "Karambit",
    skin: "Fade",
    priceUzs: 9_000_000,
    unavailable: { reason: "tradeLock", until: "2026-10-12T00:00:00Z" },
  }),
];

const plain = (s: string | null | undefined) => (s ?? "").replace(/\s/g, " ");

function view() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }} timeZone="UTC">
      <SellView locale="ru" inventory={INVENTORY} />
    </NextIntlClientProvider>,
  );
}

const signedIn = {
  status: "signed_in",
  signInHref: () => "",
  refreshMe: vi.fn(),
  user: {
    trade_link: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=Fake1234",
    trade_link_verdict: "ok",
    trade_link_reason: null,
  },
};

describe("SellView", () => {
  beforeEach(() => {
    auth.value = signedIn;
  });

  it("shows the inventory with its total, the unavailable item says why", () => {
    view();
    expect(plain(screen.getByText(/предмета на/).textContent)).toContain(
      "3 предмета на 10 200 000 сум",
    );
    expect(screen.getByText("доступно 2")).toBeInTheDocument();
    expect(screen.getByText("Обмен с 12 окт.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Karambit/ })).toBeDisabled();
  });

  it("picking skins fills the cart; a cross takes one out", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: /AK-47/ }));
    fireEvent.click(screen.getByRole("button", { name: /AWP/ }));
    expect(screen.getByRole("button", { name: /AK-47/, pressed: true })).toBeInTheDocument();
    const cart = screen.getByRole("complementary", { name: /Выбрано 2 скина/ });
    expect(within(cart).getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(within(cart).getByRole("button", { name: /Убрать AWP/ }));
    expect(screen.getByRole("complementary", { name: /Выбран 1 скин/ })).toBeInTheDocument();
  });

  it("«Выбрать все» takes only the available ones", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: "Выбрать все" }));
    expect(screen.getByRole("complementary", { name: /Выбрано 2 скина/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Снять выбор" })).toBeInTheDocument();
  });

  it("the balance pays a bonus, a card pays the fee and needs its number", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: /AK-47/ }));
    const payout = () => plain(screen.getByTestId("sell-payout").textContent);
    expect(payout()).toBe("306 000 сум"); // +2 %
    fireEvent.click(screen.getByRole("radio", { name: /Uzcard/ }));
    expect(payout()).toBe("285 000 сум"); // −5 %
    const card = screen.getByLabelText("Номер карты Uzcard");
    fireEvent.change(card, { target: { value: "9860123456781234" } });
    expect(card).toHaveValue("9860 1234 5678 1234");
    expect(screen.getByText("Это не карта Uzcard")).toBeInTheDocument();
  });

  it("selling is not open yet: the button says so", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: /AK-47/ }));
    expect(screen.getByRole("button", { name: "Продажа скоро откроется" })).toBeDisabled();
  });

  it("search and category narrow the grid", () => {
    view();
    fireEvent.change(screen.getByPlaceholderText("Поиск по названию"), {
      target: { value: "awp" },
    });
    expect(screen.queryByRole("button", { name: /AK-47/ })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Поиск по названию"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Ножи" }));
    expect(screen.queryByRole("button", { name: /AWP/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Karambit/ })).toBeInTheDocument();
  });

  it("without a trade link it asks for one; signed out it asks to sign in", () => {
    auth.value = {
      ...signedIn,
      user: { trade_link: null, trade_link_verdict: null, trade_link_reason: null },
    };
    view();
    expect(screen.getByText(/Добавьте ссылку на обмен/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /AK-47/ })).toBeNull();
  });
});
