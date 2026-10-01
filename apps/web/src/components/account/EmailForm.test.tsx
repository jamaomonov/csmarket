// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmailForm } from "./EmailForm";

const api = vi.hoisted(() => ({ apiPatch: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));

function setup(email: string | null = null) {
  const onChange = vi.fn();
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <EmailForm email={email} onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return { onChange };
}

describe("EmailForm", () => {
  beforeEach(() => {
    api.apiPatch.mockReset();
  });

  it("saves the address with an idempotency key and says so", async () => {
    api.apiPatch.mockResolvedValue({});
    const { onChange } = setup("old@example.com");
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("old@example.com");
    fireEvent.change(input, { target: { value: "new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Сохранено.")).toBeInTheDocument();
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

  it("sends null when the field is cleared", async () => {
    api.apiPatch.mockResolvedValue({});
    setup("old@example.com");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.apiPatch).toHaveBeenCalled();
    });
    expect((api.apiPatch.mock.calls[0] as [string, { email: string | null }])[1]).toEqual({
      email: null,
    });
  });

  it("asks to check the address on a 422", async () => {
    api.apiPatch.mockRejectedValue(new SessionApiError(422, "Unprocessable", null));
    const { onChange } = setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "a@b" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Проверьте адрес.")).toBeInTheDocument();
    });
    expect(screen.queryByText("Сохранено.")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("editing the address clears the last outcome", async () => {
    api.apiPatch.mockResolvedValue({});
    setup("old@example.com");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Сохранено.")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "newer@example.com" } });
    expect(screen.queryByText("Сохранено.")).not.toBeInTheDocument();
  });

  it("editing after a refusal clears the error", async () => {
    api.apiPatch.mockRejectedValue(new SessionApiError(422, "Unprocessable", null));
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "a@b" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Проверьте адрес.")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "a@b.uz" } });
    expect(screen.queryByText("Проверьте адрес.")).not.toBeInTheDocument();
  });
});
