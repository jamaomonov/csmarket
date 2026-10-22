import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsPage } from "./AnalyticsPage";
import { BUSINESS } from "./fixtures";

const api = vi.hoisted(() => ({
  getBusiness: vi.fn(),
  getCalendar: vi.fn(),
  getLosses: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage(url = "/analytics?from=2026-10-09&to=2026-10-10") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <AnalyticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AnalyticsPage — Бизнес", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getBusiness.mockResolvedValue(BUSINESS);
    api.getLosses.mockResolvedValue({ items: [] });
  });

  it("shows the tiles with soʻm, dollars and the change against the previous period", async () => {
    renderPage();
    const profit = await screen.findByTestId("tile-Валовая прибыль");
    expect(profit).toHaveTextContent("58 254 сум");
    expect(profit).toHaveTextContent("▼ −2,9 %");
    const revenue = screen.getByTestId("tile-Оборот");
    expect(revenue).toHaveTextContent("430 000 сум");
    expect(revenue).toHaveTextContent("▲ +115 %");
    expect(api.getBusiness).toHaveBeenCalledWith("2026-10-09", "2026-10-10", "all");
  });

  it("draws no «—» line under a tile with nothing to compare against", async () => {
    renderPage();
    // The previous period had no refunds: no change line at all.
    const refunds = await screen.findByTestId("tile-Возвраты");
    expect(refunds).not.toHaveTextContent("—");
  });

  it("translates the refund reasons and never repeats the total as a count", async () => {
    api.getBusiness.mockResolvedValue({
      ...BUSINESS,
      refunds: {
        count: 19,
        amount_uzs: "900000",
        by_source: [
          { key: "waxpeer", count: 12, amount_uzs: "500000" },
          { key: "lisskins", count: 7, amount_uzs: "400000" },
        ],
        by_reason: [{ key: "not_accepted", count: 19, amount_uzs: "900000" }],
      },
    });
    renderPage();
    const refunds = await screen.findByRole("region", { name: "Возвраты" });
    const reasons = within(refunds).getByRole("list", { name: "По причинам" });
    expect(reasons).toHaveTextContent(/^все: обмен не принят$/);
    expect(within(refunds).getByRole("list", { name: "По площадкам" })).toHaveTextContent(
      "Waxpeer12LIS-SKINS7",
    );
  });

  it("asks again for another period and channel", async () => {
    renderPage();
    await screen.findByTestId("tile-Оборот");
    fireEvent.click(screen.getByRole("tab", { name: "API" }));
    expect(api.getBusiness).toHaveBeenLastCalledWith("2026-10-09", "2026-10-10", "api");
    fireEvent.click(screen.getByRole("tab", { name: "7 дней" }));
    const [since, until] = api.getBusiness.mock.lastCall as [string, string];
    expect(since < until).toBe(true);
  });

  it("lists markets, buyers and the losses block", async () => {
    renderPage();
    const markets = await screen.findByRole("region", { name: "Площадки" });
    expect(within(markets).getByText("LIS-SKINS")).toBeInTheDocument();
    expect(within(markets).getByText("−6 264 сум")).toBeInTheDocument();
    const buyers = screen.getByRole("region", { name: "Покупатели" });
    expect(within(buyers).getByRole("link", { name: "Ivan" })).toHaveAttribute(
      "href",
      "/users/u-1",
    );
    expect(await screen.findByText("Нет — так и должно быть.")).toBeInTheDocument();
    expect(screen.getByTestId("day-chart")).toBeInTheDocument();
  });

  it("never reads a failed losses request as «none»", async () => {
    api.getLosses.mockRejectedValue(new Error("down"));
    renderPage();
    const losses = await screen.findByRole("region", { name: "Продано в минус" });
    expect(await within(losses).findByRole("alert")).toHaveTextContent("Не удалось загрузить");
    expect(within(losses).queryByText("Нет — так и должно быть.")).toBeNull();
  });

  it("links a loss to its order", async () => {
    api.getLosses.mockResolvedValue({
      items: [
        {
          number: "O7K2M9QX",
          name: "AK-47 | Redline (Field-Tested)",
          source: "lisskins",
          paid_at: "2026-10-09T18:59:00Z",
          revenue_uzs: "100000",
          cost_uzs: "106264",
          profit_uzs: "-6264",
        },
      ],
    });
    renderPage();
    const losses = await screen.findByRole("region", { name: "Продано в минус" });
    expect(await within(losses).findByRole("link", { name: "O7K2M9QX" })).toHaveAttribute(
      "href",
      "/orders/O7K2M9QX",
    );
  });
});
