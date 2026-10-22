import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type ReconPage } from "./reconApi";
import { ReconciliationPage } from "./ReconciliationPage";

const api = vi.hoisted(() => ({ getReconciliation: vi.fn() }));
vi.mock("./reconApi", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

const PAGE: ReconPage = {
  items: [
    {
      number: "S7K2M9QX",
      status: "credited",
      done_at: "2026-10-13T06:00:00Z",
      trade_id: 123,
      quoted_usd: "12.95",
      amount_usd: "12",
      diff_usd: "-0.95",
      flag: "short",
    },
    {
      number: "S4H8P2RT",
      status: "credited",
      done_at: "2026-10-13T05:00:00Z",
      trade_id: 124,
      quoted_usd: "12.95",
      amount_usd: "12.95",
      diff_usd: "0",
      flag: null,
    },
  ],
  next_cursor: null,
  expected_usd: "25.9",
  credited_usd: "24.95",
  diff_usd: "-0.95",
  problems: 1,
};

function renderPage(path = "/sales/reconciliation") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <ReconciliationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReconciliationPage", () => {
  beforeEach(() => {
    api.getReconciliation.mockReset();
    api.getReconciliation.mockResolvedValue(PAGE);
  });

  it("shows the totals and flags a short credit", async () => {
    renderPage();
    expect((await screen.findAllByText("S7K2M9QX")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Недозачислено").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Итоги")).toHaveTextContent("Проблемы1");
    expect(api.getReconciliation).toHaveBeenCalledWith({ days: 7, problems: false });
  });

  it("asks for the problems only and another period", async () => {
    renderPage("/sales/reconciliation?days=30");
    expect(await screen.findByRole("tab", { name: "Все" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Проблемы 1" }));
    await waitFor(() => {
      expect(api.getReconciliation).toHaveBeenLastCalledWith({ days: 30, problems: true });
    });
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("an old ?problems=1 link opens the «Проблемы» tab", async () => {
    renderPage("/sales/reconciliation?problems=1");
    expect(await screen.findByRole("tab", { name: "Проблемы 1" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(api.getReconciliation).toHaveBeenCalledWith({ days: 7, problems: true });
  });

  it("keeps the «Проблемы» count while the other tab loads", async () => {
    renderPage();
    await screen.findByRole("tab", { name: "Проблемы 1" });
    api.getReconciliation.mockReturnValue(new Promise(() => undefined));
    fireEvent.click(screen.getByRole("tab", { name: "Проблемы 1" }));
    await waitFor(() => {
      expect(api.getReconciliation).toHaveBeenLastCalledWith({ days: 7, problems: true });
    });
    expect(screen.getByRole("tab", { name: "Проблемы 1" })).toBeInTheDocument();
  });
});
