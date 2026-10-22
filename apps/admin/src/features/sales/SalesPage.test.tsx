import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
          attention_reason: "rolled_back",
          attention_open: true,
          created_at: s.created_at,
          first_item: { name: "AK-47 | Redline (Field-Tested)", image_url: null },
          items_count: 2,
        },
      ],
      next_cursor: null,
      attention_open: 2,
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
    expect(screen.getByRole("tab", { name: "Ждут проверки 2" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.getByRole("tab", { name: "Все" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("searchbox")).not.toHaveClass("font-mono");
    expect(screen.getByTestId("sale-first-skin")).toHaveTextContent(
      "AK-47 | Redline (Field-Tested)+1",
    );
    expect(screen.getByRole("link", { name: "S7K2M9QX" })).toHaveClass("text-accent");
  });

  it("filters by the attention from the URL", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/sales?attention=open"]}>
          <SalesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByRole("link", { name: "S7K2M9QX" });
    expect(api.listSales).toHaveBeenCalledWith({ attention: "open" });
    expect(screen.getByRole("tab", { name: "Ждут проверки 2" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("a tab filters by the attention, the status stays a select", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <SalesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Проверены" }));
    await waitFor(() => {
      expect(api.listSales).toHaveBeenCalledWith({ attention: "resolved" });
    });
    fireEvent.change(screen.getByLabelText("Статус"), { target: { value: "credited" } });
    await waitFor(() => {
      expect(api.listSales).toHaveBeenCalledWith({ status: "credited", attention: "resolved" });
    });
  });
});
