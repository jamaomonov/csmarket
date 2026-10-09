import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeysPage } from "./ApiKeysPage";

const api = vi.hoisted(() => ({
  listApiKeys: vi.fn(),
  getApiKeyCard: vi.fn(),
  setApiKeyTariff: vi.fn(),
  revokeApiKey: vi.fn(),
}));
vi.mock("./api", () => api);

const ROW = {
  id: "k-1",
  user: { id: "u-1", display_name: "Acme" },
  pricing_profile: "retail",
  created_at: "2026-09-30T10:00:00Z",
  last_used_at: "2026-10-01T10:00:00Z",
  revoked_at: null,
  orders: 3,
  revenue_usd: "30.500",
  cost_usd: "31.250",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ApiKeysPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ApiKeysPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("lists keys with orders, revenue, cost and the revoked badge", async () => {
    api.listApiKeys.mockResolvedValue({
      items: [
        ROW,
        {
          ...ROW,
          id: "k-2",
          user: { id: "u-2", display_name: null },
          revoked_at: "2026-10-02T10:00:00Z",
        },
      ],
      next_cursor: null,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: "Acme" });
    expect(link).toHaveAttribute("href", "/api-keys/k-1");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("розница")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(within(row).getByText(/30[.,]500/)).toBeInTheDocument();
    expect(within(row).getByText(/31[.,]250/)).toBeInTheDocument();
    expect(screen.getByText("отозван")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Без имени" })).toHaveAttribute(
      "href",
      "/api-keys/k-2",
    );
    expect(api.listApiKeys).toHaveBeenCalledWith({});
  });

  it("searches by owner name", async () => {
    api.listApiKeys.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage();
    await screen.findByRole("link", { name: "Acme" });
    fireEvent.change(screen.getByLabelText("Имя владельца"), { target: { value: " acm " } });
    await waitFor(() => {
      expect(api.listApiKeys).toHaveBeenLastCalledWith({ q: "acm" });
    });
  });

  it("says so when there are no keys", async () => {
    api.listApiKeys.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    expect(await screen.findByText("Ключей нет.")).toBeInTheDocument();
  });

  it("loads the next page", async () => {
    api.listApiKeys.mockResolvedValueOnce({ items: [ROW], next_cursor: "c1" });
    api.listApiKeys.mockResolvedValueOnce({
      items: [{ ...ROW, id: "k-3", user: { id: "u-3", display_name: "Beta" } }],
      next_cursor: null,
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByRole("link", { name: "Beta" })).toBeInTheDocument();
    expect(api.listApiKeys).toHaveBeenLastCalledWith({ cursor: "c1" });
  });
});
