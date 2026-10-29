import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { deal, item } from "./fixtures";
import { StockPage } from "./StockPage";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  listStock: vi.fn(),
  sellItem: vi.fn(),
  getRate: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <StockPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StockPage", () => {
  beforeEach(() => {
    api.listStock.mockReset().mockResolvedValue({
      items: [
        {
          ...item({ id: "s1", destination: "stock", cost_usd: "54" }),
          deal_id: "d1",
          trader: "trader one",
          bought_at: "2026-10-20T10:00:00Z",
        },
      ],
      total_cost_usd: "54",
    });
    api.sellItem.mockReset().mockResolvedValue(deal());
    api.getRate.mockReset().mockResolvedValue({ usd_uzs: "13000" });
  });

  it("sells a stock skin in dollars and previews the profit", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Продажа…" }));
    fireEvent.change(screen.getByLabelText("Где продано"), { target: { value: "Market.csgo" } });
    fireEvent.click(screen.getByRole("button", { name: "$" }));
    fireEvent.change(screen.getByLabelText("Сумма, $"), { target: { value: "70" } });
    expect(
      screen.getByText((_, el) => el?.tagName === "P" && el.textContent.includes("Прибыль: +$16")),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Записать продажу" }));
    await waitFor(() => {
      expect(api.sellItem).toHaveBeenCalledWith("s1", {
        where: "Market.csgo",
        amount: "70",
        currency: "USD",
      });
    });
  });

  it("takes a rate typed with a space and a comma", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Продажа…" }));
    fireEvent.change(screen.getByLabelText("Где продано"), { target: { value: "Buff" } });
    fireEvent.change(screen.getByLabelText("Сумма, сум"), { target: { value: "910000" } });
    fireEvent.change(screen.getByLabelText("Курс (ЦБ на сегодня)"), {
      target: { value: "12 650,5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Записать продажу" }));
    await waitFor(() => {
      expect(api.sellItem).toHaveBeenCalledWith("s1", {
        where: "Buff",
        amount: "910000",
        currency: "UZS",
        rate: "12650.5",
      });
    });
  });

  it("an empty stock says where skins come from", async () => {
    api.listStock.mockResolvedValue({ items: [], total_cost_usd: "0" });
    renderPage();
    expect(await screen.findByText(/Сюда попадают скины, отмеченные «Себе»/)).toBeInTheDocument();
  });
});
