import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL, PAYOUT_ROW } from "./fixtures";
import { PayoutDetail } from "./PayoutDetail";

import { useAuthStore } from "@/features/auth/authStore";
import { asPhone } from "@/test/phone";

const api = vi.hoisted(() => ({
  getPayout: vi.fn(),
  revealCard: vi.fn(),
  markPaid: vi.fn(),
  rejectPayout: vi.fn(),
  claimPayout: vi.fn(),
  releasePayout: vi.fn(),
  cancelPayout: vi.fn(),
  undoPayout: vi.fn(),
}));
vi.mock("./payoutsApi", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
const salesApi = vi.hoisted(() => ({ setSellBlock: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...salesApi }));

const NUMBER = "9860 1234 5678 9015";
const ME = { id: "admin-1", display_name: "Owner", roles: ["admin"] };
const OTHER = { id: "admin-2", display_name: "Petr" };

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/payouts/p-1"]}>
        <Routes>
          <Route
            path="/payouts/:id"
            element={
              <>
                <Link to="/payouts/p-2">next</Link>
                <PayoutDetail />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const numberField = () => screen.queryByLabelText<HTMLInputElement>("Номер карты");

describe("PayoutDetail", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    salesApi.setSellBlock.mockReset();
    api.getPayout.mockResolvedValue(PAYOUT_DETAIL);
    api.revealCard.mockResolvedValue({ number: "9860123456789015" });
    useAuthStore.setState({ status: "admin", me: ME });
  });
  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  });

  it("puts the amount, the card and the sale on top; never the number by itself", async () => {
    renderPage();
    const pay = await screen.findByTestId("pay-block");
    expect(within(pay).getByText(/147\s400 сум/)).toBeInTheDocument();
    expect(within(pay).getByText("Humo")).toBeInTheDocument();
    expect(within(pay).getByText("•••• 9015")).toBeInTheDocument();
    expect(within(pay).getByRole("button", { name: "Скопировать сумму" })).toBeInTheDocument();
    expect(screen.getByText(/−7\s800 сум/)).toBeInTheDocument();
    expect(numberField()).toBeNull();
  });

  it("copies the amount as digits", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Скопировать сумму" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("147400");
    });
  });

  it("«Показать номер» asks the audited reveal and shows a selectable field", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    await waitFor(() => {
      expect(numberField()?.value).toBe(NUMBER);
    });
    expect(numberField()).toHaveAttribute("readonly");
    expect(api.revealCard).toHaveBeenCalledWith("p-1", "show");
  });

  it("«Скопировать номер» reveals for a copy and puts the digits on the clipboard", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Скопировать номер" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("9860123456789015");
    });
    expect(api.revealCard).toHaveBeenCalledWith("p-1", "copy");
    expect(await screen.findByText("Номер скопирован.")).toBeInTheDocument();
  });

  it("leaves the number on screen to copy by hand when the clipboard refuses", async () => {
    Object.assign(document, { execCommand: vi.fn(() => false) });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Скопировать номер" }));
    expect(await screen.findByText(/нажмите на номер/)).toBeInTheDocument();
    expect(numberField()?.value).toBe(NUMBER);
  });

  it("«Беру в работу» claims the request with a key", async () => {
    api.claimPayout.mockResolvedValue(PAYOUT_DETAIL);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Беру в работу" }));
    await waitFor(() => {
      expect(api.claimPayout).toHaveBeenCalledWith(
        "p-1",
        false,
        expect.stringMatching(/^admin-payout-claim-/),
      );
    });
  });

  it("a request another admin is paying cannot be paid until taken over", async () => {
    const taken = {
      ...PAYOUT_DETAIL,
      request: { ...PAYOUT_ROW, claimed_by: OTHER, claimed_until: "2026-10-15T10:15:00Z" },
    };
    api.getPayout.mockResolvedValue(taken);
    api.claimPayout.mockResolvedValue(PAYOUT_DETAIL);
    renderPage();
    expect(await screen.findByText(/Платит Petr/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выплачено" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Забрать себе" }));
    await waitFor(() => {
      expect(api.claimPayout).toHaveBeenCalledWith("p-1", true, expect.any(String));
    });
  });

  it("my own claim shows «Вы платите» and can be released", async () => {
    const mine = {
      ...PAYOUT_DETAIL,
      request: { ...PAYOUT_ROW, claimed_by: ME, claimed_until: "2026-10-15T10:15:00Z" },
    };
    api.getPayout.mockResolvedValue(mine);
    api.releasePayout.mockResolvedValue(PAYOUT_DETAIL);
    renderPage();
    expect(await screen.findByText(/Вы платите/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выплачено" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Отпустить" }));
    await waitFor(() => {
      expect(api.releasePayout).toHaveBeenCalledWith("p-1", expect.any(String));
    });
  });

  it("«Выплачено» restates amount, card and seller, then sends the note with a key", async () => {
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Выплачено" }));
    const confirm = screen.getByRole("group", { name: "Подтверждение" });
    expect(confirm).toHaveTextContent(
      /Выплачено 147\s400 сум на Humo •••• 9015, получатель Ivan\?/,
    );
    fireEvent.change(screen.getByLabelText("Комментарий (номер чека банка)"), {
      target: { value: "Click #1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Да, выплачено" }));
    await waitFor(() => {
      expect(api.markPaid).toHaveBeenCalledWith(
        "p-1",
        "Click #1",
        expect.stringMatching(/^admin-payout-/),
        null,
      );
    });
  });

  it("a banned seller is shown in red and paid only with a reason", async () => {
    api.getPayout.mockResolvedValue({
      ...PAYOUT_DETAIL,
      paid_needs_override: true,
      risk: { ...PAYOUT_DETAIL.risk, banned: true, ban_reason: "fraud" },
    });
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    expect(await screen.findByText(/Аккаунт заблокирован — не платите/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Выплачено" }));
    const yes = screen.getByRole("button", { name: "Да, выплачено" });
    expect(yes).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Почему всё равно платите/), {
      target: { value: "owner said" },
    });
    fireEvent.click(yes);
    await waitFor(() => {
      expect(api.markPaid).toHaveBeenCalledWith("p-1", null, expect.any(String), "owner said");
    });
  });

  it("a reverted sale is paid only with a reason that names the revert", async () => {
    api.getPayout.mockResolvedValue({
      ...PAYOUT_DETAIL,
      paid_needs_override: true,
      request: { ...PAYOUT_DETAIL.request, flags: ["rolled_back"] },
    });
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Выплачено" }));
    expect(screen.getByRole("button", { name: "Да, выплачено" })).toBeDisabled();
    expect(screen.getByLabelText(/Обмен отменён — скины вернулись к продавцу/)).toBeInTheDocument();
  });

  it("«Отклонить» needs a reason", async () => {
    api.rejectPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отклонить" }));
    const confirm = screen.getByRole("button", { name: "Да, отклонить" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина (видят только администраторы)"), {
      target: { value: "Карта заблокирована" },
    });
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(api.rejectPayout).toHaveBeenCalledWith(
        "p-1",
        "Карта заблокирована",
        expect.stringMatching(/^admin-payout-/),
      );
    });
  });

  it("offers «Вернуть в очередь» right after a decision", async () => {
    const paid = {
      ...PAYOUT_DETAIL,
      can_decide: false,
      request: { ...PAYOUT_ROW, status: "paid" as const },
      undo_until: "2099-01-01T00:10:00Z",
    };
    api.getPayout.mockResolvedValue(paid);
    api.undoPayout.mockResolvedValue(PAYOUT_DETAIL);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Вернуть в очередь" }));
    fireEvent.change(screen.getByLabelText("Почему возвращаете"), {
      target: { value: "не та строка" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Да, вернуть в очередь" }));
    await waitFor(() => {
      expect(api.undoPayout).toHaveBeenCalledWith("p-1", "не та строка", expect.any(String));
    });
  });

  it("offers «Отменить (откат)» when the sale was reverted", async () => {
    api.getPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_cancel: true });
    api.cancelPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Отменить (откат)" }));
    fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "откат" } });
    fireEvent.click(screen.getByRole("button", { name: "Да, отменить" }));
    await waitFor(() => {
      expect(api.cancelPayout).toHaveBeenCalledWith("p-1", "откат", expect.any(String));
    });
  });

  it("hides «Отклонить» once Skinslink reverted the trade: the API would refuse it", async () => {
    api.getPayout.mockResolvedValue({
      ...PAYOUT_DETAIL,
      can_cancel: true,
      paid_needs_override: true,
      request: { ...PAYOUT_DETAIL.request, flags: ["rolled_back"] },
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Отменить (откат)" })).toBeInTheDocument();
    expect(screen.getByText(/Если деньги ещё не ушли — «Отменить \(откат\)»/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Отклонить" })).toBeNull();
  });

  it("one green button per step: «Беру в работу», then «Выплачено»", async () => {
    renderPage();
    const take = await screen.findByRole("button", { name: "Беру в работу" });
    expect(take.className).toContain("bg-accent");
    expect(screen.getByRole("button", { name: "Выплачено" }).className).not.toContain("bg-accent");
    expect(screen.getByRole("button", { name: "Скопировать номер" }).className).not.toContain(
      "bg-accent",
    );
  });

  it("«Выплачено» is the green one once the request is mine", async () => {
    api.getPayout.mockResolvedValue({
      ...PAYOUT_DETAIL,
      request: { ...PAYOUT_ROW, claimed_by: ME, claimed_until: "2026-10-15T10:15:00Z" },
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Выплачено" })).toHaveClass("bg-accent");
  });

  it("on a phone the confirm is a bottom sheet that confirms", async () => {
    const restore = asPhone();
    try {
      api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
      renderPage();
      fireEvent.click(await screen.findByRole("button", { name: "Выплачено" }));
      const sheet = screen.getByRole("dialog", { name: "Подтвердите выплату" });
      expect(within(sheet).getByText(/^147\s400 сум$/)).toBeInTheDocument();
      expect(within(sheet).getByText("•••• 9015")).toBeInTheDocument();
      fireEvent.click(within(sheet).getByRole("button", { name: "Да, выплачено" }));
      await waitFor(() => {
        expect(api.markPaid).toHaveBeenCalled();
      });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).toBeNull();
      });
    } finally {
      restore();
    }
  });

  it("says a request was canceled because the seller reverted the trade", async () => {
    api.getPayout.mockResolvedValue({
      ...PAYOUT_DETAIL,
      request: { ...PAYOUT_ROW, status: "canceled", flags: ["seller_reverted"] },
      can_decide: false,
    });
    renderPage();
    expect(await screen.findByText("Отменено: продавец отменил обмен")).toBeInTheDocument();
  });

  it("shows the risks and blocks selling from the page", async () => {
    api.getPayout.mockResolvedValue({
      ...PAYOUT_DETAIL,
      risk: { ...PAYOUT_DETAIL.risk, shared_card_users: [{ id: "u-9", display_name: "Twin" }] },
    });
    salesApi.setSellBlock.mockResolvedValue({});
    renderPage();
    const risks = await screen.findByRole("region", { name: "Риски" });
    expect(within(risks).getByRole("link", { name: "Twin" })).toHaveAttribute("href", "/users/u-9");
    fireEvent.click(within(risks).getByRole("button", { name: "Запретить выкуп" }));
    fireEvent.change(within(risks).getByLabelText(/Причина запрета/), {
      target: { value: "carousel" },
    });
    fireEvent.click(within(risks).getByRole("button", { name: "Да, запретить" }));
    await waitFor(() => {
      expect(salesApi.setSellBlock).toHaveBeenCalledWith(
        "u-1",
        true,
        "carousel",
        expect.stringMatching(/^admin-sell-block-/),
      );
    });
  });

  it("drops the revealed number after a decision", async () => {
    api.markPaid.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    await waitFor(() => {
      expect(numberField()).not.toBeNull();
    });
    fireEvent.click(screen.getByRole("button", { name: "Выплачено" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, выплачено" }));
    await waitFor(() => {
      expect(numberField()).toBeNull();
    });
  });

  it("hides the number again after a minute", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
      await waitFor(() => {
        expect(numberField()).not.toBeNull();
      });
      act(() => {
        vi.advanceTimersByTime(61_000);
      });
      expect(numberField()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("never shows one payout's number under another payout", async () => {
    const other = {
      ...PAYOUT_DETAIL,
      request: { ...PAYOUT_ROW, id: "p-2", card_masked: "•••• 1111" },
    };
    api.getPayout.mockImplementation((id: string) =>
      Promise.resolve(id === "p-2" ? other : PAYOUT_DETAIL),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать номер" }));
    await waitFor(() => {
      expect(numberField()).not.toBeNull();
    });
    fireEvent.click(screen.getByRole("link", { name: "next" }));
    await screen.findByText("•••• 1111");
    expect(numberField()).toBeNull();
  });

  it("hides the actions when the request can no longer be decided", async () => {
    api.getPayout.mockResolvedValue({ ...PAYOUT_DETAIL, can_decide: false });
    renderPage();
    await screen.findByTestId("pay-block");
    expect(screen.queryByRole("button", { name: "Выплачено" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Показать номер" })).toBeNull();
  });
});
