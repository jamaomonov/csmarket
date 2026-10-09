import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminTradeRow, type AdminTradesPage } from "./api";
import { TradesPage } from "./TradesPage";

import { DETAIL, SKINSLINK } from "@/features/orders/fixtures";

const api = vi.hoisted(() => ({ listTrades: vi.fn() }));
vi.mock("./api", () => api);
const orders = vi.hoisted(() => ({ getOrder: vi.fn() }));
vi.mock("@/features/orders/api", () => orders);

const NOW = new Date("2026-10-09T12:00:00Z");

const ROW: AdminTradeRow = {
  number: "O7K2M9QX",
  created_at: "2026-10-09T11:57:00Z",
  status: "trade_sent",
  source: "skinslink",
  channel: "site",
  api_owner: null,
  item: {
    name: "AK-47 | Redline (Field-Tested)",
    phase: null,
    image_url: "https://img.example/ak.png",
    rarity_color: "#d32ce6",
    float_value: "0.1234",
  },
  price_uzs: "171800",
  price_usd: "13.580000",
  cost_usd: "12.000000",
  margin_usd: "1.580000",
  margin_pct: "11.6",
  paid_with: "click",
  buyer: { id: "u-1", display_name: "Ivan", avatar_url: "https://img.example/ivan.jpg" },
  steam_offer_id: "6912345678",
  offer_url: "https://steamcommunity.com/tradeoffer/6912345678/",
  // Fake, already-masked link.
  trade_link_masked: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••XY",
  trade_state: "sent",
  protected_until: null,
  protected_estimated: false,
  failure_reason: null,
  attention_reason: null,
  source_status: "active",
};
const FLAGGED: AdminTradeRow = {
  ...ROW,
  number: "O9",
  attention_reason: "rolled_back",
};
const HELD: AdminTradeRow = {
  ...ROW,
  number: "H1",
  trade_state: "hold",
  // 6 days 4 hours 30 minutes after NOW.
  protected_until: "2026-10-15T16:30:00Z",
  source_status: "hold",
};
const API_REFUND: AdminTradeRow = {
  ...ROW,
  number: "R1",
  source: "lisskins",
  channel: "api",
  api_owner: "Partner Co",
  trade_state: "refunded",
  failure_reason: "not_accepted",
  steam_offer_id: null,
  offer_url: null,
};

const COUNTS = { all: 40, active: 5, hold: 3, attention: 2, refunds: 1 };

function page(items: AdminTradeRow[], next: string | null = null): AdminTradesPage {
  return { items, counts: COUNTS, next_cursor: next };
}

function renderPage(url = "/trades") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/trades" element={<TradesPage />} />
          <Route path="/orders/:number" element={<p>order page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const rowOf = async (number: string): Promise<HTMLElement> =>
  (await screen.findByRole("link", { name: number })).closest("tr") as HTMLElement;

describe("TradesPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    api.listTrades.mockReset();
    orders.getOrder.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens on «Все» with every tab's count", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    expect(await screen.findByRole("link", { name: "O7K2M9QX" })).toHaveAttribute(
      "href",
      "/orders/O7K2M9QX",
    );
    expect(api.listTrades).toHaveBeenCalledWith({ view: "all" });
    expect(screen.getByRole("tab", { name: "Все 40" })).toHaveAttribute("aria-selected", "true");
    for (const name of ["В пути 5", "На холде 3", "Требуют внимания 2", "Возвраты 1"]) {
      expect(screen.getByRole("tab", { name })).toHaveAttribute("aria-selected", "false");
    }
  });

  it("requests the tab's view when it is clicked", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "На холде 3" }));
    await waitFor(() => {
      expect(api.listTrades).toHaveBeenCalledWith({ view: "hold" });
    });
    fireEvent.click(screen.getByRole("tab", { name: "Возвраты 1" }));
    await waitFor(() => {
      expect(api.listTrades).toHaveBeenCalledWith({ view: "refunds" });
    });
  });

  it("starts from ?view=attention (the dashboard's link) and ignores an unknown view", async () => {
    api.listTrades.mockResolvedValue(page([FLAGGED]));
    renderPage("/trades?view=attention");
    await screen.findByRole("link", { name: "O9" });
    expect(api.listTrades).toHaveBeenCalledWith({ view: "attention" });
  });

  it("falls back to «Все» for an unknown view and passes ?q=", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage("/trades?view=bogus&q=6912345678");
    await screen.findByRole("link", { name: "O7K2M9QX" });
    expect(api.listTrades).toHaveBeenCalledWith({ view: "all", q: "6912345678" });
    expect(screen.getByRole("searchbox")).toHaveValue("6912345678");
  });

  it("shows the skin, source, money, offer, buyer, state and time of a row", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    const row = await rowOf("O7K2M9QX");
    expect(within(row).getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
    expect(within(row).getByText("float 0.1234")).toBeInTheDocument();
    expect(within(row).getByText("Skinslink")).toBeInTheDocument();
    expect(within(row).getByTestId("trade-price")).toHaveTextContent("$13.58");
    expect(within(row).getByText("себест. $12.00")).toBeInTheDocument();
    const offer = within(row).getByRole("link", { name: "6912345678" });
    expect(offer).toHaveAttribute("href", "https://steamcommunity.com/tradeoffer/6912345678/");
    expect(offer).toHaveAttribute("target", "_blank");
    expect(within(row).queryByText("Трейд-ссылка")).toBeNull(); // in the expanded row now
    expect(within(row).getByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
    expect(within(row).getByText("Click")).toBeInTheDocument();
    expect(within(row).getByTestId("trade-state")).toHaveTextContent("отправлен");
    expect(within(row).getByTestId("trade-state")).toHaveAttribute("title", "Площадка: active");
    expect(within(row).getByText("3 мин назад")).toBeInTheDocument();
  });

  it("explains the price in a tooltip", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    const row = await rowOf("O7K2M9QX");
    const cell = within(row).getByTestId("trade-price").closest("td") as HTMLElement;
    const title = cell.getAttribute("title") ?? "";
    expect(title).toContain("Цена на витрине: 171");
    expect(title).toMatch(/Списано: 171/);
    expect(title).not.toContain("Списано: $");
    expect(title).toContain("Заплатили площадке: $12.00");
    expect(title).toContain("Прибыль: $1.58 (11.6%)");
  });

  it("shows an API order's charge in dollars", async () => {
    api.listTrades.mockResolvedValue(page([API_REFUND]));
    renderPage();
    const row = await rowOf("R1");
    const cell = within(row).getByTestId("trade-price").closest("td") as HTMLElement;
    expect(cell.getAttribute("title")).toContain("Списано: $13.58");
  });

  it("counts down a hold and shows its end date", async () => {
    api.listTrades.mockResolvedValue(page([HELD]));
    renderPage();
    const row = await rowOf("H1");
    expect(within(row).getByTestId("trade-state")).toHaveTextContent("на холде");
    expect(within(row).getByTestId("hold-left")).toHaveTextContent(/^6д 4ч · 15\.10$/);
  });

  it("names an API order's owner and a refund's reason", async () => {
    api.listTrades.mockResolvedValue(page([API_REFUND]));
    renderPage();
    const row = await rowOf("R1");
    expect(within(row).getByText("LIS-SKINS")).toBeInTheDocument();
    expect(within(row).getByText("API · Partner Co")).toBeInTheDocument();
    expect(within(row).getByTestId("trade-state")).toHaveTextContent("возврат · обмен не принят");
    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("tints rows that need attention and names the reason", async () => {
    api.listTrades.mockResolvedValue(page([ROW, FLAGGED]));
    renderPage();
    const flagged = await rowOf("O9");
    expect(flagged).toHaveAttribute("data-attention", "true");
    expect(await rowOf("O7K2M9QX")).not.toHaveAttribute("data-attention");
    expect(within(flagged).getByTestId("order-attention")).toHaveTextContent(
      "откат после получения",
    );
  });

  it("expands a row into the timeline and the source block, from the order page's data", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    orders.getOrder.mockResolvedValue({
      ...DETAIL,
      order: {
        ...DETAIL.order,
        source: "skinslink",
        trade_sent_at: "2026-09-30T10:03:00Z",
      },
      trade: null,
      skinslink: { ...SKINSLINK, fail_reason: "timeout" },
    });
    renderPage();
    const toggle = await screen.findByRole("button", { name: "Подробнее о O7K2M9QX" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    const details = await screen.findByTestId("trade-details");
    const steps = await within(details).findByRole("list", { name: "Ход обмена" });
    expect(
      within(steps)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      expect.stringContaining("Создан"),
      expect.stringContaining("Оплачен"),
      expect.stringContaining("Покупка начата"),
      expect.stringContaining("Обмен отправлен"),
    ]);
    expect(within(details).getByText("active")).toBeInTheDocument();
    expect(within(details).getByText("178")).toBeInTheDocument();
    expect(within(details).getByText("timeout")).toBeInTheDocument();
    expect(within(details).getByRole("link", { name: "Открыть заказ →" })).toHaveAttribute(
      "href",
      "/orders/O7K2M9QX",
    );
    expect(orders.getOrder).toHaveBeenCalledWith("O7K2M9QX");
    fireEvent.click(screen.getByRole("button", { name: "Свернуть O7K2M9QX" }));
    expect(screen.queryByTestId("trade-details")).not.toBeInTheDocument();
  });

  it("opens the order when the row is clicked", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    const row = await rowOf("O7K2M9QX");
    fireEvent.click(within(row).getByText("3 мин назад"));
    expect(await screen.findByText("order page")).toBeInTheDocument();
  });

  it("searches once typing settles", async () => {
    api.listTrades.mockResolvedValue(page([ROW]));
    renderPage();
    await screen.findByRole("link", { name: "O7K2M9QX" });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: " 6912345678 " } });
    await waitFor(() => {
      expect(api.listTrades).toHaveBeenCalledWith({ view: "all", q: "6912345678" });
    });
  });

  it("says so when a tab is empty", async () => {
    api.listTrades.mockResolvedValue(page([]));
    renderPage("/trades?view=hold");
    expect(await screen.findByText("Здесь пусто.")).toBeInTheDocument();
  });

  it("pages with «Показать ещё»", async () => {
    api.listTrades
      .mockResolvedValueOnce(page([ROW], "c2"))
      .mockResolvedValueOnce(page([{ ...ROW, number: "O2" }]));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByRole("link", { name: "O2" })).toBeInTheDocument();
    expect(api.listTrades).toHaveBeenLastCalledWith({ view: "all", cursor: "c2" });
  });

  it("on a phone shows cards with the status and price, not a wide table", async () => {
    const before = Object.getOwnPropertyDescriptor(window, "matchMedia");
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia; // only the members useNarrow reads
    try {
      api.listTrades.mockResolvedValue(page([FLAGGED]));
      renderPage();
      const cards = await screen.findByRole("list", { name: "Обмены" });
      expect(screen.queryByTestId("trades-table")).toBeNull();
      expect(within(cards).getByTestId("trade-state")).toBeInTheDocument();
      expect(within(cards).getByRole("link", { name: FLAGGED.number })).toHaveAttribute(
        "href",
        `/orders/${FLAGGED.number}`,
      );
    } finally {
      if (before) Object.defineProperty(window, "matchMedia", before);
      else Reflect.deleteProperty(window, "matchMedia");
    }
  });

  it("marks an estimated hold end (LIS-SKINS) with ≈", async () => {
    api.listTrades.mockResolvedValue(
      page([
        {
          ...ROW,
          number: "LSHOLD01",
          source: "lisskins",
          status: "delivered",
          trade_state: "hold",
          protected_until: new Date(Date.now() + 3 * 86_400_000).toISOString(),
          protected_estimated: true,
        },
      ]),
    );
    renderPage();
    expect(await screen.findByTestId("hold-left")).toHaveTextContent(/^≈ /);
  });
});
