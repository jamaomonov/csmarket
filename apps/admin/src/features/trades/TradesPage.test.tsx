import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminTradeRow, type AdminTradesPage } from "./api";
import { TradesPage } from "./TradesPage";

import { ORDER_ROW } from "@/features/orders/fixtures";

const api = vi.hoisted(() => ({ listTrades: vi.fn() }));
vi.mock("./api", () => api);

const ROW: AdminTradeRow = {
  ...ORDER_ROW,
  trade: { status: 4, state: "offer_sent", attention_reason: null, send_until: null },
};
const FLAGGED: AdminTradeRow = {
  ...ROW,
  number: "O9",
  attention_reason: "buy_unconfirmed",
  trade: { status: null, state: "buying", attention_reason: "buy_unconfirmed", send_until: null },
};

function page(items: AdminTradeRow[], next: string | null = null): AdminTradesPage {
  return { items, counts: { active: 5, attention: 2 }, next_cursor: next };
}

function renderPage(url = "/trades") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <TradesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TradesPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("opens on «Все» and shows the counts of the other two tabs", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    expect(await screen.findByRole("link", { name: "O7K2M9QX" })).toHaveAttribute(
      "href",
      "/orders/O7K2M9QX",
    );
    expect(api.listTrades).toHaveBeenCalledWith({ view: "all" });
    expect(screen.getByRole("tab", { name: "Все" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "В пути 5" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "Требуют внимания 2" })).toBeInTheDocument();
  });

  it("requests the tab's view when it is clicked, and keeps it in the URL", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "В пути 5" }));
    await waitFor(() => {
      expect(api.listTrades).toHaveBeenCalledWith({ view: "active" });
    });
    fireEvent.click(await screen.findByRole("tab", { name: "Требуют внимания 2" }));
    await waitFor(() => {
      expect(api.listTrades).toHaveBeenCalledWith({ view: "attention" });
    });
    expect(screen.getByRole("tab", { name: "Требуют внимания 2" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("starts from ?view= and ignores an unknown one", async () => {
    api.listTrades.mockResolvedValue(page([FLAGGED]));
    renderPage("/trades?view=attention");
    await screen.findByRole("link", { name: "O9" });
    expect(api.listTrades).toHaveBeenCalledWith({ view: "attention" });
  });

  it("falls back to «Все» for an unknown view", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage("/trades?view=bogus");
    await screen.findByRole("link", { name: "O7K2M9QX" });
    expect(api.listTrades).toHaveBeenCalledWith({ view: "all" });
  });

  it("tints rows that need attention and names the reason", async () => {
    api.listTrades.mockResolvedValue(page([ROW, FLAGGED]));
    renderPage();
    const flagged = (await screen.findByRole("link", { name: "O9" })).closest("tr") as HTMLElement;
    const plain = screen.getByRole("link", { name: "O7K2M9QX" }).closest("tr") as HTMLElement;
    expect(flagged).toHaveAttribute("data-attention", "true");
    expect(plain).not.toHaveAttribute("data-attention");
    expect(within(flagged).getByTestId("order-attention")).toHaveTextContent(
      "ответ Waxpeer потерян",
    );
  });

  it("shows the order status, the trade state and the user", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    const row = (await screen.findByRole("link", { name: "O7K2M9QX" })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(row).getByTestId("order-status")).toHaveTextContent("покупаем");
    expect(within(row).getByText("предложение отправлено")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
  });

  it("says so when a tab is empty", async () => {
    api.listTrades.mockResolvedValue(page([]));
    renderPage("/trades?view=attention");
    expect(await screen.findByText("Здесь пусто.")).toBeInTheDocument();
  });

  it("pages with «Показать ещё»", async () => {
    api.listTrades
      .mockResolvedValueOnce(page([ROW], "c2"))
      .mockResolvedValueOnce(page([{ ...ROW, number: "O2" }]));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByRole("link", { name: "O2" })).toBeInTheDocument();
    expect(api.listTrades).toHaveBeenLastCalledWith({ view: "all", cursor: "c2" });
  });
});
