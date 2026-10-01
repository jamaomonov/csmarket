import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminUserCard } from "./api";
import { UserCard } from "./UserCard";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUserCard: vi.fn(),
  banUser: vi.fn(),
  unbanUser: vi.fn(),
  adjustBalance: vi.fn(),
}));
vi.mock("./api", () => api);

// Fake IDs and a fake, already-masked trade link; never a real account.
const STEAM_ID = "76561190000000001";
const CARD: AdminUserCard = {
  user: {
    id: "u-1",
    steam_id: STEAM_ID,
    display_name: "Ivan",
    avatar_url: null,
    email: "ivan@example.test",
    locale: "uz",
    roles: [],
    banned_at: null,
    ban_reason: null,
    created_at: "2026-09-01T10:00:00Z",
    trade_link_masked: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••zz",
    trade_link_verdict: "warn",
    trade_link_reason: "hold",
    trade_link_checked_at: "2026-09-30T10:00:00Z",
  },
  balance_uzs: "30000",
  entries: [
    {
      id: "e-2",
      kind: "admin_adjust",
      amount_uzs: "-20000",
      created_at: "2026-09-30T11:00:00Z",
      reference_number: null,
      actor: "admin:a-1",
      reason: "Ошибочное начисление",
    },
    {
      id: "e-1",
      kind: "topup",
      amount_uzs: "+50000",
      created_at: "2026-09-30T10:00:00Z",
      reference_number: "T100001",
      actor: "payments",
      reason: null,
    },
  ],
  topups: [
    {
      number: "T100001",
      amount_uzs: "50000",
      status: "succeeded",
      provider: "click",
      created_at: "2026-09-30T09:55:00Z",
      succeeded_at: "2026-09-30T10:00:00Z",
    },
  ],
};

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/users/u-1"]}>
        <Routes>
          <Route path="/users/:id" element={<UserCard />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openAdjust(amount: string, reason: string) {
  fireEvent.click(await screen.findByRole("button", { name: "Изменить баланс" }));
  fireEvent.change(screen.getByLabelText("Сумма, сум"), { target: { value: amount } });
  fireEvent.change(screen.getByLabelText("Причина изменения"), { target: { value: reason } });
  fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
}

describe("UserCard", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getUserCard.mockResolvedValue(CARD);
  });

  it("shows the profile, balance, history and top-ups", async () => {
    renderCard();
    expect(await screen.findByRole("heading", { name: "Ivan" })).toBeInTheDocument();
    expect(api.getUserCard).toHaveBeenCalledWith("u-1");
    expect(screen.getByText(STEAM_ID)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Профиль в Steam" })).toHaveAttribute(
      "href",
      `https://steamcommunity.com/profiles/${STEAM_ID}`,
    );
    expect(screen.getByText("ivan@example.test")).toBeInTheDocument();
    expect(screen.getByText("узбекский")).toBeInTheDocument();
    expect(screen.getByText(CARD.user.trade_link_masked ?? "")).toBeInTheDocument();
    expect(screen.getByText(/задержка обмена/)).toBeInTheDocument();
    expect(screen.getByText(/Баланс: 30\s000 сум/)).toBeInTheDocument();

    const history = screen.getByRole("region", { name: "История баланса" });
    expect(within(history).getByText("Изменение администратором")).toBeInTheDocument();
    expect(within(history).getByText(/^\u221220\s000 сум$/)).toBeInTheDocument();
    expect(within(history).getByText(/^\+50\s000 сум$/)).toBeInTheDocument();
    expect(within(history).getByText(/Ошибочное начисление/)).toBeInTheDocument();
    expect(within(history).getByRole("link", { name: "администратор" })).toHaveAttribute(
      "href",
      "/users/a-1",
    );

    const topups = screen.getByRole("region", { name: "Пополнения" });
    expect(within(topups).getByRole("link", { name: "T100001" })).toHaveAttribute(
      "href",
      "/payments?q=T100001",
    );
    expect(within(topups).getByText("зачислено")).toBeInTheDocument();
  });

  it("credits after a confirm step with a signed amount, reason and key", async () => {
    api.adjustBalance.mockResolvedValue({ ...CARD, balance_uzs: "80000" });
    renderCard();
    await openAdjust("50 000", "Компенсация за задержку");
    const confirm = await screen.findByRole("button", { name: /^Начислить 50\s000 сум$/ });
    expect(api.adjustBalance).not.toHaveBeenCalled();
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(api.adjustBalance).toHaveBeenCalledTimes(1);
    });
    const [id, amount, reason, key] = api.adjustBalance.mock.calls[0] as [
      string,
      number,
      string,
      string,
    ];
    expect([id, amount, reason]).toEqual(["u-1", 50000, "Компенсация за задержку"]);
    expect(key.length).toBeGreaterThanOrEqual(16);
    expect(await screen.findByText(/Баланс: 80\s000 сум/)).toBeInTheDocument();
  });

  it("names a clawback as «Списать»", async () => {
    api.adjustBalance.mockResolvedValue(CARD);
    renderCard();
    await openAdjust("-10000", "Ошибочное начисление");
    fireEvent.click(await screen.findByRole("button", { name: /^Списать 10\s000 сум$/ }));
    await waitFor(() => {
      expect(api.adjustBalance).toHaveBeenCalledWith(
        "u-1",
        -10000,
        "Ошибочное начисление",
        expect.any(String),
      );
    });
  });

  it("does not send a second request while the first is pending", async () => {
    api.adjustBalance.mockReturnValue(new Promise(() => undefined));
    renderCard();
    await openAdjust("50000", "Компенсация за задержку");
    const confirm = await screen.findByRole("button", { name: /Начислить/ });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(api.adjustBalance).toHaveBeenCalledTimes(1);
    });
    expect(confirm).toBeDisabled();
  });

  it("retries a failed submission with the same key", async () => {
    api.adjustBalance.mockRejectedValueOnce(new TypeError("network")).mockResolvedValue(CARD);
    renderCard();
    await openAdjust("50000", "Компенсация за задержку");
    fireEvent.click(await screen.findByRole("button", { name: /Начислить/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не получилось");
    fireEvent.click(screen.getByRole("button", { name: /Начислить/ }));
    await waitFor(() => {
      expect(api.adjustBalance).toHaveBeenCalledTimes(2);
    });
    const keys = api.adjustBalance.mock.calls.map((c) => c[3] as string);
    expect(keys[0]).toBe(keys[1]);
  });

  it("explains a clawback beyond the balance", async () => {
    api.adjustBalance.mockRejectedValue(
      new ApiError(409, "Conflict", { code: "balance_too_low", detail: "insufficient" }),
    );
    renderCard();
    await openAdjust("-90000", "Ошибочное начисление");
    fireEvent.click(await screen.findByRole("button", { name: /Списать/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "На балансе меньше, чем вы хотите списать.",
    );
  });

  it("refuses an amount that is not whole soʻm", async () => {
    renderCard();
    await openAdjust("1e9", "Компенсация за задержку");
    expect(await screen.findByRole("alert")).toHaveTextContent("целую сумму");
    expect(screen.queryByRole("button", { name: /Начислить|Списать/ })).not.toBeInTheDocument();
  });

  it("refuses an adjustment without a reason", async () => {
    renderCard();
    await openAdjust("50000", "  ");
    expect(await screen.findByRole("alert")).toHaveTextContent("причину");
    expect(screen.queryByRole("button", { name: /Начислить/ })).not.toBeInTheDocument();
  });

  it("bans only with a reason", async () => {
    api.banUser.mockResolvedValue({
      ...CARD,
      user: { ...CARD.user, banned_at: "2026-10-01T10:00:00Z", ban_reason: "Мошенничество" },
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Заблокировать" }));
    const dialog = screen.getByRole("dialog", { name: "Заблокировать пользователя" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Заблокировать" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("причину");
    expect(api.banUser).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Мошенничество" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Заблокировать" }));
    await waitFor(() => {
      expect(api.banUser).toHaveBeenCalledTimes(1);
    });
    const [id, reason, key] = api.banUser.mock.calls[0] as [string, string, string];
    expect([id, reason]).toEqual(["u-1", "Мошенничество"]);
    expect(key.length).toBeGreaterThanOrEqual(16);
    expect(await screen.findByText(/Заблокирован/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Разблокировать" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("unbans a banned user with a reason", async () => {
    api.getUserCard.mockResolvedValue({
      ...CARD,
      user: { ...CARD.user, banned_at: "2026-10-01T10:00:00Z", ban_reason: "Мошенничество" },
    });
    api.unbanUser.mockResolvedValue(CARD);
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Разблокировать" }));
    const dialog = screen.getByRole("dialog", { name: "Разблокировать пользователя" });
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Разобрались" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Разблокировать" }));
    await waitFor(() => {
      expect(api.unbanUser).toHaveBeenCalledWith("u-1", "Разобрались", expect.any(String));
    });
  });

  it("says when the user does not exist", async () => {
    api.getUserCard.mockRejectedValue(new ApiError(404, "Not Found", { code: "not_found" }));
    renderCard();
    expect(await screen.findByText("Пользователь не найден.")).toBeInTheDocument();
  });
});
