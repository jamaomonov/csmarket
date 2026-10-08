// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { AccountSidebar } from "./AccountSidebar";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  usePathname: () => "/account/trades",
}));

describe("AccountSidebar", () => {
  it("lists the profile sections with icons, marks the current one", () => {
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
      ["Реферал", "/account/referral"],
    ]);
    for (const a of links) expect(a.querySelector("svg")).not.toBeNull();
    expect(within(nav).getByRole("link", { name: "Обмены" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Профиль" })).not.toHaveAttribute("aria-current");
    // «Выйти» lives in the account menu, not among the profile's tabs.
    expect(within(nav).queryByRole("button", { name: "Выйти" })).toBeNull();
  });
});
