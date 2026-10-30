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
}));
vi.mock("./api", () => api);

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
    expect(await screen.findByText(/Трейдер откатил обмен/)).toBeInTheDocument();
  });

  it("moves an item to stock", async () => {
    api.moveItem.mockResolvedValue(deal());
    renderPage();
    const [first] = await screen.findAllByRole("radio", { name: "Себе" });
    if (first) fireEvent.click(first);
    await waitFor(() => {
      expect(api.moveItem).toHaveBeenCalledWith("i1", "stock");
    });
  });

  it("keeps the price form open when the save fails", async () => {
    api.patchDeal.mockRejectedValue(new ApiError(409, "Conflict", { code: "price_locked" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Изменить цену" }));
    fireEvent.change(screen.getByLabelText("Сколько заплачено, $"), { target: { value: "1200" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить цену" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Цену уже не изменить");
    expect(screen.getByRole("button", { name: "Сохранить цену" })).toBeInTheDocument();
  });
});
