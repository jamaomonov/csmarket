import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ManualRate } from "./ManualRate";

const api = vi.hoisted(() => ({ setManualRate: vi.fn() }));
vi.mock("./api", () => api);

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ManualRate />
    </QueryClientProvider>,
  );
}

describe("ManualRate", () => {
  it("asks for the CBU rate and saves it", async () => {
    api.setManualRate.mockResolvedValue({ id: "f1", usd_uzs: "12004.02", source: "manual" });
    renderIt();
    fireEvent.click(screen.getByRole("button", { name: "Курс вручную" }));
    const sheet = screen.getByRole("group", { name: "Подтверждение" });
    expect(sheet).toHaveTextContent("cbu.uz");
    fireEvent.change(within(sheet).getByLabelText("Курс ЦБ, сум"), {
      target: { value: "12 004,02" },
    });
    fireEvent.click(within(sheet).getByRole("button", { name: "Сохранить курс" }));
    await waitFor(() => {
      expect(api.setManualRate).toHaveBeenCalledWith("12004.02");
    });
  });

  it("refuses a rate outside 1 000–100 000", () => {
    renderIt();
    fireEvent.click(screen.getByRole("button", { name: "Курс вручную" }));
    fireEvent.change(screen.getByLabelText("Курс ЦБ, сум"), { target: { value: "120" } });
    expect(screen.getByRole("button", { name: "Сохранить курс" })).toBeDisabled();
  });
});
