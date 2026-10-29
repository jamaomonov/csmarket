import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DealPage } from "./DealPage";
import { deal, item } from "./fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  getDeal: vi.fn(),
  patchDeal: vi.fn(),
  sendDeposit: vi.fn(),
  sellItem: vi.fn(),
  moveItem: vi.fn(),
  writeOff: vi.fn(),
  getRate: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/desk/deals/d1"]}>
        <Routes>
          <Route path="/desk/deals/:id" element={<DealPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DealPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => {
      if (typeof f === "function") f.mockReset();
    });
    api.getDeal.mockResolvedValue(deal());
    api.getRate.mockResolvedValue({ usd_uzs: "13000" });
  });

  it("sends the offer and shows the protection end", async () => {
    api.sendDeposit.mockResolvedValue(
      deal({
        status: "received",
        items: [item({ state: "sent", deposit_id: "x" })],
        deposits: [
          {
            id: "x",
            status: "hold",
            amount_usd: "1200",
            amount_estimated: false,
            trade_offer_id: "6912345678",
            offer_expiry_at: null,
            hold_end_date: null,
            fail_reason: null,
            accepted_at: "2026-10-29T10:00:00Z",
            credited_at: null,
            reverted_at: null,
            created_at: "2026-10-29T09:00:00Z",
          },
        ],
        protected_until: "2026-11-05T10:00:00Z",
      }),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отправить обмен" }));
    await waitFor(() => {
      expect(api.sendDeposit).toHaveBeenCalledWith("d1");
    });
    expect(await screen.findByText(/защита до/)).toBeInTheDocument();
    expect(screen.getByText(/принят, холд Steam/)).toBeInTheDocument();
  });

  it("says when Skinslink's prices moved", async () => {
    api.sendDeposit.mockRejectedValue(new ApiError(409, "Conflict", { code: "prices_moved" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отправить обмен" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Цены Skinslink изменились");
  });

  it("shows a red banner on a revert", async () => {
    api.getDeal.mockResolvedValue(deal({ status: "reverted", profit_usd: "-1100" }));
    renderPage();
    expect(await screen.findByText(/Трейдер откатил обмен/)).toBeInTheDocument();
  });

  it("moves an item to stock", async () => {
    api.moveItem.mockResolvedValue(deal());
    renderPage();
    const [first] = await screen.findAllByRole("button", { name: "Себе" });
    if (first) fireEvent.click(first);
    await waitFor(() => {
      expect(api.moveItem).toHaveBeenCalledWith("i1", "stock");
    });
  });
});
