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

  it("sells a stock skin with where and how much", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Продал…" }));
    fireEvent.change(screen.getByLabelText("Где продал"), { target: { value: "Market.csgo" } });
    fireEvent.change(screen.getByLabelText("Сумма"), { target: { value: "70" } });
    fireEvent.click(screen.getByRole("button", { name: "$" }));
    fireEvent.click(screen.getByRole("button", { name: "Записать продажу" }));
    await waitFor(() => {
      expect(api.sellItem).toHaveBeenCalledWith("s1", {
        where: "Market.csgo",
        amount: "70",
        currency: "USD",
      });
    });
  });
});
