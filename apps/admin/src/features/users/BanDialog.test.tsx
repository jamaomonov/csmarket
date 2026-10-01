import { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CARD, renderCard as renderWith } from "./fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUserCard: vi.fn(),
  banUser: vi.fn(),
  unbanUser: vi.fn(),
  adjustBalance: vi.fn(),
}));
vi.mock("./api", () => api);

function renderCard(seed?: (qc: QueryClient) => void) {
  renderWith(new QueryClient({ defaultOptions: { queries: { retry: false } } }), seed);
}

describe("BanDialog (on the user card)", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getUserCard.mockResolvedValue(CARD);
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

  it("closes the dialog and refreshes the card when the ban state was stale", async () => {
    api.banUser.mockRejectedValue(
      new ApiError(409, "Conflict", { code: "already_banned", detail: "already banned" }),
    );
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Заблокировать" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Мошенничество" },
    });
    api.getUserCard.mockResolvedValue({
      ...CARD,
      user: { ...CARD.user, banned_at: "2026-10-01T10:00:00Z", ban_reason: "Другой админ" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Заблокировать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Пользователь уже заблокирован.");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Разблокировать" })).toBeInTheDocument();
    expect(api.unbanUser).not.toHaveBeenCalled();
  });

  it("replays a ban with the same key after the dialog is reopened", async () => {
    api.banUser
      .mockRejectedValueOnce(new TypeError("network"))
      .mockReturnValue(new Promise(() => undefined));
    renderCard();
    const submit = async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Заблокировать" }));
      const dialog = screen.getByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText("Причина"), {
        target: { value: "Мошенничество" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Заблокировать" }));
      return dialog;
    };
    const dialog = await submit();
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Не получилось");
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    await submit();
    await waitFor(() => {
      expect(api.banUser).toHaveBeenCalledTimes(2);
    });
    const keys = api.banUser.mock.calls.map((c) => c[2] as string);
    expect(keys[0]).toBe(keys[1]);
  });
});
