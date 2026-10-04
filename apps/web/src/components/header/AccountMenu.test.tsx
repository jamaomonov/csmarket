// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { AccountMenu } from "./AccountMenu";

const signOut = vi.fn(() => Promise.resolve());
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "signed_in",
    user: { display_name: "Jam", avatar_url: null },
    signOut,
  }),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("AccountMenu", () => {
  it("lists profile, orders, balance and signs out", () => {
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <AccountMenu />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Jam/ }));
    expect(screen.getByRole("menuitem", { name: "Профиль и трейд-ссылка" })).toHaveAttribute(
      "href",
      "/account",
    );
    expect(screen.getByRole("menuitem", { name: "Мои заказы" })).toHaveAttribute(
      "href",
      "/account/orders",
    );
    expect(screen.getByRole("menuitem", { name: "Баланс и история" })).toHaveAttribute(
      "href",
      "/account/balance",
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Выйти" }));
    expect(signOut).toHaveBeenCalledOnce();
  });
});
