// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { AccountSidebar } from "./AccountSidebar";

const signOut = vi.fn(() => Promise.resolve());
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ status: "signed_in", signOut }) }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  usePathname: () => "/account/trades",
}));

describe("AccountSidebar", () => {
  it("lists the profile sections with icons, marks the current one and signs out", () => {
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <AccountSidebar />
      </NextIntlClientProvider>,
    );
    const nav = screen.getByRole("navigation", { name: "Разделы профиля" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Профиль", "/account"],
      ["Транзакции", "/account/transactions"],
      ["Обмены", "/account/trades"],
      ["Мои карты", "/account/cards"],
      ["Реферал", "/account/referral"],
    ]);
    for (const a of links) expect(a.querySelector("svg")).not.toBeNull();
    expect(within(nav).getByRole("link", { name: "Обмены" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Профиль" })).not.toHaveAttribute("aria-current");
    fireEvent.click(within(nav).getByRole("button", { name: "Выйти" }));
    expect(signOut).toHaveBeenCalledOnce();
  });
});
