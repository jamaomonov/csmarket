// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { AccountView } from "./AccountView";

import type { ReactNode } from "react";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/lib/api", () => ({ session: { apiPut: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn() } }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function renderView() {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <AccountView locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("AccountView", () => {
  it("offers Steam sign-in when signed out", () => {
    auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/start?l=${l}` };
    renderView();
    expect(screen.getByText("Войдите через Steam, чтобы открыть аккаунт.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Войти через Steam" }).getAttribute("href")).toBe(
      "/start?l=ru",
    );
  });

  it("says so when the account is suspended", () => {
    auth.value = { status: "suspended", user: null, signInHref: () => "" };
    renderView();
    expect(screen.getByText("Аккаунт заблокирован.")).toBeInTheDocument();
  });

  it("shows the profile, trade link and email forms when signed in", () => {
    auth.value = {
      status: "signed_in",
      signInHref: () => "",
      signOut: vi.fn(),
      refreshMe: vi.fn(),
      user: {
        display_name: "Player",
        avatar_url: null,
        email: "p@example.com",
        trade_link: null,
        trade_link_verdict: null,
        trade_link_reason: null,
      },
    };
    renderView();
    expect(screen.getByText("Player")).toBeInTheDocument();
    expect(screen.getByText("Ссылка на обмен", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("p@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выйти" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Баланс/ })).toHaveAttribute(
      "href",
      "/account/balance",
    );
    expect(screen.getByRole("link", { name: "Мои заказы" })).toHaveAttribute(
      "href",
      "/account/orders",
    );
  });
});
