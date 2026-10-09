import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeyCard } from "./ApiKeyCard";
import { ORDER_ROW } from "../orders/fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  listApiKeys: vi.fn(),
  getApiKeyCard: vi.fn(),
  setApiKeyTariff: vi.fn(),
  revokeApiKey: vi.fn(),
}));
vi.mock("./api", () => api);

const KEY = {
  id: "k-1",
  user: { id: "u-1", display_name: "Acme" },
  pricing_profile: "retail",
  created_at: "2026-09-30T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
  orders: 1,
  revenue_usd: "10.000",
  cost_usd: "9.000",
};
const CARD = {
  key: KEY,
  orders: [ORDER_ROW],
  webhook: {
    host: "hooks.partner.example",
    last_delivery: {
      event: "order.paid",
      status: "failed",
      attempts: 3,
      last_status_code: 500,
      created_at: "2026-10-01T10:00:00Z",
    },
  },
};

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/api-keys/k-1"]}>
        <Routes>
          <Route path="/api-keys/:id" element={<ApiKeyCard />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ApiKeyCard", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getApiKeyCard.mockResolvedValue(CARD);
  });

  it("shows the tariff, sales, webhook host and orders linking to the order page", async () => {
    renderCard();
    expect(await screen.findByTestId("key-tariff")).toHaveTextContent("розница");
    expect(screen.getByTestId("key-webhook")).toHaveTextContent("hooks.partner.example");
    expect(screen.getByTestId("key-webhook")).toHaveTextContent("не доставлено");
    expect(screen.getByRole("link", { name: ORDER_ROW.number })).toHaveAttribute(
      "href",
      `/orders/${ORDER_ROW.number}`,
    );
  });

  it("switches the tariff only with a reason, then shows the new tariff", async () => {
    api.setApiKeyTariff.mockResolvedValue({ ...CARD, key: { ...KEY, pricing_profile: "cost" } });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Тариф: по себестоимости" }));
    const dialog = screen.getByRole("dialog", { name: "Тариф по себестоимости" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Переключить" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("причину");
    expect(api.setApiKeyTariff).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Причина"), { target: { value: "объём" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Переключить" }));
    await waitFor(() => {
      expect(api.setApiKeyTariff).toHaveBeenCalledTimes(1);
    });
    const [id, profile, reason, key] = api.setApiKeyTariff.mock.calls[0] as string[];
    expect([id, profile, reason]).toEqual(["k-1", "cost", "объём"]);
    expect((key ?? "").length).toBeGreaterThanOrEqual(16);
    await waitFor(() => {
      expect(screen.getByTestId("key-tariff")).toHaveTextContent("по себестоимости");
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("revokes the key and hides the actions", async () => {
    api.revokeApiKey.mockResolvedValue({
      ...CARD,
      key: { ...KEY, revoked_at: "2026-10-02T10:00:00Z" },
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Отозвать ключ" }));
    const dialog = screen.getByRole("dialog", { name: "Отозвать ключ" });
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "злоупотребление" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отозвать" }));
    expect(await screen.findByTestId("key-revoked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Отозвать ключ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Тариф:/ })).not.toBeInTheDocument();
  });

  it("explains a revoked-key conflict in Russian", async () => {
    api.setApiKeyTariff.mockRejectedValue(
      new ApiError(409, "Conflict", { code: "api_key_revoked", detail: "the API key is revoked" }),
    );
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Тариф: по себестоимости" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Причина"), { target: { value: "объём" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Переключить" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Ключ уже отозван.");
  });

  it("says when the key is missing", async () => {
    api.getApiKeyCard.mockRejectedValue(new ApiError(404, "Not Found", { detail: "x" }));
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("Ключ не найден.");
  });
});
