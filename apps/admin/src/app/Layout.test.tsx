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
  getDashboard.mockResolvedValue({
    attention: 3,
    payouts: { to_pay_count: 2, sales_attention: 5 },
    holds_open: 4,
    reviews_bad_open: 6,
  });
});

describe("Layout", () => {
  it("a top bar: Дашборд, the groups and Журнал, no API keys page", () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Дашборд", "Аналитика", "Статьи", "Журнал"]);
    for (const group of ["Очередь", "Деньги", "Люди", "Настройки"]) {
      expect(within(nav).getByRole("button", { name: new RegExp(group) })).toBeInTheDocument();
    }
    expect(screen.queryByText("API-ключи")).toBeNull();
  });

  it.each([
    ["Очередь", ["Обмены", "Заявки на выплату", "На проверке"]],
    ["Деньги", ["Платежи", "P2P", "Продажи", "Сверка"]],
    ["Люди", ["Пользователи", "Запрет выкупа", "Отзывы"]],
    ["Настройки", ["Цены", "Каталог", "Настройки выкупа", "Оплата"]],
  ])("the menu «%s» opens its pages", (group, pages) => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    fireEvent.click(within(nav).getByRole("button", { name: new RegExp(group) }));
    const menu = screen.getByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((a) => a.textContent.replace(/\d+$/, "")),
    ).toEqual(pages);
  });

  it("counts what waits for an operator, as numbers", async () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    // Closed, «Очередь» shows the sum of its queues: 3 + 2 + 4.
    expect(await within(nav).findByLabelText("Очередь, ждут: 9")).toBeInTheDocument();
    expect(within(nav).getByLabelText("Деньги, ждут: 5")).toBeInTheDocument();
    expect(within(nav).getByLabelText("Люди, ждут: 6")).toBeInTheDocument();
    fireEvent.click(within(nav).getByRole("button", { name: /Очередь/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByLabelText("ждут внимания: 3")).toBeInTheDocument();
    expect(within(menu).getByLabelText("к выплате: 2")).toBeInTheDocument();
    expect(within(menu).getByLabelText("Платежи на проверке: 4")).toBeInTheDocument();
  });

  it("marks the current page; an order page belongs to «Обмены»", () => {
    renderLayout("/orders/123");
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(within(nav).getByRole("button", { name: /Очередь/ })).toHaveClass("border-accent");
    expect(within(nav).getByRole("link", { name: "Дашборд" })).not.toHaveAttribute("aria-current");
    const bar = screen.getByRole("navigation", { name: "Быстрый доступ" });
    expect(within(bar).getByRole("link", { name: /Обмены/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("«Сверка» is its own page, not «Продажи»", () => {
    renderLayout("/sales/reconciliation");
    fireEvent.click(screen.getByRole("button", { name: /Ещё/ }));
    const sheet = screen.getByRole("dialog", { name: "Меню" });
    expect(within(sheet).getByRole("link", { name: "Сверка" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(sheet).getByRole("link", { name: /Продажи/ })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("on a phone a bottom bar: the three queues with counters and «Ещё»", async () => {
    renderLayout();
    const bar = screen.getByRole("navigation", { name: "Быстрый доступ" });
    expect(
      within(bar)
        .getAllByRole("link")
        .map((a) => [a.getAttribute("href"), a.textContent.replace(/^\d+/, "")]),
    ).toEqual([
      ["/trades", "Обмены"],
      ["/payouts", "Выплаты"],
      ["/payment-holds", "Проверка"],
    ]);
    expect(await within(bar).findByLabelText("ждут внимания: 3")).toBeInTheDocument();
    expect(within(bar).getByLabelText("к выплате: 2")).toBeInTheDocument();
    expect(within(bar).getByLabelText("Платежи на проверке: 4")).toBeInTheDocument();
    // «Ещё» counts the rest: the sales waiting for a check.
    // 5 from «Деньги» plus the 6 bad reviews in «Люди»
    expect(within(bar).getByLabelText("Ещё ждут: 11")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Открыть меню" })).toBeNull();
  });

  it("«Ещё» opens every page under group headings and closes on navigation", () => {
    renderLayout();
    fireEvent.click(screen.getByRole("button", { name: /Ещё/ }));
    const sheet = screen.getByRole("dialog", { name: "Меню" });
    expect(
      within(sheet)
        .getAllByRole("heading")
        .map((h) => h.textContent),
    ).toEqual(["Очередь", "Деньги", "Люди", "Настройки"]);
    const people = within(sheet).getByRole("region", { name: "Люди" });
    expect(
      within(people)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Пользователи", "Запрет выкупа", "Отзывы"]);
    expect(within(sheet).getByRole("link", { name: "Журнал" })).toHaveAttribute("href", "/audit");
    expect(within(sheet).getByRole("link", { name: "Аналитика" })).toHaveAttribute(
      "href",
      "/analytics",
    );
    fireEvent.click(within(sheet).getByRole("link", { name: "Платежи" }));
    expect(screen.queryByRole("dialog", { name: "Меню" })).toBeNull();
  });

  it("«Ещё» closes on Esc", () => {
    renderLayout();
    fireEvent.click(screen.getByRole("button", { name: /Ещё/ }));
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Меню" }), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Меню" })).toBeNull();
  });

  it("every route of the old menu is still reachable", () => {
    renderLayout();
    fireEvent.click(screen.getByRole("button", { name: /Ещё/ }));
    const sheet = screen.getByRole("dialog", { name: "Меню" });
    const hrefs = within(sheet)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs.sort()).toEqual(
      [
        "/",
        "/analytics",
        "/articles",
        "/trades",
        "/payouts",
        "/sales",
        "/sales/reconciliation",
        "/sale-blocks",
        "/reviews",
        "/users",
        "/payments",
        "/payment-holds",
        "/p2p",
        "/pricing",
        "/catalogue",
        "/sale-settings",
        "/payment-settings",
        "/audit",
      ].sort(),
    );
  });

  it("starts with a skip link to the content", () => {
    renderLayout();
    expect(screen.getByRole("link", { name: "Перейти к содержимому" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  });
});
