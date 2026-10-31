import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeskPage } from "./DeskPage";
import { row } from "./fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  getSummary: vi.fn(),
  listDeals: vi.fn(),
  addWithdrawal: vi.fn(),
  listWithdrawals: vi.fn(),
}));
vi.mock("./api", () => api);

const SUMMARY = {
  profit_usd: "100",
  revenue_usd: "1200",
  deals_closed: 3,
  items_resolved: 2,
  in_transit_usd: "366.67",
  stock_usd: "54",
  skinslink_share_usd: "1175",
};

const PAST = "2026-10-01T10:00:00Z";

function renderPage(url = "/desk") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <DeskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DeskPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => {
      if (typeof f === "function") f.mockReset();
    });
    api.getSummary.mockResolvedValue(SUMMARY);
    api.listWithdrawals.mockResolvedValue({ items: [] });
    api.listDeals.mockResolvedValue({ items: [row()], next_cursor: null });
  });

  it("puts the profit first and names the other figures", async () => {
    renderPage();
    const tiles = await screen.findByLabelText("Итоги");
    expect(within(tiles).getByTestId("desk-profit")).toHaveTextContent("+$100.00 · 3 сделки");
    for (const title of [
      "Зачислено Skinslink",
      "В пути",
      "На складе (по себестоимости)",
      "Мои деньги на Skinslink",
    ]) {
      expect(tiles).toHaveTextContent(title);
    }
  });

  it("a row shows the dearest skin, the trader and the expected profit", async () => {
    api.listDeals.mockResolvedValue({
      items: [row({ note: "из чата", method: "guarantor", protected_until: PAST })],
      next_cursor: null,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: /trader one/ });
    expect(link).toHaveAttribute("href", "/desk/deals/d1");
    expect(link).toHaveTextContent("AK-47 | Redline (Field-Tested)");
    expect(link).toHaveTextContent("+1");
    expect(link).toHaveTextContent("через гаранта");
    expect(link).toHaveTextContent("из чата");
    expect(link).toHaveTextContent("≈ +$100.00");
    expect(link).toHaveTextContent("14,3 млн сум");
    expect(link).toHaveTextContent("Skinslink $1 200.00");
    expect(link).toHaveTextContent("можно платить гаранту");
  });

  it("a deal with booked profit shows it, not the estimate", async () => {
    api.listDeals.mockResolvedValue({
      items: [
        row({ status: "closed", profit_usd: "90", resolved: true, expected_profit_usd: null }),
      ],
      next_cursor: null,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: /trader one/ });
    expect(link).toHaveTextContent("+$90.00");
    expect(link).not.toHaveTextContent("≈");
    expect(link).not.toHaveTextContent("можно платить гаранту");
  });

  it("a cancelled deal shows no expected profit", async () => {
    api.listDeals.mockResolvedValue({
      items: [row({ status: "cancelled" })],
      next_cursor: null,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: /trader one/ });
    expect(link).not.toHaveTextContent("≈");
    expect(link).toHaveTextContent("—");
  });

  it("a partly done deal shows the booked and the expected profit together", async () => {
    api.listDeals.mockResolvedValue({
      items: [row({ profit_usd: "40", expected_profit_usd: "110" })],
      next_cursor: null,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: /trader one/ });
    expect(link).toHaveTextContent("пока +$40.00 · ≈ +$110.00");
  });

  it("counts «Сегодня» by the day in Tashkent, not the browser's", async () => {
    const tz = process.env.TZ;
    process.env.TZ = "UTC";
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-30T20:30:00Z")); // 01:30 on the 31st in Tashkent
    try {
      renderPage();
      await screen.findByLabelText("Итоги");
      fireEvent.click(screen.getByRole("tab", { name: "Сегодня" }));
      await waitFor(() => {
        expect(api.getSummary).toHaveBeenCalledWith("2026-10-31", undefined);
      });
      expect(api.getSummary).toHaveBeenCalledWith("2026-10-02", undefined);
    } finally {
      vi.useRealTimers();
      process.env.TZ = tz;
    }
  });

  it("«в работе» asks for paid and received deals", async () => {
    renderPage();
    await screen.findByRole("link", { name: /trader one/ });
    fireEvent.click(screen.getByRole("button", { name: "в работе" }));
    await waitFor(() => {
      expect(api.listDeals).toHaveBeenCalledWith({ status: "paid" });
    });
    expect(api.listDeals).toHaveBeenCalledWith({ status: "received" });
  });

  it("searches by the URL's q and keeps typing in the URL", async () => {
    renderPage("/desk?q=trader%20one");
    await waitFor(() => {
      expect(api.listDeals).toHaveBeenCalledWith({ q: "trader one" });
    });
    fireEvent.change(screen.getByLabelText("Трейдер или скин"), { target: { value: "awp" } });
    await waitFor(() => {
      expect(api.listDeals).toHaveBeenCalledWith({ q: "awp" });
    });
  });

  it("asks for a custom period", async () => {
    renderPage();
    await screen.findByLabelText("Итоги");
    fireEvent.click(screen.getByRole("tab", { name: "Свой период" }));
    fireEvent.change(screen.getByLabelText("С"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("По"), { target: { value: "2026-10-15" } });
    await waitFor(() => {
      expect(api.getSummary).toHaveBeenCalledWith("2026-10-01", "2026-10-15");
    });
  });

  it("records «Вывел себе» and lists what was taken out", async () => {
    api.listWithdrawals.mockResolvedValue({
      items: [{ id: "w0", amount_usd: "40", note: "на карту", at: "2026-10-20T10:00:00Z" }],
    });
    api.addWithdrawal.mockResolvedValue({ id: "w1", amount_usd: "25", note: null, at: "" });
    renderPage();
    expect(await screen.findByText("на карту")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Вывел себе…" }));
    fireEvent.change(screen.getByLabelText("Сколько выведено, $"), { target: { value: "25.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Записать" }));
    await waitFor(() => {
      expect(api.addWithdrawal).toHaveBeenCalledWith("25.5", undefined);
    });
  });

  it("a failed list can be asked again", async () => {
    api.listDeals.mockRejectedValueOnce(new ApiError(500, "Server Error", {}));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Попробовать ещё раз" }));
    expect(await screen.findByRole("link", { name: /trader one/ })).toBeInTheDocument();
  });

  it("an empty list offers a new deal", async () => {
    api.listDeals.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    expect(await screen.findByText("Сделок пока нет")).toBeInTheDocument();
  });
});
