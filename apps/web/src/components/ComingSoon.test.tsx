// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { Star } from "lucide-react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { ComingSoon } from "./ComingSoon";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

it("names the section, says it is coming and leads to the market", () => {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <ComingSoon section="reviews" icon={Star} />
    </NextIntlClientProvider>,
  );
  expect(screen.getByRole("heading", { level: 1, name: "Отзывы" })).toBeInTheDocument();
  expect(screen.getByText("Скоро")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Открыть маркет" })).toHaveAttribute("href", "/");
});
