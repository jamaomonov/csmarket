import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type Incoming, type P2PCard } from "./api";
import { P2PPage } from "./P2PPage";

const api = vi.hoisted(() => ({
  listCards: vi.fn(),
  addCard: vi.fn(),
  patchCard: vi.fn(),
  listIncoming: vi.fn(),
  listRequests: vi.fn(),
  getP2PSettings: vi.fn(),
  saveP2PSettings: vi.fn(),
  creditIncoming: vi.fn(),
}));
vi.mock("./api", () => api);
const users = vi.hoisted(() => ({ listUsers: vi.fn() }));
vi.mock("@/features/users/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...users,
}));

const CARD: P2PCard = {
  id: "c1",
  label: "Humo",
  masked: "•••• 4321",
  holder_name: "TEST HOLDER",
  network: "humo",
  active: true,
  min_amount_uzs: "10000",
  max_amount_uzs: "5000000",
  daily_limit_uzs: null,
  today_uzs: "100000",
  created_at: "2026-10-19T10:00:00Z",
};

const UNMATCHED: Incoming = {
  id: "i1",
  kind: "credit",
  amount_uzs: "70000.00",
  card_last4: "4321",
  source_text: "UB P2P",
  bank_time: "2026-10-19T09:30:00Z",
  balance_after: "1000000.00",
  chain_ok: true,
  result: "unmatched",
  number: null,
  received_at: "2026-10-19T09:30:05Z",
  can_credit: true,
};

function renderPage(url = "/p2p") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <P2PPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("P2PPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.listCards.mockResolvedValue({ items: [CARD] });
    api.listIncoming.mockResolvedValue({ items: [UNMATCHED], next_cursor: null });
    api.listRequests.mockResolvedValue({ items: [], next_cursor: null });
    users.listUsers.mockResolvedValue({
      items: [{ id: "u1", display_name: "Buyer", avatar_url: null, steam_id: "7656" }],
      next_cursor: null,
    });
  });

  it("shows the journal with result chips and credits an unmatched transfer after a confirm", async () => {
    api.creditIncoming.mockResolvedValue({
      incoming: { ...UNMATCHED, result: "matched", can_credit: false },
      topup_number: "T1",
    });
    renderPage();
    expect(await screen.findByText("не сопоставлен")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Зачислить пользователю" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Пользователь"), { target: { value: "Buyer" } });
    fireEvent.click(await within(dialog).findByRole("button", { name: /Buyer/ }));
    fireEvent.change(within(dialog).getByLabelText("Основание"), {
      target: { value: "чек от покупателя" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Зачислить 70\s000 сум$/ }));
    await waitFor(() => {
      expect(api.creditIncoming).toHaveBeenCalledOnce();
    });
    const [id, body] = api.creditIncoming.mock.calls[0] as [string, { user_id: string }];
    expect(id).toBe("i1");
    expect(body.user_id).toBe("u1");
  });

  it("the journal filters by result with underlined tabs and a plain search", async () => {
    renderPage();
    const tabs = await screen.findByRole("tablist", { name: "Результат" });
    expect(within(tabs).getByRole("tab", { name: "Все" })).toHaveAttribute("aria-selected", "true");
    expect(tabs).not.toHaveClass("inline-flex");
    fireEvent.click(within(tabs).getByRole("tab", { name: "Не сопоставлены" }));
    await waitFor(() => {
      expect(api.listIncoming).toHaveBeenLastCalledWith({ result: "unmatched" });
    });
    expect(screen.getByRole("searchbox", { name: "Сумма, сум" })).not.toHaveClass("font-mono");
  });

  it("adds a card and clears the number field", async () => {
    api.addCard.mockResolvedValue(CARD);
    renderPage("/p2p?tab=cards");
    expect(await screen.findByText(/•••• 4321/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Номер карты"), {
      target: { value: "9860 1111 2222 4321" },
    });
    fireEvent.change(screen.getByLabelText("Держатель"), { target: { value: "TEST HOLDER" } });
    fireEvent.change(screen.getByLabelText("Название"), { target: { value: "Humo" } });
    const daily = screen.getByLabelText("Лимит в день, сум");
    fireEvent.change(daily, { target: { value: "20000000" } });
    expect(daily).toHaveValue("20\u00a0000\u00a0000");
    fireEvent.click(screen.getByRole("button", { name: "Добавить карту" }));
    await waitFor(() => {
      expect(api.addCard).toHaveBeenCalledOnce();
    });
    expect(api.addCard.mock.calls[0]?.[0]).toMatchObject({ daily_limit_uzs: 20000000 });
    expect(screen.getByLabelText("Номер карты")).toHaveValue("");
  });

  it("saves the settings and says so", async () => {
    api.getP2PSettings.mockResolvedValue({
      humo_bot_user_id: 900,
      owner_telegram_user_id: 500,
      min_amount_uzs: 10000,
      max_amount_uzs: 5000000,
      daily_count: 3,
      daily_amount_uzs: 10000000,
      connected: true,
      last_received_at: null,
      updated_at: "2026-10-19T10:00:00Z",
    });
    api.saveP2PSettings.mockImplementation((body: object) =>
      Promise.resolve({ ...body, connected: true, last_received_at: null, updated_at: "x" }),
    );
    renderPage("/p2p?tab=settings");
    expect(await screen.findByText("подключено")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Подключение и лимиты" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull();
    const max = screen.getByLabelText("Максимум, сум");
    expect(max).toHaveValue("5\u00a0000\u00a0000");
    fireEvent.change(screen.getByLabelText("Пополнений в день, шт"), { target: { value: "5" } });
    fireEvent.change(max, { target: { value: "6\u00a0000\u00a00000" } });
    expect(screen.getByText("Изменено: 2 поля")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText(/Сохранено/)).toBeInTheDocument();
    expect(api.saveP2PSettings.mock.calls[0]?.[0]).toEqual({
      humo_bot_user_id: 900,
      owner_telegram_user_id: 500,
      min_amount_uzs: 10000,
      max_amount_uzs: 60000000,
      daily_count: 5,
      daily_amount_uzs: 10000000,
    });
  });
});
