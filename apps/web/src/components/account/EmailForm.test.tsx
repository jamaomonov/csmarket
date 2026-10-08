// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EmailForm } from "./EmailForm";

const api = vi.hoisted(() => ({ apiPatch: vi.fn(), apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));

interface Props {
  email?: string | null;
  verified?: boolean;
  sentAt?: string | null;
}

function setup({ email = null, verified = false, sentAt = null }: Props = {}) {
  const onChange = vi.fn();
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <EmailForm email={email} verified={verified} sentAt={sentAt} onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return { onChange };
}

const resend = () => screen.getByRole("button", { name: "Отправить ещё раз" });
/** A saved address reads as text; «Изменить» opens the form. */
const edit = () => {
  fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
};

describe("EmailForm", () => {
  beforeEach(() => {
    api.apiPatch.mockReset();
    api.apiPost.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("without an email: what it is for and «Добавить», which opens the form", () => {
    setup();
    expect(screen.getByText("Для писем о заказах.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Отправить ещё раз" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("saves a new address with a key and says a letter is on its way", async () => {
    api.apiPatch.mockResolvedValue({});
    const { onChange } = setup({ email: "old@example.com", verified: true });
    expect(screen.getByText("old@example.com")).toBeInTheDocument();
    edit();
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("old@example.com");
    fireEvent.change(input, { target: { value: "new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(
        screen.getByText("Мы отправили письмо со ссылкой — откройте его."),
      ).toBeInTheDocument();
    });
    const [path, body, opts] = api.apiPatch.mock.calls[0] as [
      string,
      { email: string | null },
      { idempotencyKey: string },
    ];
    expect(path).toBe("/api/v1/me");
    expect(body).toEqual({ email: "new@example.com" });
    expect(opts.idempotencyKey.length).toBeGreaterThanOrEqual(16);
    expect(onChange).toHaveBeenCalled();
  });

  it("a second address within a minute is saved but says to send the letter later", async () => {
    api.apiPatch.mockResolvedValue({ email_verification_sent_at: null });
    setup({ email: "old@example.com" });
    edit();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Отправить ещё раз можно через минуту.")).toBeInTheDocument();
    expect(
      screen.queryByText("Мы отправили письмо со ссылкой — откройте его."),
    ).not.toBeInTheDocument();
  });

  it("clearing the field sends null and says saved", async () => {
    api.apiPatch.mockResolvedValue({});
    setup({ email: "old@example.com" });
    edit();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Сохранено.")).toBeInTheDocument();
    });
    expect((api.apiPatch.mock.calls[0] as [string, { email: string | null }])[1]).toEqual({
      email: null,
    });
  });

  it("asks to check the address on a 422, and editing clears it", async () => {
    api.apiPatch.mockRejectedValue(new SessionApiError(422, "Unprocessable", null));
    const { onChange } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "a@b" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Проверьте адрес.")).toBeInTheDocument();
    });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "a@b.uz" } });
    expect(screen.queryByText("Проверьте адрес.")).not.toBeInTheDocument();
  });

  it("verified: a badge, no resend", () => {
    setup({ email: "a@example.com", verified: true });
    expect(screen.getByRole("img", { name: "Подтверждена" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Отправить ещё раз" })).not.toBeInTheDocument();
  });

  it("unverified: says where the letter went and resends it once a minute", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.apiPost.mockResolvedValue({ sent: true });
    setup({ email: "a@example.com", sentAt: "2000-01-01T00:00:00Z" });
    expect(
      screen.getByText("Почта не подтверждена. Мы отправили письмо на a@example.com."),
    ).toBeInTheDocument();
    fireEvent.click(resend());
    await waitFor(() => {
      expect(api.apiPost).toHaveBeenCalledTimes(1);
    });
    const [path, , opts] = api.apiPost.mock.calls[0] as [
      string,
      unknown,
      { idempotencyKey: string },
    ];
    expect(path).toBe("/api/v1/me/email/verification");
    expect(opts.idempotencyKey.length).toBeGreaterThanOrEqual(16);
    await waitFor(() => {
      expect(resend()).toBeDisabled();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(resend()).toBeEnabled();
  });

  it("a letter queued in the last minute keeps resend off", () => {
    setup({ email: "a@example.com", sentAt: new Date().toISOString() });
    expect(resend()).toBeDisabled();
  });

  it("a 429 says to wait a minute", async () => {
    api.apiPost.mockRejectedValue(
      new SessionApiError(429, "Too Many Requests", { code: "email_verify_cooldown" }),
    );
    setup({ email: "a@example.com", sentAt: "2000-01-01T00:00:00Z" });
    fireEvent.click(resend());
    expect(await screen.findByText("Отправить ещё раз можно через минуту.")).toBeInTheDocument();
  });
});
