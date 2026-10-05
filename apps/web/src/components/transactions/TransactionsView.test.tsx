// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { TransactionsView } from "./TransactionsView";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/account/OrdersList", () => ({ OrdersList: () => <p>orders-list</p> }));
vi.mock("@/components/balance/EntriesList", () => ({ EntriesList: () => <p>entries-list</p> }));

function view(tab: "purchases" | "balance") {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <TransactionsView locale="ru" tab={tab} />
    </NextIntlClientProvider>,
  );
}

describe("TransactionsView", () => {
  it("purchases first; the tabs link to each other", () => {
    auth.value = { status: "signed_in", user: {}, signInHref: () => "/in" };
    view("purchases");
    expect(screen.getByText("orders-list")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Покупки" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Баланс" })).toHaveAttribute(
      "href",
      "/account/transactions?tab=balance",
    );
  });

  it("the balance tab shows the balance history", () => {
    auth.value = { status: "signed_in", user: {}, signInHref: () => "/in" };
    view("balance");
    expect(screen.getByText("entries-list")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Покупки" })).toHaveAttribute(
      "href",
      "/account/transactions",
    );
  });

  it("asks a visitor to sign in before the balance history", () => {
    auth.value = { status: "anonymous", user: null, signInHref: () => "/in" };
    view("balance");
    expect(screen.queryByText("entries-list")).toBeNull();
    expect(screen.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute("href", "/in");
  });
});
