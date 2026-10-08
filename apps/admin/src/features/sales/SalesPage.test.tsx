import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL } from "./fixtures";
import { SalesPage } from "./SalesPage";

const api = vi.hoisted(() => ({ listSales: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

describe("SalesPage", () => {
  beforeEach(() => {
    const s = PAYOUT_DETAIL.sale;
    api.listSales.mockReset().mockResolvedValue({
      items: [
        {
          number: s.number,
          status: s.status,
          user: s.user,
          payout_to: s.payout_to,
          quoted_usd: s.quoted_usd,
          payout_uzs: s.payout_uzs,
          margin_usd: s.margin_usd,
          attention_reason: null,
          created_at: s.created_at,
        },
      ],
      next_cursor: null,
    });
  });

  it("lists the sales", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <SalesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "S7K2M9QX" })).toHaveAttribute(
      "href",
      "/sales/S7K2M9QX",
    );
    expect(screen.getAllByText("выплата на карту").length).toBeGreaterThan(1); // row + filter option
    expect(screen.getByText(/147\s400 сум/)).toBeInTheDocument();
  });
});
