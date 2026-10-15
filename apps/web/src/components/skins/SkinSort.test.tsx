// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import messages from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { SkinSort } from "./SkinSort";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function renderSort(sort: "-price" | "popular") {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinSort query={{ sort, category: "knives" }} />
    </NextIntlClientProvider>,
  );
}

describe("SkinSort", () => {
  it("shows the current order and opens a menu of links that keep the filters", () => {
    renderSort("popular");
    const trigger = screen.getByRole("button", { name: "Сортировка: Популярные" });
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.click(trigger);
    const items = screen.getAllByRole("menuitem");
    expect(items.map((a) => a.textContent)).toEqual([
      "Сначала дороже",
      "Сначала дешевле",
      "Популярные",
      "Выгоднее Steam",
    ]);
    expect(items[2]).toHaveAttribute("aria-current", "true");
    expect(items[1]?.getAttribute("href")).toContain("sort=price");
    expect(items[1]?.getAttribute("href")).toContain("category=knives");
  });
});
