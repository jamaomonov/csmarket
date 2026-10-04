// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { OtherCategoriesMenu } from "./OtherCategoriesMenu";

import type { SkinCategory } from "@csmarket/utils/skins";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const categories: SkinCategory[] = ["agents", "cases", "keys"];

function renderMenu(active?: SkinCategory) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <OtherCategoriesMenu
        categories={categories}
        query={{ sort: "-price", ...(active ? { category: active } : {}) }}
        {...(active ? { active } : {})}
      />
    </NextIntlClientProvider>,
  );
}

describe("OtherCategoriesMenu", () => {
  it("is a flat «Другое» chip that lists the other categories as links", () => {
    renderMenu();
    const trigger = screen.getByRole("button", { name: /Другое/ });
    expect(trigger.className.split(" ")).toContain("bg-transparent");
    fireEvent.click(trigger);
    const cases = screen.getByRole("menuitem", { name: /Кейсы/ });
    expect(cases.getAttribute("href")).toContain("category=cases");
    expect(screen.getAllByRole("menuitem").map((a) => a.textContent)).toEqual([
      "Агенты",
      "Кейсы",
      "Ключи",
    ]);
  });

  it("names and highlights the chosen one", () => {
    renderMenu("cases");
    const trigger = screen.getByRole("button", { name: /Кейсы/ });
    expect(trigger.className.split(" ")).toContain("bg-accent");
    fireEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: /Кейсы/ })).toHaveAttribute("aria-current", "true");
  });
});
