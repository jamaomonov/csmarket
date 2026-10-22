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
    expect(screen.getAllByRole("switch", { name: /: включён$/ })).toHaveLength(4);
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

  it("shows the sum grouped and sends it as before: a whole number, no spaces", async () => {
    renderBlock();
    const sum = await screen.findByLabelText("Payme: сумма, сум");
    expect(sum).toHaveValue("2\u00a0000\u00a0000");
    fireEvent.change(sum, { target: { value: "3\u00a0000\u00a00000" } });
    expect(sum).toHaveValue("30\u00a0000\u00a0000");
    fireEvent.click(screen.getByRole("switch", { name: "Uzum: включён" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveReviewLimits).toHaveBeenCalledOnce();
    });
    const rows = api.saveReviewLimits.mock.calls[0]?.[0] as Record<string, unknown>[];
    expect(rows.map((r) => r.provider)).toEqual(["click", "payme", "uzum", "p2p"]);
    expect(rows).toContainEqual({
      provider: "payme",
      enabled: true,
      max_amount_uzs: 30000000,
      window_hours: 24,
    });
    expect(rows).toContainEqual({
      provider: "uzum",
      enabled: false,
      max_amount_uzs: 2000000,
      window_hours: 24,
    });
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
