// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { MobileMenu } from "./MobileMenu";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ status: "signed_in", signInHref: () => "", signOut: () => Promise.resolve() }),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  usePathname: () => "/",
  getPathname: ({ href }: { href: string }) => href,
}));

describe("MobileMenu", () => {
  it("has the nav and the account entries, with icons", () => {
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <MobileMenu locale="ru" />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Меню" }));
    const links = screen
      .getAllByRole("menuitem")
      .filter((a) => a.tagName === "A")
      .map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual([
      ["Продать скины", "/sell"],
      ["Маркет", "/"],
      ["Пополнить Steam", "/steam"],
      ["Отзывы", "/reviews"],
      ["Профиль", "/account"],
      ["Транзакции", "/account/transactions"],
      ["Обмены", "/account/trades"],
      ["Мои карты", "/account/cards"],
      ["Реферал", "/account/referral"],
    ]);
    expect(screen.getByRole("menuitem", { name: "Маркет" }).querySelector("svg")).not.toBeNull();
  });
});
