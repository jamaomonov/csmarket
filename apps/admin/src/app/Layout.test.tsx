import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Layout } from "./Layout";

vi.mock("@/features/auth/authStore", () => ({
  useAuthStore: (pick: (s: { me: null; signOut: () => void }) => unknown) =>
    pick({ me: null, signOut: () => undefined }),
}));

const getDashboard = vi.fn();
vi.mock("@/features/dashboard/api", () => ({
  getDashboard: (days: number) => getDashboard(days) as unknown,
}));

function renderLayout(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getDashboard.mockResolvedValue({ attention: 3, payouts: { to_pay_count: 2 } });
});

describe("Layout", () => {
  it("a top bar: direct links and two menus, no API keys page", () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Дашборд", "Обмены", "Пользователи", "Платежи"]);
    expect(within(nav).getByRole("button", { name: /Выкуп/ })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /Настройки/ })).toBeInTheDocument();
    expect(screen.queryByText("API-ключи")).toBeNull();
  });

  it("a menu opens its pages", () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    fireEvent.click(within(nav).getByRole("button", { name: /Настройки/ }));
    const menu = screen.getByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((a) => a.textContent),
    ).toEqual(["Цены", "Каталог", "Выкуп", "Журнал"]);
  });

  it("counts what waits for an operator", async () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(await within(nav).findByLabelText("ждут внимания: 3")).toBeInTheDocument();
    expect(await within(nav).findByLabelText("к выплате: 2")).toBeInTheDocument();
  });

  it("marks the current page; an order page belongs to «Обмены»", () => {
    renderLayout("/orders/123");
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(within(nav).getByRole("link", { name: /Обмены/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Дашборд" })).not.toHaveAttribute("aria-current");
  });

  it("on a phone ☰ opens every page and closes on navigation", () => {
    renderLayout();
    fireEvent.click(screen.getByRole("button", { name: "Открыть меню" }));
    const sheet = screen.getByRole("dialog", { name: "Меню" });
    expect(within(sheet).getByRole("link", { name: "Журнал" })).toHaveAttribute("href", "/audit");
    fireEvent.click(within(sheet).getByRole("link", { name: "Платежи" }));
    expect(screen.queryByRole("dialog", { name: "Меню" })).toBeNull();
  });

  it("starts with a skip link to the content", () => {
    renderLayout();
    expect(screen.getByRole("link", { name: "Перейти к содержимому" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  });
});
