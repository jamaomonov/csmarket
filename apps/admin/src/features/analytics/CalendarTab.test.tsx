import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsPage } from "./AnalyticsPage";
import { BUSINESS, OCTOBER } from "./fixtures";

import { asPhone } from "@/test/phone";

const api = vi.hoisted(() => ({
  getBusiness: vi.fn(),
  getCalendar: vi.fn(),
  getLosses: vi.fn(),
}));
vi.mock("./api", () => api);

let search = "";
function Spy() {
  search = useLocation().search;
  return null;
}

function renderPage(url = "/analytics?tab=calendar&cm=2026-10") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <AnalyticsPage />
        <Spy />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AnalyticsPage — Календарь", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getCalendar.mockResolvedValue(OCTOBER);
    api.getBusiness.mockResolvedValue(BUSINESS);
    api.getLosses.mockResolvedValue({ items: [] });
  });

  it("draws the month from Monday with every day and its tone", async () => {
    renderPage();
    const grid = await screen.findByRole("grid", { name: "Октябрь 2026" });
    const cells = within(grid).getAllByRole("gridcell");
    // October 1st, 2026 is a Thursday: three empty cells first.
    expect(cells.slice(0, 3).every((c) => c.textContent === "")).toBe(true);
    expect(within(grid).getAllByRole("button")).toHaveLength(31);
    expect(screen.getByRole("button", { name: /^9 / })).toHaveAttribute("data-tone", "profit");
    expect(screen.getByRole("button", { name: /^10 / })).toHaveAttribute("data-tone", "loss");
    expect(screen.getByRole("button", { name: /^1 / })).toHaveAttribute("data-tone", "empty");
    expect(api.getCalendar).toHaveBeenCalledWith("2026-10", "all");
  });

  it("steps to the previous month", async () => {
    renderPage();
    await screen.findByRole("grid");
    fireEvent.click(screen.getByRole("button", { name: "Предыдущий месяц" }));
    expect(api.getCalendar).toHaveBeenLastCalledWith("2026-09", "all");
  });

  it("opens a day, or a span of two days, in «Бизнес»", async () => {
    renderPage();
    await screen.findByRole("grid");
    fireEvent.click(screen.getByRole("button", { name: /^9 / }));
    fireEvent.click(screen.getByRole("button", { name: /^12 / }));
    fireEvent.click(screen.getByRole("button", { name: "Открыть 09.10 – 12.10" }));
    expect(search).toContain("from=2026-10-09");
    expect(search).toContain("to=2026-10-12");
    expect(search).not.toContain("tab=calendar");
    fireEvent.click(await screen.findByRole("button", { name: "← к календарю" }));
    expect(search).toContain("tab=calendar");
  });

  it("opens a single day", async () => {
    renderPage();
    await screen.findByRole("grid");
    fireEvent.click(screen.getByRole("button", { name: /^9 / }));
    fireEvent.click(screen.getByRole("button", { name: "Открыть 09.10" }));
    expect(search).toContain("from=2026-10-09");
    expect(search).toContain("to=2026-10-09");
  });

  it("on a phone a day shows a short sum that fits its cell", async () => {
    const restore = asPhone();
    try {
      renderPage();
      await screen.findByRole("grid");
      const sums = screen.getAllByTestId("day-profit").map((e) => e.textContent);
      expect(sums.length).toBeGreaterThan(0);
      expect(sums.every((t) => !t.includes("сум"))).toBe(true);
    } finally {
      restore();
    }
  });
});
