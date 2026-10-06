// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { TradesView } from "./TradesView";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/account/OrdersList", () => ({ OrdersList: () => <p>orders-list</p> }));

function view(type: "all" | "purchases" | "sales") {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <TradesView locale="ru" type={type} />
    </NextIntlClientProvider>,
  );
}

describe("TradesView", () => {
  it("filters: all, purchases, sales", () => {
    view("all");
    const links = ["Все", "Покупки", "Продажи"].map((name) => screen.getByRole("link", { name }));
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/account/trades",
      "/account/trades?type=purchases",
      "/account/trades?type=sales",
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("orders-list")).toBeInTheDocument();
  });

  it("purchases are the orders", () => {
    view("purchases");
    expect(screen.getByText("orders-list")).toBeInTheDocument();
  });

  it("sales: none yet", () => {
    view("sales");
    expect(screen.queryByText("orders-list")).toBeNull();
    expect(screen.getByText("Продаж пока нет.")).toBeInTheDocument();
  });
});
