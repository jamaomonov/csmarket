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
  it("lists profile, transactions, trades, cards, referral with icons and signs out", () => {
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <AccountMenu />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Jam/ }));
    const items = screen.getAllByRole("menuitem");
    expect(items.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Профиль", "/account"],
      ["Транзакции", "/account/transactions"],
      ["Обмены", "/account/trades"],
      ["Мои карты", "/account/cards"],
      ["Реферал", "/account/referral"],
      ["Выйти", null],
    ]);
    for (const a of items) expect(a.querySelector("svg")).not.toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Выйти" }));
    expect(signOut).toHaveBeenCalledOnce();
  });
});
