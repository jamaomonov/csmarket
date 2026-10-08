import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SETTINGS } from "./fixtures";
import { SaleSettingsPage } from "./SaleSettingsPage";

const api = vi.hoisted(() => ({ getSaleSettings: vi.fn(), saveSaleSettings: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SaleSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SaleSettingsPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getSaleSettings.mockResolvedValue(SETTINGS);
    api.saveSaleSettings.mockResolvedValue(SETTINGS);
  });

  it("saves the edited document with a key after a confirm", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Выкуп включён"));
    fireEvent.change(screen.getByLabelText("Минимум на карту, сум"), {
      target: { value: "50000" },
    });
    fireEvent.change(screen.getByLabelText("Комиссия Humo, %"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, сохранить" }));
    await waitFor(() => {
      expect(api.saveSaleSettings).toHaveBeenCalledOnce();
    });
    const [doc, key] = api.saveSaleSettings.mock.calls[0] as [Record<string, unknown>, string];
    expect(doc).toMatchObject({
      enabled: true,
      card_min_uzs: 50000,
      card_fee_pct: { uzcard: "5", humo: "1.5", uzum_visa: "5" },
    });
    expect(key).toMatch(/^admin-sale-settings-/);
  });

  it("adds and removes a margin bracket", async () => {
    renderPage();
    await screen.findByLabelText("Выкуп включён");
    expect(screen.getAllByLabelText(/^От, \$/)).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Добавить диапазон" }));
    expect(screen.getAllByLabelText(/^От, \$/)).toHaveLength(5);
    const last = screen.getAllByRole("button", { name: "Убрать диапазон" }).at(-1);
    if (!last) throw new Error("no remove button");
    fireEvent.click(last);
    expect(screen.getAllByLabelText(/^От, \$/)).toHaveLength(4);
  });

  it("does not send an emptied minimum", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Минимум на карту, сум"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Минимум на карту");
    expect(api.saveSaleSettings).not.toHaveBeenCalled();
  });

  it("keeps a row's input when an earlier row is removed", async () => {
    renderPage();
    await screen.findByLabelText("Выкуп включён");
    const inputs = screen.getAllByLabelText(/^От, \$/);
    inputs[0]?.focus();
    const second = screen.getAllByRole("button", { name: "Убрать диапазон" }).at(1);
    if (!second) throw new Error("no remove button");
    fireEvent.click(second);
    expect(inputs[0]).toBe(screen.getAllByLabelText(/^От, \$/)[0]);
  });
});
