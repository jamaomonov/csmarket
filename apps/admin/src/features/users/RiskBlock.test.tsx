import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RISK } from "./fixtures";
import { RiskBlock } from "./RiskBlock";

const api = vi.hoisted(() => ({ getRisk: vi.fn(), saveRisk: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

function renderBlock() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RiskBlock userId="u1" />
    </QueryClientProvider>,
  );
}

describe("RiskBlock", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getRisk.mockResolvedValue(RISK);
    api.saveRisk.mockResolvedValue(RISK);
  });

  it("shows the money put in through the kassas", async () => {
    renderBlock();
    const line = await screen.findByTestId("risk-money-in");
    expect(line.textContent).toMatch(
      /Внесено через кассы: 24 ч 1\s500\s000 сум \/ 7 дней 4\s200\s000 сум/,
    );
  });

  it("saves the policy with a key", async () => {
    renderBlock();
    fireEvent.click(await screen.findByLabelText("Запретить оплату кассой"));
    fireEvent.change(screen.getByLabelText("Личный лимит, сум"), { target: { value: "1000000" } });
    fireEvent.change(screen.getByLabelText("Заметка"), { target: { value: "дроппер" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveRisk).toHaveBeenCalledOnce();
    });
    const [id, body, key] = api.saveRisk.mock.calls[0] as [string, unknown, string];
    expect(id).toBe("u1");
    expect(body).toEqual({
      trusted: false,
      kassa_blocked: true,
      max_amount_uzs: 1000000,
      window_hours: 24,
      note: "дроппер",
    });
    expect(key).toMatch(/^admin-user-risk-/);
  });

  it("an empty limit field sends null", async () => {
    renderBlock();
    fireEvent.click(await screen.findByLabelText("Доверенный (без лимитов)"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.saveRisk).toHaveBeenCalledOnce();
    });
    expect(api.saveRisk.mock.calls[0]?.[1]).toEqual({
      trusted: true,
      kassa_blocked: false,
      max_amount_uzs: null,
      window_hours: 24,
      note: null,
    });
  });
});
