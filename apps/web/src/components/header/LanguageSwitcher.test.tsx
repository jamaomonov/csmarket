// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "./LanguageSwitcher";

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/category/rifles",
  getPathname: ({ href, locale }: { href: string; locale: string }) =>
    locale === "ru" ? href : `/${locale}${href}`,
}));

describe("LanguageSwitcher", () => {
  it("keeps path and query; ru has no prefix", () => {
    window.history.pushState({}, "", "/uz/category/rifles?sort=price&weapon=AK-47");
    render(
      <NextIntlClientProvider locale="uz" messages={{ web: ru, common }}>
        <LanguageSwitcher locale="uz" />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /UZ/ }));
    expect(screen.getByRole("menuitem", { name: "Русский" })).toHaveAttribute(
      "href",
      "/category/rifles?sort=price&weapon=AK-47",
    );
    expect(screen.getByRole("menuitem", { name: "English" })).toHaveAttribute(
      "href",
      "/en/category/rifles?sort=price&weapon=AK-47",
    );
    expect(screen.getByRole("menuitem", { name: "Oʻzbekcha" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
});
