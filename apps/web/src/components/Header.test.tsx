// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { Header } from "./Header";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function renderHeader() {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <Header locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("Header", () => {
  it("offers Steam sign-in to a visitor", () => {
    auth.value = {
      status: "anonymous",
      user: null,
      signInHref: (l: string) => `http://api/api/v1/auth/steam/start?app=web&locale=${l}`,
    };
    renderHeader();
    const link = screen.getByRole("link", { name: "Войти через Steam" });
    expect(link.getAttribute("href")).toContain("app=web&locale=ru");
  });

  it("links a signed-in user to their account", () => {
    auth.value = {
      status: "signed_in",
      user: { display_name: "Player", avatar_url: null },
      signInHref: () => "",
    };
    renderHeader();
    expect(screen.getByRole("link", { name: /Player/ }).getAttribute("href")).toBe("/account");
  });
});
