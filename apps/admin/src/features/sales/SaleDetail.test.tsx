import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL, PAYOUT_ROW } from "./fixtures";
import { SaleDetail } from "./SaleDetail";

const api = vi.hoisted(() => ({ getSale: vi.fn(), resolveSale: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

describe("SaleDetail", () => {
  beforeEach(() => {
    api.getSale.mockReset().mockResolvedValue(PAYOUT_DETAIL.sale);
  });

  function renderPage() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/sales/S7K2M9QX"]}>
          <Routes>
            <Route path="/sales/:number" element={<SaleDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("shows the amounts and the items", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Продажа S7K2M9QX" })).toBeInTheDocument();
    expect(screen.getByText(/147\s400 сум/)).toBeInTheDocument();
    expect(screen.getByText(/^12\s650,5\sсум за \$$/)).toBeInTheDocument();
    expect(screen.getByText("$12.83")).toBeInTheDocument();
    expect(screen.getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
  });

  it("the payout chip is a link to the payout request", async () => {
    api.getSale.mockResolvedValue({
      ...PAYOUT_DETAIL.sale,
      status: "payout",
      payout: { ...PAYOUT_ROW, status: "to_pay" },
    });
    renderPage();
    const link = await screen.findByTestId("sale-payout-link");
    expect(link).toHaveAttribute("href", `/payouts/${PAYOUT_ROW.id}`);
    expect(link).toHaveTextContent("к выплате");
  });

  it("«Проверено» resolves an open attention with the note", async () => {
    const flagged = {
      ...PAYOUT_DETAIL.sale,
      attention_reason: "rolled_back",
      attention_open: true,
    };
    api.getSale.mockResolvedValue(flagged);
    api.resolveSale.mockResolvedValue({
      ...flagged,
      attention_open: false,
      resolved_at: "2026-10-12T10:00:00Z",
      resolved_by: { id: "a-1", display_name: "Owner" },
      resolved_note: "написал продавцу",
    });
    renderPage();
    expect(await screen.findByText(/Требует внимания: откат после выплаты/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Что сделали (необязательно)"), {
      target: { value: "написал продавцу" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверено" }));
    await waitFor(() => {
      expect(api.resolveSale).toHaveBeenCalledWith(
        "S7K2M9QX",
        "написал продавцу",
        expect.stringMatching(/^admin-sale-resolve-/),
      );
    });
    expect(await screen.findByText(/Проверено: откат после выплаты/)).toBeInTheDocument();
  });
});
