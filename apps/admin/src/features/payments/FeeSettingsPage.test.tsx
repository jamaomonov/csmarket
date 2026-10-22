import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FeeSettingsPage } from "./FeeSettingsPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getFeeSettings: vi.fn(),
  saveFeeSettings: vi.fn(),
  getReviewLimits: vi.fn(),
  saveReviewLimits: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const SAVED = {
  settings: { click: "1", payme: "0", uzum: "0", statuses: {} },
  updated_at: "2026-10-14T10:00:00.123456Z",
  updated_by: { id: "u1", display_name: "Owner" },
};

const LIMITS = {
  limits: ["payme", "click", "uzum", "p2p"].map((provider) => ({
    provider,
    enabled: true,
    max_amount_uzs: "2000000",
    window_hours: 24,
  })),
  updated_at: null,
  updated_by: null,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FeeSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FeeSettingsPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getFeeSettings.mockResolvedValue(SAVED);
    api.saveFeeSettings.mockResolvedValue(SAVED);
    api.getReviewLimits.mockResolvedValue(LIMITS);
    api.saveReviewLimits.mockResolvedValue(LIMITS);
  });

  it("saves the edited rates with the version and a key", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Комиссия Payme, %"), {
      target: { value: "1.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveFeeSettings).toHaveBeenCalledOnce();
    });
    const [doc, version, key] = api.saveFeeSettings.mock.calls[0] as [
      Record<string, string>,
      string | null,
      string,
    ];
    expect(doc).toEqual({ click: "1", payme: "1.5", uzum: "0", statuses: {} });
    expect(version).toBe("2026-10-14T10:00:00.123456Z");
    expect(key).toMatch(/^admin-fee-settings-/);
  });

  it("switches a kassa to maintenance and P2P on, saved with the fees", async () => {
    renderPage();
    const payme = await screen.findByRole("tablist", { name: "Payme: состояние" });
    fireEvent.click(within(payme).getByRole("tab", { name: "Тех. работы" }));
    const p2p = screen.getByRole("tablist", { name: "Перевод на карту (P2P): состояние" });
    expect(within(p2p).getByRole("tab", { name: "Выключен" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.click(within(p2p).getByRole("tab", { name: "Работает" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveFeeSettings).toHaveBeenCalledOnce();
    });
    const [doc] = api.saveFeeSettings.mock.calls[0] as [{ statuses: Record<string, string> }];
    expect(doc.statuses).toEqual({ payme: "maintenance", p2p: "on" });
  });

  it("refuses a rate that is not 0–10 before sending it", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Комиссия Click, %"), {
      target: { value: "12" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("от 0 до 10");
    expect(api.saveFeeSettings).not.toHaveBeenCalled();
  });

  it("says a stale tab was overwritten by someone else", async () => {
    api.saveFeeSettings.mockRejectedValue(
      new ApiError(409, "conflict", { code: "settings_stale" }),
    );
    renderPage();
    fireEvent.change(await screen.findByLabelText("Комиссия Uzum, %"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("сохранил кто-то другой");
  });

  it("has one save bar for the fees and the limits, shown only when changed", async () => {
    renderPage();
    await screen.findByText("Лимит без проверки");
    expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Комиссия Payme, %"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Click: окно, ч"), { target: { value: "12" } });
    expect(screen.getByText("Изменено: 2 поля")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Сохранить" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveReviewLimits).toHaveBeenCalledOnce();
    });
    expect(api.saveFeeSettings).toHaveBeenCalledOnce();
  });

  it("asks before hiding a kassa from the site", async () => {
    renderPage();
    const payme = await screen.findByRole("tablist", { name: "Payme: состояние" });
    fireEvent.click(within(payme).getByRole("tab", { name: "Выключен" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    const dialog = screen.getByRole("dialog", { name: "Выключить: Payme?" });
    expect(dialog).toHaveTextContent("Payme будет скрыт на сайте.");
    expect(api.saveFeeSettings).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Да, выключить" }));
    await waitFor(() => {
      expect(api.saveFeeSettings).toHaveBeenCalledOnce();
    });
    const [doc] = api.saveFeeSettings.mock.calls[0] as [{ statuses: Record<string, string> }];
    expect(doc.statuses).toEqual({ payme: "off" });
  });

  it("saves maintenance without asking", async () => {
    renderPage();
    const click = await screen.findByRole("tablist", { name: "Click: состояние" });
    fireEvent.click(within(click).getByRole("tab", { name: "Тех. работы" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => {
      expect(api.saveFeeSettings).toHaveBeenCalledOnce();
    });
  });
});
