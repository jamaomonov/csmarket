// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen, within } from "@testing-library/react";
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
  usePathname: () => "/",
}));
vi.mock("./header/LanguageSwitcher", () => ({ LanguageSwitcher: () => <span>lang</span> }));
vi.mock("./header/MobileMenu", () => ({
  MobileMenu: ({ avatar }: { avatar?: React.ReactNode }) => (
    <span data-testid={avatar ? "menu-avatar" : "menu-burger"}>{avatar ?? "menu"}</span>
  ),
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: { balance_uzs: "1250000" } }),
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
    expect(link.querySelector("[data-steam-icon]")).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "Пополнить Steam" }).querySelector("[data-steam-icon]"),
    ).not.toBeNull();
  });

  it("shows the balance chip and the account menu to a signed-in user", () => {
    auth.value = {
      status: "signed_in",
      user: { display_name: "Player", avatar_url: null },
      signInHref: () => "",
      signOut: () => Promise.resolve(),
    };
    renderHeader();
    expect(screen.getAllByText(/1\s250\s000/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Пополнить баланс" })[0]).toHaveAttribute(
      "href",
      "/deposit",
    );
    expect(screen.getByRole("button", { name: /Player/ })).toBeInTheDocument();
    // Phones: the avatar opens the ☰ menu; the ☰ itself shows only from md to xl.
    expect(screen.getByTestId("menu-avatar").parentElement).toHaveClass("md:hidden");
    expect(screen.getByTestId("menu-burger").parentElement?.className).toBe(
      "hidden md:block xl:hidden",
    );
  });

  it("the nav: sell, market, Steam top-up and reviews, each with an icon", () => {
    auth.value = { status: "anonymous", user: null, signInHref: () => "" };
    renderHeader();
    const nav = screen.getByRole("navigation");
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Продать скины", "/sell"],
      ["Маркет", "/market"],
      ["Пополнить Steam", "/steam"],
      ["Отзывы", "/reviews"],
    ]);
    for (const a of links) expect(a.querySelector("svg")).not.toBeNull();
    // `/` is the landing now: no section is current there.
    expect(within(nav).getByRole("link", { name: "Маркет" })).not.toHaveAttribute("aria-current");
  });

  it("hides the auth skeleton and the sign-in button on phones (☰ has them)", () => {
    auth.value = { status: "loading", user: null, signInHref: () => "" };
    const { container, unmount } = renderHeader();
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton?.className.split(" ")).toEqual(expect.arrayContaining(["hidden", "md:block"]));
    unmount();
    auth.value = { status: "anonymous", user: null, signInHref: () => "/s" };
    renderHeader();
    const classes = screen.getByRole("link", { name: "Войти через Steam" }).className.split(" ");
    expect(classes).toContain("hidden");
    expect(classes).toContain("md:inline-flex");
    expect(classes).not.toContain("inline-flex");
  });
});
