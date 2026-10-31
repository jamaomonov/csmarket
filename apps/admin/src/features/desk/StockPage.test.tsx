import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deal, stockItem } from "./fixtures";
import { StockPage } from "./StockPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  listStock: vi.fn(),
  sellItem: vi.fn(),
  getRate: vi.fn(),
  stockPrices: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <StockPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function confirm() {
  return screen.getByRole("group", { name: "Подтверждение" });
}

function names(): string[] {
  return within(screen.getByRole("list", { name: "Склад" }))
    .getAllByRole("link")
    .map((a) => a.textContent);
}

const KNIFE = stockItem({
  id: "s2",
  name: "★ Karambit | Doppler (Factory New)",
  cost_usd: "900",
  deal_id: "d2",
  bought_at: "2026-10-25T10:00:00Z",
});

describe("StockPage", () => {
  beforeEach(() => {
    api.listStock.mockReset().mockResolvedValue({
      items: [stockItem(), KNIFE],
      total_cost_usd: "954",
    });
    api.sellItem.mockReset().mockResolvedValue(deal());
    api.getRate.mockReset().mockResolvedValue({ usd_uzs: "13000" });
    api.stockPrices.mockReset().mockResolvedValue({ "AK-47 | Redline (Field-Tested)": "70" });
    localStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("heads with the count and the cost, and each row opens its deal", async () => {
    renderPage();
    const head = await screen.findByText(
      (_, el) => el?.tagName === "P" && el.textContent.startsWith("2 скина · $954.00"),
    );
    expect(head).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /AK-47 \| Redline/ });
    expect(link).toHaveAttribute("href", "/desk/deals/d1");
  });

  it("filters by name and sorts by cost or age", async () => {
    renderPage();
    await screen.findByRole("list", { name: "Склад" });
    expect(names()[0]).toContain("Karambit"); // dearest first
    fireEvent.change(screen.getByLabelText("Сортировка"), { target: { value: "age" } });
    expect(names()[0]).toContain("AK-47"); // the oldest first
    fireEvent.change(screen.getByLabelText("Найти на складе"), { target: { value: "karam" } });
    expect(names()).toHaveLength(1);
  });

  it("shows Skinslink's price now and the profit at it", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Обновить цены" }));
    const row = (await screen.findByText(/Skinslink сейчас/)).closest("li");
    expect(row).toHaveTextContent("$70.00");
    expect(row).toHaveTextContent("+$16.00");
  });

  it("sells a stock skin in dollars in a sheet and remembers where", async () => {
    renderPage();
    await screen.findByRole("list", { name: "Склад" });
    const [, first] = screen.getAllByRole("button", { name: "Продал" });
    if (first) fireEvent.click(first);
    expect(confirm()).toHaveTextContent("AK-47 | Redline (Field-Tested)");
    expect(confirm()).toHaveTextContent("$54.00");
    fireEvent.click(within(confirm()).getByRole("button", { name: "$" }));
    fireEvent.change(screen.getByLabelText("Продал за, $"), { target: { value: "70" } });
    fireEvent.change(screen.getByLabelText("Где продано"), { target: { value: "Market.csgo" } });
    expect(confirm()).toHaveTextContent("Прибыль: +$16.00");
    fireEvent.click(within(confirm()).getByRole("button", { name: "Записать продажу" }));
    await waitFor(() => {
      expect(api.sellItem).toHaveBeenCalledWith("s1", {
        where: "Market.csgo",
        amount: "70",
        currency: "USD",
      });
    });
    expect(localStorage.getItem("desk.sold_where")).toBe("Market.csgo");
  });

  it("takes a rate typed with a space and a comma, and fills the last place", async () => {
    localStorage.setItem("desk.sold_where", "Buff");
    renderPage();
    await screen.findByRole("list", { name: "Склад" });
    const [, first] = screen.getAllByRole("button", { name: "Продал" });
    if (first) fireEvent.click(first);
    expect(screen.getByLabelText("Где продано")).toHaveValue("Buff");
    fireEvent.change(screen.getByLabelText("Продал за, сум"), { target: { value: "910000" } });
    fireEvent.change(screen.getByLabelText("Курс (ЦБ на сегодня)"), {
      target: { value: "12 650,5" },
    });
    fireEvent.click(within(confirm()).getByRole("button", { name: "Записать продажу" }));
    await waitFor(() => {
      expect(api.sellItem).toHaveBeenCalledWith("s1", {
        where: "Buff",
        amount: "910000",
        currency: "UZS",
        rate: "12650.5",
      });
    });
  });

  it("a failed load can be asked again", async () => {
    api.listStock.mockRejectedValueOnce(new ApiError(500, "Server Error", {}));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Попробовать ещё раз" }));
    expect(await screen.findByRole("list", { name: "Склад" })).toBeInTheDocument();
  });

  it("an empty stock says where skins come from", async () => {
    api.listStock.mockResolvedValue({ items: [], total_cost_usd: "0" });
    renderPage();
    expect(await screen.findByText(/Сюда попадают скины, отмеченные «Себе»/)).toBeInTheDocument();
  });
});
