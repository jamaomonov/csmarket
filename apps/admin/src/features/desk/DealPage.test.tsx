import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type DeskDeposit } from "./api";
import { DealPage } from "./DealPage";
import { deal, item } from "./fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  getDeal: vi.fn(),
  patchDeal: vi.fn(),
  sendDeposit: vi.fn(),
  sellItem: vi.fn(),
  moveItem: vi.fn(),
  writeOff: vi.fn(),
  getRate: vi.fn(),
  addItems: vi.fn(),
  removeItem: vi.fn(),
  undoItem: vi.fn(),
  loadInventory: vi.fn(),
  listTraders: vi.fn(),
}));
vi.mock("./api", () => api);
vi.mock("@/features/catalogue/SkinSearch", () => ({ SkinSearch: () => null }));

const HOLD: DeskDeposit = {
  id: "x",
  status: "hold",
  amount_usd: "1200",
  amount_estimated: false,
  trade_offer_id: "6912345678",
  offer_expiry_at: null,
  hold_end_date: null,
  fail_reason: null,
  bot_name: "Skinslink Bot #3",
  bot_steam_id: "76561190000000003",
  bot_persona: null,
  bot_avatar_url: null,
  accepted_at: "2026-10-29T10:00:00Z",
  credited_at: null,
  reverted_at: null,
  created_at: "2026-10-29T09:00:00Z",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/desk/deals/d1"]}>
        <Routes>
          <Route path="/desk/deals/:id" element={<DealPage />} />
          <Route path="/desk" element={<p>desk list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function confirm() {
  return screen.getByRole("group", { name: "Подтверждение" });
}

const LATER = new Date(Date.now() + 5 * 86_400_000).toISOString();

describe("DealPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => {
      if (typeof f === "function") f.mockReset();
    });
    api.getDeal.mockResolvedValue(deal());
    api.getRate.mockResolvedValue({ usd_uzs: "13000" });
    api.listTraders.mockResolvedValue({ items: [] });
  });

  it("asks before sending the offer, then shows when paying is safe", async () => {
    api.sendDeposit.mockResolvedValue(
      deal({
        status: "received",
        items: [item({ state: "sent", deposit_id: "x" })],
        deposits: [HOLD],
        protected_until: LATER,
      }),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отправить обмен" }));
    expect(api.sendDeposit).not.toHaveBeenCalled();
    expect(confirm()).toHaveTextContent("2 скина в Skinslink");
    expect(within(confirm()).getAllByRole("checkbox")).toHaveLength(2);
    fireEvent.click(within(confirm()).getByRole("button", { name: "Отправить" }));
    await waitFor(() => {
      expect(api.sendDeposit).toHaveBeenCalledWith("d1");
    });
    expect(await screen.findByText(/Платить безопасно с/)).toBeInTheDocument();
    expect(screen.getByText(/Steam держит 7 дней/)).toBeInTheDocument();
  });

  it("says when paying is safe once the protection is over", async () => {
    api.getDeal.mockResolvedValue(
      deal({ deposits: [HOLD], protected_until: "2026-10-01T10:00:00Z" }),
    );
    renderPage();
    expect(await screen.findByText("Защита Steam прошла — можно платить")).toBeInTheDocument();
  });

  it("says when Skinslink's prices moved", async () => {
    api.sendDeposit.mockRejectedValue(new ApiError(409, "Conflict", { code: "prices_moved" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отправить обмен" }));
    fireEvent.click(within(confirm()).getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Цена Skinslink изменилась при отправке",
    );
  });

  it("says when the skins left the trader's inventory", async () => {
    api.sendDeposit.mockRejectedValue(new ApiError(409, "Conflict", { code: "skins_gone" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отправить обмен" }));
    expect(confirm()).toHaveTextContent("Цены Skinslink обновятся перед отправкой");
    fireEvent.click(within(confirm()).getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Этих скинов уже нет в инвентаре трейдера",
    );
  });

  it("changes the status only through the confirm step", async () => {
    api.patchDeal.mockResolvedValue(deal({ status: "cancelled" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Сменить статус" }));
    expect(within(confirm()).getAllByRole("radio")).toHaveLength(4);
    expect(within(confirm()).queryByRole("radio", { name: "закрыта" })).toBeNull();
    fireEvent.click(within(confirm()).getByRole("radio", { name: "отменена" }));
    expect(confirm()).toHaveTextContent("Это только пометка");
    fireEvent.click(within(confirm()).getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.patchDeal).toHaveBeenCalledWith("d1", { status: "cancelled" });
    });
  });

  it("warns before confirming the guarantor while the protection runs", async () => {
    api.getDeal.mockResolvedValue(
      deal({ method: "guarantor", deposits: [HOLD], protected_until: LATER }),
    );
    api.patchDeal.mockResolvedValue(deal({ method: "guarantor" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Подтвердить гаранту" }));
    expect(api.patchDeal).not.toHaveBeenCalled();
    expect(confirm()).toHaveTextContent("Трейдер ещё может откатить обмен");
    fireEvent.click(within(confirm()).getByRole("button", { name: "Всё равно подтвердить" }));
    await waitFor(() => {
      expect(api.patchDeal).toHaveBeenCalledWith("d1", { guarantor_released: true });
    });
  });

  it("says in words that Skinslink turned the offer down", async () => {
    api.getDeal.mockResolvedValue(
      deal({
        deposits: [{ ...HOLD, status: "failed", fail_reason: "price_changed", accepted_at: null }],
      }),
    );
    renderPage();
    expect(
      await screen.findByText("Skinslink отклонил обмен: цена на Skinslink изменилась"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/price_changed/)).not.toBeInTheDocument();
  });

  it("shows the bot that sends the offer, with its Steam profile", async () => {
    api.getDeal.mockResolvedValue(
      deal({
        deposits: [
          {
            ...HOLD,
            status: "active",
            bot_persona: "SL Bot 3",
            bot_avatar_url: "https://avatars.test/b3.jpg",
          },
        ],
      }),
    );
    renderPage();
    const bot = await screen.findByRole("link", { name: /SL Bot 3/ });
    expect(bot).toHaveAttribute("href", "https://steamcommunity.com/profiles/76561190000000003");
    expect(within(bot).getByRole("presentation")).toHaveAttribute(
      "src",
      "https://avatars.test/b3.jpg",
    );
  });

  it("refreshes by itself while the offer is open", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      api.getDeal.mockResolvedValue(deal({ deposits: [{ ...HOLD, status: "pending" }] }));
      renderPage();
      await screen.findByText(/бот готовит обмен/);
      expect(api.getDeal).toHaveBeenCalledTimes(1);
      api.getDeal.mockResolvedValue(
        deal({ deposits: [{ ...HOLD, status: "failed", fail_reason: "price_changed" }] }),
      );
      await vi.advanceTimersByTimeAsync(5_000);
      expect(await screen.findByText(/Skinslink отклонил обмен/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows a red banner on a revert", async () => {
    api.getDeal.mockResolvedValue(deal({ status: "reverted", profit_usd: "-1100" }));
    renderPage();
    expect(await screen.findByText(/Трейдер откатил обмен:/)).toBeInTheDocument();
    // The system's status: not for the owner to change.
    expect(screen.queryByRole("button", { name: "Сменить статус" })).toBeNull();
  });

  it("sends only the ticked skins", async () => {
    api.sendDeposit.mockResolvedValue(deal());
    renderPage();
    const bar = await screen.findByRole("region", { name: "Отправка" });
    expect(bar).toHaveTextContent("2 скина · ≈ $1 200.00");
    fireEvent.click(within(bar).getByRole("button", { name: /Отправить обмен/ }));
    fireEvent.click(
      within(confirm()).getByRole("checkbox", { name: "AWP | Asiimov (Field-Tested)" }),
    );
    expect(confirm()).toHaveTextContent("1 скин в Skinslink");
    fireEvent.click(within(confirm()).getByRole("button", { name: "Отправить" }));
    await waitFor(() => {
      expect(api.sendDeposit).toHaveBeenCalledWith("d1", ["i1"]);
    });
  });

  it("says why it cannot send without a trade link", async () => {
    api.getDeal.mockResolvedValue(deal({ trade_link: null }));
    renderPage();
    const bar = await screen.findByRole("region", { name: "Отправка" });
    expect(bar).toHaveTextContent("Нет трейд-ссылки");
    expect(within(bar).queryByRole("button", { name: /Отправить обмен/ })).toBeNull();
    fireEvent.click(within(bar).getByRole("button", { name: "Указать ссылку" }));
    expect(screen.getByLabelText("Трейд-ссылка")).toBeInTheDocument();
  });

  it("says an offer is already open", async () => {
    api.getDeal.mockResolvedValue(
      deal({
        items: [item({ state: "sent", deposit_id: "x" }), item({ id: "i2", asset_id: "101" })],
        deposits: [{ ...HOLD, status: "active" }],
      }),
    );
    renderPage();
    const bar = await screen.findByRole("region", { name: "Отправка" });
    expect(bar).toHaveTextContent("Обмен уже идёт");
  });

  it("shows what the deal is: paid, Skinslink, the expected profit, the note", async () => {
    api.getDeal.mockResolvedValue(
      deal({
        paid_amount: "14300000",
        paid_currency: "UZS",
        rate: "13000",
        note: "из чата",
        method: "guarantor",
        guarantor: "garant42",
      }),
    );
    renderPage();
    const sum = await screen.findByRole("region", { name: "Сделка" });
    expect(sum).toHaveTextContent("14 300 000");
    expect(sum).toHaveTextContent("$1 100.00");
    expect(sum).toHaveTextContent("$1 200.00");
    expect(sum).toHaveTextContent("≈ +$100.00");
    expect(sum).toHaveTextContent("из чата");
    expect(sum).toHaveTextContent("garant42");
    expect(screen.getByRole("link", { name: "Все сделки с трейдером" })).toHaveAttribute(
      "href",
      "/desk?q=trader+one",
    );
  });

  it("edits the deal, sending only what changed", async () => {
    api.patchDeal.mockResolvedValue(deal({ note: "новое" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
    fireEvent.change(screen.getByLabelText("Заметка"), { target: { value: "новое" } });
    fireEvent.click(screen.getByRole("radio", { name: "через гаранта" }));
    fireEvent.change(screen.getByLabelText("Гарант"), { target: { value: "garant42" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.patchDeal).toHaveBeenCalledWith("d1", {
        note: "новое",
        method: "guarantor",
        guarantor: "garant42",
      });
    });
  });

  it("says in words why the status cannot change", async () => {
    api.patchDeal.mockRejectedValue(new ApiError(409, "Conflict", { code: "deal_busy" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Сменить статус" }));
    fireEvent.click(within(confirm()).getByRole("radio", { name: "отменена" }));
    fireEvent.click(within(confirm()).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Сейчас статус не сменить");
  });

  it("copies the offer number", async () => {
    api.getDeal.mockResolvedValue(deal({ deposits: [HOLD] }));
    renderPage();
    expect(
      await screen.findByRole("button", { name: "Копировать номер обмена" }),
    ).toBeInTheDocument();
  });

  it("a failed load can be asked again", async () => {
    api.getDeal.mockRejectedValueOnce(new ApiError(500, "Server Error", {}));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Попробовать ещё раз" }));
    expect(await screen.findByRole("heading", { name: "trader one" })).toBeInTheDocument();
  });
});
