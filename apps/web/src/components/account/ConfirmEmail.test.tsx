// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmEmail } from "./ConfirmEmail";

const api = vi.hoisted(() => ({ apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const TOKEN = "c2VhbGVkLXRva2VuLWZha2U";
const replace = vi.fn();

function setup() {
  vi.stubGlobal("location", {
    pathname: "/account/email/confirm",
    search: `?token=${TOKEN}`,
    hash: "",
  });
  vi.stubGlobal("history", { replaceState: replace, state: null });
  return render(
    <StrictMode>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <ConfirmEmail />
      </NextIntlClientProvider>
    </StrictMode>,
  );
}

describe("ConfirmEmail", () => {
  beforeEach(() => {
    api.apiPost.mockReset();
    replace.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the token once and says the address is confirmed", async () => {
    api.apiPost.mockResolvedValue({ email_verified: true });
    const { container } = setup();
    expect(
      await screen.findByText(
        "Почта подтверждена. Теперь письма о заказах будут приходить на неё.",
      ),
    ).toBeInTheDocument();
    expect(api.apiPost).toHaveBeenCalledTimes(1);
    expect(api.apiPost).toHaveBeenCalledWith("/api/v1/email/confirm", { token: TOKEN });
    expect(screen.getByRole("link", { name: "В профиль" })).toHaveAttribute("href", "/account");
    expect(container.innerHTML).not.toContain(TOKEN);
    expect(replace).toHaveBeenCalledWith(null, "", "/account/email/confirm");
  });

  it.each([
    ["email_token_expired", 422, "Ссылка устарела. Отправьте письмо ещё раз в профиле."],
    ["email_token_invalid", 422, "Ссылка не подходит. Отправьте письмо ещё раз в профиле."],
    ["email_token_stale", 409, "Ссылка не подходит. Отправьте письмо ещё раз в профиле."],
  ])("%s reads in our words", async (code, status, text) => {
    api.apiPost.mockRejectedValue(new SessionApiError(status, "x", { code }));
    setup();
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("an outage offers a retry", async () => {
    api.apiPost.mockRejectedValueOnce(new Error("network")).mockResolvedValue({
      email_verified: true,
    });
    setup();
    const retry = await screen.findByRole("button", { name: "Попробовать ещё раз" });
    retry.click();
    await waitFor(() => {
      expect(screen.getByText(/Почта подтверждена/)).toBeInTheDocument();
    });
  });

  it("a page without a token says the link does not fit", async () => {
    vi.stubGlobal("location", { pathname: "/account/email/confirm", search: "", hash: "" });
    vi.stubGlobal("history", { replaceState: replace, state: null });
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <ConfirmEmail />
      </NextIntlClientProvider>,
    );
    expect(
      await screen.findByText("Ссылка не подходит. Отправьте письмо ещё раз в профиле."),
    ).toBeInTheDocument();
    expect(api.apiPost).not.toHaveBeenCalled();
  });
});
