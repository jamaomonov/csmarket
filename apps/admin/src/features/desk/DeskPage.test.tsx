import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeskPage } from "./DeskPage";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  getSummary: vi.fn(),
  listDeals: vi.fn(),
  addWithdrawal: vi.fn(),
}));
vi.mock("./api", () => api);

const SUMMARY = {
  profit_usd: "100",
  revenue_usd: "1200",
  deals_closed: 1,
  items_resolved: 2,
  in_transit_usd: "366.67",
  stock_usd: "54",
  skinslink_share_usd: "1175",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DeskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DeskPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => {
      if (typeof f === "function") f.mockReset();
    });
    api.getSummary.mockResolvedValue(SUMMARY);
    api.listDeals.mockResolvedValue({
      items: [
        {
          id: "d1",
          status: "closed",
          trader: "trader one",
          method: "guarantor",
          created_at: "2026-10-29T10:00:00Z",
          paid_amount: "14300000",
          paid_currency: "UZS",
          paid_usd: "1100",
          items: 2,
          profit_usd: "100",
          resolved: true,
        },
      ],
      next_cursor: null,
    });
  });

  it("shows the five figures and the deals", async () => {
    renderPage();
    const tiles = await screen.findByLabelText("Итоги");
    for (const title of [
      "Прибыль",
      "Выручка Skinslink",
      "В пути",
      "На складе",
      "Моя доля на Skinslink",
    ]) {
      expect(tiles).toHaveTextContent(title);
    }
    const link = await screen.findByRole("link", { name: /trader one/ });
    expect(link).toHaveAttribute("href", "/desk/deals/d1");
    expect(link).toHaveTextContent("закрыта");
    expect(link).toHaveTextContent("через гаранта");
  });

  it("asks for the chosen period", async () => {
    renderPage();
    await screen.findByLabelText("Итоги");
    fireEvent.click(screen.getByRole("tab", { name: "7 дней" }));
    await waitFor(() => {
      expect(api.getSummary).toHaveBeenCalledTimes(2);
    });
  });

  it("records «Вывел себе»", async () => {
    api.addWithdrawal.mockResolvedValue({ id: "w1", amount_usd: "25", note: null, at: "" });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Вывел себе" }));
    fireEvent.change(screen.getByLabelText("Сколько вывел, $"), { target: { value: "25,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Записать" }));
    await waitFor(() => {
      expect(api.addWithdrawal).toHaveBeenCalledWith("25.5", undefined);
    });
  });
});
