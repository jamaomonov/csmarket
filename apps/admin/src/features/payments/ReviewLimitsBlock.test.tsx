import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FeeSettingsPage } from "./FeeSettingsPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getReviewLimits: vi.fn(),
  saveReviewLimits: vi.fn(),
  getFeeSettings: vi.fn(),
  saveFeeSettings: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const row = (provider: string) => ({
  provider,
  enabled: true,
  max_amount_uzs: "2000000",
  window_hours: 24,
});
const SAVED = {
  limits: ["payme", "click", "uzum", "p2p"].map(row),
  updated_at: "2026-10-21T10:00:00.123456Z",
  updated_by: null,
};

function renderBlock() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FeeSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReviewLimitsBlock (on «Настройки оплаты»)", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getReviewLimits.mockResolvedValue(SAVED);
    api.saveReviewLimits.mockResolvedValue(SAVED);
    api.getFeeSettings.mockResolvedValue({
      settings: { click: "0", payme: "0", uzum: "0", statuses: {} },
      updated_at: null,
      updated_by: null,
    });
  });

  it("renders a row per kassa", async () => {
    renderBlock();
    expect(await screen.findByText("Лимит без проверки")).toBeInTheDocument();
    for (const name of ["Payme", "Click", "Uzum", "Перевод на карту (P2P)"]) {
      expect(screen.getByLabelText(`${name}: сумма, сум`)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("checkbox", { name: /: включён$/ })).toHaveLength(4);
  });

  it("saves the edited row with the version and a key", async () => {
    renderBlock();
    fireEvent.change(await screen.findByLabelText("Click: сумма, сум"), {
      target: { value: "500000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveReviewLimits).toHaveBeenCalledOnce();
    });
    const [rows, version, key] = api.saveReviewLimits.mock.calls[0] as [
      Record<string, unknown>[],
      string | null,
      string,
    ];
    expect(rows).toHaveLength(4);
    expect(rows).toContainEqual({
      provider: "click",
      enabled: true,
      max_amount_uzs: 500000,
      window_hours: 24,
    });
    expect(version).toBe("2026-10-21T10:00:00.123456Z");
    expect(key).toMatch(/^admin-review-limits-/);
  });

  it("refuses a sum that is not a whole number before sending it", async () => {
    renderBlock();
    fireEvent.change(await screen.findByLabelText("Uzum: сумма, сум"), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("целое число");
    expect(api.saveReviewLimits).not.toHaveBeenCalled();
  });

  it("says a stale tab was overwritten", async () => {
    api.saveReviewLimits.mockRejectedValue(
      new ApiError(409, "conflict", { code: "settings_stale" }),
    );
    renderBlock();
    fireEvent.change(await screen.findByLabelText("Payme: окно, ч"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("сохранил кто-то другой");
  });
});
