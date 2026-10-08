// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TradesView, type TradesType } from "./TradesView";

import type * as OrdersModule from "@/lib/orders";
import type * as SalesModule from "@/lib/sales";

import { orderOut, tradeOut } from "@/test/orders";
import { saleItem, saleOut } from "@/test/sales";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({ listOrders: vi.fn(), listSales: vi.fn() }));
vi.mock("@/lib/orders", async (importOriginal) => ({
  ...(await importOriginal<typeof OrdersModule>()),
  listOrders: api.listOrders,
}));
vi.mock("@/lib/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof SalesModule>()),
  listSales: api.listSales,
}));

function view(type: TradesType) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }} timeZone="UTC">
        <TradesView locale="ru" type={type} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const page = <T,>(items: T[]) => ({ items, next_cursor: null });

describe("TradesView", () => {
  beforeEach(() => {
    api.listOrders.mockReset().mockResolvedValue(page([]));
    api.listSales.mockReset().mockResolvedValue(page([]));
    auth.value = { status: "signed_in", user: { id: "u1" }, signInHref: () => "/auth" };
  });

  it("filters: all, purchases, sales, on hold", () => {
    view("all");
    const names = ["Все", "Покупки", "Продажи", "В холде"];
    const links = names.map((name) => screen.getByRole("link", { name }));
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/account/trades",
      "/account/trades?type=purchases",
      "/account/trades?type=sales",
      "/account/trades?type=hold",
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
  });

  it("shows purchases and sales as one list, newest first", async () => {
    api.listOrders.mockResolvedValue(
      page([
        orderOut("03TVB3PM", {
          status: "trade_sent",
          paid_at: "2026-10-08T15:50:00Z",
          paid_with: "wallet",
          price_uzs: "1200",
          created_at: "2026-10-08T15:50:00Z",
          trade: tradeOut({ state: "accepted" }),
        }),
      ]),
    );
    api.listSales.mockResolvedValue(
      page([saleOut("SKMBK33X", { items: [saleItem("1"), saleItem("2"), saleItem("3")] })]),
    );
    view("all");
    const rows = await screen.findAllByRole("link", { name: /#/ });
    expect(rows.map((r) => r.getAttribute("href"))).toEqual([
      "/account/sales/SKMBK33X",
      "/orders/03TVB3PM",
    ]);
    const [sale, order] = rows;
    if (!sale || !order) throw new Error("two rows expected");
    expect(within(sale).getByText("+2")).toBeInTheDocument();
    expect(within(sale).getByText(/\+10\s900/)).toBeInTheDocument();
    expect(within(sale).getByText("Деньги придут 15 окт.")).toBeInTheDocument();
    expect(within(order).getByText(/−1\s200/)).toBeInTheDocument();
    // A trade accepted in Steam reads «Получен», though the order still says trade_sent.
    expect(within(order).getByText("Получен")).toBeInTheDocument();
    expect(within(order).getByText("с баланса")).toBeInTheDocument();
  });

  it("asks only for the sales on hold on the hold tab", async () => {
    view("hold");
    expect(await screen.findByText("Сейчас ничего не ждёт зачисления.")).toBeInTheDocument();
    expect(api.listSales).toHaveBeenCalledWith(undefined, "hold");
    expect(api.listOrders).not.toHaveBeenCalled();
  });

  it("purchases do not ask for sales", async () => {
    view("purchases");
    expect(await screen.findByText("Обменов пока нет.")).toBeInTheDocument();
    expect(api.listSales).not.toHaveBeenCalled();
  });

  it("asks a visitor to sign in", () => {
    auth.value = { status: "signed_out", user: null, signInHref: () => "/auth" };
    view("all");
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
      "href",
      "/auth",
    );
    expect(api.listOrders).not.toHaveBeenCalled();
  });
});
