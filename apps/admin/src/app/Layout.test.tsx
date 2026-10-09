import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Layout } from "./Layout";

vi.mock("@/features/auth/authStore", () => ({
  useAuthStore: (pick: (s: { me: null; signOut: () => void }) => unknown) =>
    pick({ me: null, signOut: () => undefined }),
}));

// jsdom has no matchMedia: a narrow screen that never changes.
window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList; // only the members Layout uses

function renderLayout(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Layout />
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  it("a left sidebar lists every page with an icon, grouped", () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual([
      "Дашборд",
      "Каталог",
      "Цены",
      "Обмены",
      "Платежи",
      "API-ключи",
      "Заявки на выплату",
      "Продажи",
      "Настройки выкупа",
      "Пользователи",
      "Журнал",
    ]);
    for (const a of links) expect(a.querySelector("svg")).not.toBeNull();
    expect(within(nav).getByText("Операции")).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Цены" })).toHaveAttribute("href", "/pricing");
  });

  it("marks the current page; an order page belongs to «Обмены»", () => {
    renderLayout("/orders/123");
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(within(nav).getByRole("link", { name: "Обмены" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Дашборд" })).not.toHaveAttribute("aria-current");
  });

  it("on narrow screens the sidebar is a drawer behind ☰ that closes on navigation", () => {
    renderLayout();
    const aside = screen.getByRole("complementary", { name: "Боковая панель" });
    expect(aside.className).toContain("-translate-x-full");
    fireEvent.click(screen.getByRole("button", { name: "Открыть меню" }));
    expect(aside.className.split(" ")).toContain("translate-x-0");
    fireEvent.click(within(aside).getByRole("link", { name: "Платежи" }));
    expect(aside.className).toContain("-translate-x-full");
  });

  it("starts with a skip link to the content", () => {
    renderLayout();
    expect(screen.getByRole("link", { name: "Перейти к содержимому" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  });
});
