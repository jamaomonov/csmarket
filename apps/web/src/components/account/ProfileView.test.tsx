// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { ProfileView } from "./ProfileView";

import type { ReactNode } from "react";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("./CardsList", () => ({ CardsList: () => <p>cards-list</p> }));
vi.mock("@/lib/api", () => ({ session: { apiPut: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn() } }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function renderView() {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <ProfileView locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("ProfileView", () => {
  it("offers Steam sign-in when signed out", () => {
    auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/start?l=${l}` };
    renderView();
    expect(screen.getByText("Войдите через Steam, чтобы открыть профиль.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Войти через Steam" }).getAttribute("href")).toBe(
      "/start?l=ru",
    );
  });

  it("says so when the account is suspended", () => {
    auth.value = { status: "suspended", user: null, signInHref: () => "" };
    renderView();
    expect(screen.getByText("Аккаунт заблокирован.")).toBeInTheDocument();
  });

  it("shows who you are: avatar, name, since when, Steam ID and the Steam profile", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    auth.value = signedIn();
    renderView();
    expect(screen.getByRole("heading", { level: 2, name: "Player" })).toBeInTheDocument();
    expect(screen.getByText("P")).toBeInTheDocument(); // no Steam avatar: the initial
    expect(screen.getByText(/На csmarket с 28 сентября 2026/)).toBeInTheDocument();
    expect(screen.getByText("76561198000000777")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Профиль в Steam" })).toHaveAttribute(
      "href",
      "https://steamcommunity.com/profiles/76561198000000777",
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Скопировать Steam ID" }));
      await Promise.resolve();
    });
    expect(writeText).toHaveBeenCalledWith("76561198000000777");
    expect(screen.getByText("Скопировано")).toBeInTheDocument();
  });

  it("«Ваш аккаунт»: the trade link, the email and the referral code (soon)", () => {
    auth.value = signedIn();
    renderView();
    expect(screen.getByRole("heading", { name: "Ваш аккаунт" })).toBeInTheDocument();
    expect(screen.getByText("Ссылка на обмен", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("p@example.com")).toBeInTheDocument();
    expect(screen.getByText("Реферальный код", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText("Скоро")).toBeInTheDocument();
  });
});

function signedIn() {
  return {
    status: "signed_in",
    signInHref: () => "",
    signOut: vi.fn(),
    refreshMe: vi.fn(),
    user: {
      steam_id: "76561198000000777",
      display_name: "Player",
      avatar_url: null,
      created_at: "2026-09-28T10:00:00Z",
      email: "p@example.com",
      email_verified: false,
      trade_link: null,
      trade_link_verdict: null,
      trade_link_reason: null,
    },
  };
}
