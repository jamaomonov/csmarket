// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrdersList } from "./OrdersList";

import type { OrdersPage } from "@/lib/orders";
import type { ReactNode } from "react";

import { orderOut, tradeOut } from "@/test/orders";

const m = vi.hoisted(() => ({
  auth: { value: {} },
  list: vi.fn<(path: string) => Promise<OrdersPage>>(),
}));

vi.mock("@/lib/api", () => ({
  session: {
    apiGet: (path: string) =>
      path.startsWith("/api/v1/me/orders")
        ? m.list(path)
        : Promise.reject(new Error(`unexpected GET ${path}`)),
  },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => m.auth.value }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <OrdersList locale="ru" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  m.list.mockReset();
  m.auth.value = {
    status: "signed_in",
    user: { id: "u1" },
    signInHref: (l: string) => `/s?l=${l}`,
  };
});

describe("OrdersList", () => {
  it("lists orders as cards: skin, status, price, number and date, each a link to its page", async () => {
    m.list.mockResolvedValue({
      items: [
        orderOut("A2", {
          status: "delivered",
          payable: false,
          name: "AWP | Asiimov (Field-Tested)",
          image_url: "https://community.fastly.steamstatic.com/economy/image/abc",
          trade: tradeOut({ state: "accepted" }),
        }),
        orderOut("A1", { status: "trade_sent", payable: false, price_uzs: "1250000" }),
      ],
      next_cursor: null,
    });
    view();
    const cards = await screen.findAllByTestId("order-card");
    expect(cards).toHaveLength(2);
    const [first, second] = cards;
    if (!first || !second) throw new Error("two cards");
    expect(first).toHaveAttribute("href", "/orders/A2");
    expect(first).toHaveAttribute("data-state", "delivered");
    expect(within(first).getByText("AWP | Asiimov (Field-Tested)")).toBeInTheDocument();
    expect(within(first).getByText("Получен")).toBeInTheDocument();
    expect(within(first).getByText(/^381\s000 сум$/)).toBeInTheDocument();
    expect(within(first).getByText(/Заказ #A2/)).toBeInTheDocument();
    expect(first.querySelector("time")).toHaveAttribute("datetime", "2026-10-02T10:00:00Z");
    expect(first.querySelector("img")).not.toBeNull();
    expect(second).toHaveAttribute("href", "/orders/A1");
    expect(within(second).getByText("Обмен отправлен")).toBeInTheDocument();
    expect(within(second).getByText(/^1\s250\s000 сум$/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
    expect(m.list).toHaveBeenCalledWith("/api/v1/me/orders");
  });

  it("loads the next page by cursor behind «Показать ещё»", async () => {
    m.list
      .mockResolvedValueOnce({ items: [orderOut("A3")], next_cursor: "cur 2" })
      .mockResolvedValueOnce({ items: [orderOut("A2")], next_cursor: null });
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    await waitFor(() => {
      expect(screen.getAllByTestId("order-card")).toHaveLength(2);
    });
    expect(m.list).toHaveBeenLastCalledWith("/api/v1/me/orders?cursor=cur%202");
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("with no orders yet points to the catalogue", async () => {
    m.list.mockResolvedValue({ items: [], next_cursor: null });
    view();
    expect(await screen.findByText("Заказов пока нет.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "В каталог" })).toHaveAttribute("href", "/");
  });

  it("an outage offers a retry", async () => {
    m.list
      .mockRejectedValueOnce(new SessionApiError(500, "Internal", null))
      .mockResolvedValue({ items: [], next_cursor: null });
    view();
    fireEvent.click(await screen.findByRole("button", { name: "Обновить" }));
    expect(await screen.findByText("Заказов пока нет.")).toBeInTheDocument();
  });

  it("signed out: a way to sign in, and nothing is asked for", () => {
    m.auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/s?l=${l}` };
    view();
    expect(screen.getByText("Войдите через Steam, чтобы открыть заказы.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
      "href",
      "/s?l=ru",
    );
    expect(m.list).not.toHaveBeenCalled();
  });
});
