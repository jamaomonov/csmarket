// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TradeLinkForm } from "./TradeLinkForm";

const api = vi.hoisted(() => ({ apiPut: vi.fn(), apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));
const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12";

function setup(initial: string | null = null, verdict: "ok" | null = null) {
  const onChange = vi.fn();
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <TradeLinkForm initial={{ trade_link: initial, verdict, reason: null }} onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return { onChange };
}

describe("TradeLinkForm", () => {
  beforeEach(() => {
    api.apiPut.mockReset();
    api.apiPost.mockReset();
  });

  it("explains where to find the link", () => {
    setup();
    fireEvent.click(screen.getByText("Где взять?"));
    expect(screen.getByText(/Предложения обмена/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Открыть страницу в Steam" }).getAttribute("href"),
    ).toContain("tradeoffers/privacy");
  });

  it("saves with an idempotency key, then checks and shows the verdict", async () => {
    api.apiPut.mockResolvedValue({
      trade_link: LINK,
      verdict: null,
      reason: null,
      checked_at: null,
    });
    api.apiPost.mockResolvedValue({
      trade_link: LINK,
      verdict: "bad",
      reason: "hold",
      checked_at: "2026-10-01T00:00:00Z",
    });
    const { onChange } = setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText(/Steam задерживает обмены/)).toBeInTheDocument();
    });
    const [, body, opts] = api.apiPut.mock.calls[0] as [
      string,
      { url: string },
      { idempotencyKey: string },
    ];
    expect(body.url).toBe(LINK);
    expect(opts.idempotencyKey.length).toBeGreaterThanOrEqual(16);
    expect(api.apiPost).toHaveBeenCalledWith("/api/v1/me/trade-link/check", {});
    expect(onChange).toHaveBeenCalled();
  });

  it("shows the API's reason when the link is someone else's", async () => {
    api.apiPut.mockRejectedValue(
      new SessionApiError(422, "Unprocessable", { code: "trade_link_not_yours" }),
    );
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText(/другого аккаунта Steam/)).toBeInTheDocument();
    });
    expect(api.apiPost).not.toHaveBeenCalled();
  });

  it("falls back to unavailable copy when the check call fails", async () => {
    api.apiPut.mockResolvedValue({
      trade_link: LINK,
      verdict: null,
      reason: null,
      checked_at: null,
    });
    api.apiPost.mockRejectedValue(new SessionApiError(500, "Server Error", null));
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText(/Сейчас не получилось проверить/)).toBeInTheDocument();
    });
  });

  it("a failed save hides the verdict of the previous link", async () => {
    api.apiPut.mockRejectedValue(
      new SessionApiError(422, "Unprocessable", { code: "trade_link_not_yours" }),
    );
    setup(LINK, "ok");
    // Saved and working: the link as text, a tick, «Изменить» opens the form.
    expect(screen.getByText(LINK)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Ссылка работает/ })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    expect(screen.getByText(/Ссылка работает/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: LINK.replace("39734273", "39734274") },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText(/другого аккаунта Steam/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Ссылка работает/)).not.toBeInTheDocument();
  });

  it("editing the link clears the error", async () => {
    api.apiPut.mockRejectedValue(
      new SessionApiError(422, "Unprocessable", { code: "trade_link_invalid" }),
    );
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "https://x.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText(/Это не ссылка на обмен Steam/)).toBeInTheDocument();
    });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: LINK } });
    expect(screen.queryByText(/Это не ссылка на обмен Steam/)).not.toBeInTheDocument();
  });
});
