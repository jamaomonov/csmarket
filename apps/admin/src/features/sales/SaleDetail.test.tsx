import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL } from "./fixtures";
import { SaleDetail } from "./SaleDetail";

const api = vi.hoisted(() => ({ getSale: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

describe("SaleDetail", () => {
  beforeEach(() => {
    api.getSale.mockReset().mockResolvedValue(PAYOUT_DETAIL.sale);
  });

  it("shows the amounts and the items", async () => {
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
    expect(await screen.findByRole("heading", { name: "S7K2M9QX" })).toBeInTheDocument();
    expect(screen.getByText(/147\s400 сум/)).toBeInTheDocument();
    expect(screen.getByText("$12.83")).toBeInTheDocument();
    expect(screen.getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
  });
});
