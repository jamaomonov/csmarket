import { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminUserCard } from "./api";
import { CARD, renderCard as renderWith, STEAM_ID } from "./fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUserCard: vi.fn(),
  banUser: vi.fn(),
  unbanUser: vi.fn(),
  adjustBalance: vi.fn(),
  adjustUsdBalance: vi.fn(),
  switchUsdWallet: vi.fn(),
}));
vi.mock("./api", () => api);

function renderCard(seed?: (qc: QueryClient) => void) {
  renderWith(new QueryClient({ defaultOptions: { queries: { retry: false } } }), seed);
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
    expect(screen.getByTestId("user-balance")).toHaveTextContent(/^30\s000 сум$/);

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

  it("lists the user's orders with a link to each", async () => {
    api.getUserCard.mockResolvedValue({
      ...CARD,
      orders: [
        ...CARD.orders,
        { ...CARD.orders[0], number: "O2", status: "returned", attention_reason: "rolled_back" },
      ],
    });
    renderCard();
    const orders = await screen.findByRole("region", { name: "Заказы" });
    expect(within(orders).getByRole("link", { name: "O7K2M9QX" })).toHaveAttribute(
      "href",
      "/orders/O7K2M9QX",
    );
    expect(within(orders).getByRole("link", { name: "O2" })).toHaveAttribute("href", "/orders/O2");
    expect(
      within(orders)
        .getAllByTestId("order-status")
        .map((c) => c.textContent),
    ).toEqual(["покупаем", "обмен не состоялся"]);
    expect(within(orders).getByTestId("order-attention")).toHaveTextContent(
      "откат после получения",
    );
  });

  it("says there are no orders yet", async () => {
    api.getUserCard.mockResolvedValue({ ...CARD, orders: [] });
    renderCard();
    const orders = await screen.findByRole("region", { name: "Заказы" });
    expect(orders).toHaveTextContent("Заказов пока не было.");
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
    await waitFor(() => {
      expect(screen.getByTestId("user-balance")).toHaveTextContent(/^80\s000 сум$/);
    });
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

  it("drops an open adjustment when navigating to another (cached) user", async () => {
    const other: AdminUserCard = {
      ...CARD,
      user: { ...CARD.user, id: "a-1", display_name: "Boss", steam_id: "76561190000000002" },
      balance_uzs: "0",
    };
    api.adjustBalance.mockResolvedValue(other);
    renderCard((qc) => {
      qc.setQueryData(["admin", "users", "card", "a-1"], other);
    });
    await openAdjust("50000", "Компенсация за задержку");
    expect(await screen.findByTestId("adjust-confirm")).toBeInTheDocument();
    // The history's actor link goes to the other account's card.
    const history = screen.getByRole("region", { name: "История баланса" });
    fireEvent.click(within(history).getByRole("link", { name: "администратор" }));
    expect(await screen.findByRole("heading", { name: "Boss" })).toBeInTheDocument();
    expect(screen.queryByTestId("adjust-confirm-step")).not.toBeInTheDocument();
    expect(screen.queryByTestId("adjust-form")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Начислить/ })).not.toBeInTheDocument();
    expect(api.adjustBalance).not.toHaveBeenCalled();
  });

  it("says in Russian when a key was already used with other data", async () => {
    api.adjustBalance.mockRejectedValue(
      new ApiError(409, "Conflict", {
        code: "idempotency_mismatch",
        detail: "Idempotency-Key reused with a different request",
      }),
    );
    renderCard();
    await openAdjust("50000", "Компенсация за задержку");
    fireEvent.click(await screen.findByRole("button", { name: /Начислить/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Эта операция уже была выполнена с другими данными.");
    expect(alert).not.toHaveTextContent("Idempotency-Key");
  });

  it("says when the user does not exist", async () => {
    api.getUserCard.mockRejectedValue(new ApiError(404, "Not Found", { code: "not_found" }));
    renderCard();
    expect(await screen.findByText("Пользователь не найден.")).toBeInTheDocument();
  });

  describe("USD wallet", () => {
    const USD_CARD: AdminUserCard = {
      ...CARD,
      usd_wallet_enabled: true,
      balance_usd: "250.000",
      usd_entries: [
        {
          id: "x-1",
          kind: "admin_adjust_usd",
          currency: "USD",
          amount_uzs: "0",
          amount_usd: "+250.000",
          created_at: "2026-10-09T10:00:00Z",
          reference_number: null,
          actor: "admin:a-1",
          reason: "Стартовый баланс",
        },
      ],
    };

    it("shows the USD block with the balance and the dollar lines", async () => {
      api.getUserCard.mockResolvedValue(USD_CARD);
      renderCard();
      const block = await screen.findByTestId("usd-block");
      expect(within(block).getByText("включён")).toBeInTheDocument();
      expect(screen.getByTestId("user-balance-usd")).toHaveTextContent("Баланс: $250.000");
      const history = screen.getByRole("region", { name: "История USD" });
      expect(within(history).getByText("Корректировка USD")).toBeInTheDocument();
      expect(within(history).getByText("+$250.000")).toBeInTheDocument();
      expect(within(history).getByText(/Стартовый баланс/)).toBeInTheDocument();
    });

    it("switches the wallet on with a reason and a key (PUT)", async () => {
      api.switchUsdWallet.mockResolvedValue(USD_CARD);
      renderCard();
      fireEvent.click(await screen.findByRole("button", { name: "Включить USD-кошелёк" }));
      fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "Пилот" } });
      fireEvent.click(screen.getByRole("button", { name: "Включить" }));
      await waitFor(() => {
        expect(api.switchUsdWallet).toHaveBeenCalledTimes(1);
      });
      const [id, enabled, reason, key] = api.switchUsdWallet.mock.calls[0] as [
        string,
        boolean,
        string,
        string,
      ];
      expect([id, enabled, reason]).toEqual(["u-1", true, "Пилот"]);
      expect(key.length).toBeGreaterThanOrEqual(16);
      expect(await screen.findByText("включён")).toBeInTheDocument();
    });

    it("credits dollars through the USD endpoint after a confirm step", async () => {
      api.adjustUsdBalance.mockResolvedValue(USD_CARD);
      renderCard();
      fireEvent.click(await screen.findByRole("button", { name: "Изменить баланс" }));
      fireEvent.click(screen.getByRole("button", { name: "USD" }));
      fireEvent.change(screen.getByLabelText("Сумма, USD"), { target: { value: "250" } });
      fireEvent.change(screen.getByLabelText("Причина изменения"), {
        target: { value: "Стартовый баланс" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
      fireEvent.click(await screen.findByRole("button", { name: "Начислить $250.000" }));
      await waitFor(() => {
        expect(api.adjustUsdBalance).toHaveBeenCalledWith(
          "u-1",
          "250.000",
          "Стартовый баланс",
          expect.any(String),
        );
      });
      expect(api.adjustBalance).not.toHaveBeenCalled();
    });

    it("refuses a comma and groups the confirm amount so 1000 is not read as 1", async () => {
      api.adjustUsdBalance.mockResolvedValue(USD_CARD);
      renderCard();
      fireEvent.click(await screen.findByRole("button", { name: "Изменить баланс" }));
      fireEvent.click(screen.getByRole("button", { name: "USD" }));
      fireEvent.change(screen.getByLabelText("Причина изменения"), {
        target: { value: "Стартовый баланс" },
      });
      fireEvent.change(screen.getByLabelText("Сумма, USD"), { target: { value: "1,000" } });
      fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Только точка");
      fireEvent.change(screen.getByLabelText("Сумма, USD"), { target: { value: "1000" } });
      fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
      expect(
        await screen.findByRole("button", { name: "Начислить $1\u00a0000.000" }),
      ).toBeInTheDocument();
    });

    it("clears the amount and the error when the currency is switched", async () => {
      renderCard();
      fireEvent.click(await screen.findByRole("button", { name: "Изменить баланс" }));
      fireEvent.change(screen.getByLabelText("Сумма, сум"), { target: { value: "50 000" } });
      fireEvent.click(screen.getByRole("button", { name: "USD" }));
      expect(screen.getByLabelText("Сумма, USD")).toHaveValue("");
      fireEvent.change(screen.getByLabelText("Причина изменения"), {
        target: { value: "Стартовый баланс" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(screen.queryByTestId("adjust-confirm-step")).not.toBeInTheDocument();
      expect(api.adjustUsdBalance).not.toHaveBeenCalled();
    });

    it("refuses a dollar amount with four decimals", async () => {
      renderCard();
      fireEvent.click(await screen.findByRole("button", { name: "Изменить баланс" }));
      fireEvent.click(screen.getByRole("button", { name: "USD" }));
      fireEvent.change(screen.getByLabelText("Сумма, USD"), { target: { value: "1.2345" } });
      fireEvent.change(screen.getByLabelText("Причина изменения"), {
        target: { value: "Стартовый баланс" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("в долларах");
      expect(api.adjustUsdBalance).not.toHaveBeenCalled();
    });
  });
});
