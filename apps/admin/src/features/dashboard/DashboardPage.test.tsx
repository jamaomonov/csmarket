import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type DashboardOut } from "./api";
import { DashboardPage } from "./DashboardPage";

const api = vi.hoisted(() => ({ getDashboard: vi.fn() }));
vi.mock("./api", () => api);

const DATA: DashboardOut = {
  days: 1,
  since: "2026-10-01T19:00:00Z",
  sales: {
    count: 12,
    revenue_uzs: "1524000",
    revenue_usd: "120",
    cost_usd: "105",
    margin_usd: "15",
    margin_percent: "12.5",
  },
  refunds: { count: 2, amount_uzs: "177000" },
  in_flight: 3,
  attention: 1,
  payouts: { to_pay_count: 2, to_pay_uzs: "310400" },
  by_day: [
    { day: "2026-10-01", sales_count: 0, revenue_uzs: "0", margin_usd: "0" },
    { day: "2026-10-02", sales_count: 12, revenue_uzs: "1524000", margin_usd: "15" },
  ],
  waxpeer: { balance_usd: "812.5", read_at: new Date(Date.now() - 4 * 60_000).toISOString() },
  lisskins: {
    available_usd: "99.96",
    locked_usd: "1.5",
    read_at: new Date(Date.now() - 3 * 60_000).toISOString(),
  },
  skinslink: {
    available_usd: "240.5",
    hold_usd: "12",
    read_at: new Date(Date.now() - 2 * 60_000).toISOString(),
  },
};

function renderPage(path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const tile = (title: string): HTMLElement => screen.getByTestId(`tile-${title}`);

describe("DashboardPage", () => {
  beforeEach(() => {
    api.getDashboard.mockReset();
    api.getDashboard.mockResolvedValue(DATA);
  });

  it("asks for today by default and for the tab picked", async () => {
    renderPage();
    await screen.findByTestId("tile-Продажи");
    expect(api.getDashboard).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "7 дней" }));
    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(7);
    });
    fireEvent.click(screen.getByRole("button", { name: "30 дней" }));
    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(30);
    });
  });

  it("a stale or hand-edited ?days= falls back to today", async () => {
    renderPage("/?days=5");
    await screen.findByTestId("tile-Продажи");
    expect(api.getDashboard).toHaveBeenLastCalledWith(1);
  });

  it("renders every tile from the API's strings", async () => {
    renderPage("/?days=7");
    await screen.findByTestId("tile-Продажи");
    expect(tile("Продажи")).toHaveTextContent("12");
    expect(tile("Выручка")).toHaveTextContent("1 524 000 сум");
    expect(tile("Выручка")).toHaveTextContent("$120");
    expect(tile("Маржа")).toHaveTextContent("$15");
    expect(tile("Маржа")).toHaveTextContent("12.5 %");
    expect(tile("Возвраты")).toHaveTextContent("2");
    expect(tile("Возвраты")).toHaveTextContent("177 000 сум");
    expect(tile("В пути")).toHaveTextContent("3");
    expect(within(tile("В пути")).getByRole("link")).toHaveAttribute("href", "/trades?view=active");
    expect(tile("Баланс Waxpeer")).toHaveTextContent("$812.5");
    expect(tile("Баланс Waxpeer")).toHaveTextContent("обновлено 4 мин назад");
    expect(tile("Баланс Skinslink")).toHaveTextContent("$240.5");
    expect(tile("Баланс Skinslink")).toHaveTextContent("в холде $12");
    expect(tile("Баланс Skinslink")).toHaveTextContent("обновлено 2 мин назад");
    expect(tile("Баланс LIS-SKINS")).toHaveTextContent("$99.96");
    expect(tile("Баланс LIS-SKINS")).toHaveTextContent("заблокировано $1.5");
    expect(tile("Баланс LIS-SKINS")).toHaveTextContent("обновлено 3 мин назад");
    const link = within(tile("Требуют внимания")).getByRole("link");
    expect(link).toHaveAttribute("href", "/trades?view=attention");
  });

  it("an unknown balance says so", async () => {
    api.getDashboard.mockResolvedValue({ ...DATA, waxpeer: { balance_usd: null, read_at: null } });
    renderPage();
    await screen.findByTestId("tile-Продажи");
    expect(tile("Баланс Waxpeer")).toHaveTextContent("неизвестно");
  });

  it("shows the card payouts to pay as a link to the queue", async () => {
    api.getDashboard.mockResolvedValue(DATA);
    renderPage();
    const tile = await screen.findByTestId("tile-К выплате");
    expect(within(tile).getByRole("link")).toHaveAttribute("href", "/payouts");
    expect(tile).toHaveTextContent(/2/);
    expect(tile).toHaveTextContent(/310\s400 сум/);
  });

  it("an unknown LIS-SKINS balance says so", async () => {
    api.getDashboard.mockResolvedValue({
      ...DATA,
      lisskins: { available_usd: null, locked_usd: null, read_at: null },
    });
    renderPage();
    await screen.findByTestId("tile-Продажи");
    expect(tile("Баланс LIS-SKINS")).toHaveTextContent("неизвестно");
  });

  it("an unknown Skinslink balance says so", async () => {
    api.getDashboard.mockResolvedValue({
      ...DATA,
      skinslink: { available_usd: null, hold_usd: null, read_at: null },
    });
    renderPage();
    await screen.findByTestId("tile-Продажи");
    expect(tile("Баланс Skinslink")).toHaveTextContent("неизвестно");
  });

  it("days without sales are listed too", async () => {
    renderPage("/?days=7");
    const rows = await screen.findAllByRole("row");
    expect(rows.map((r) => r.textContent)).toContain("01.100—$0.00");
  });
});
