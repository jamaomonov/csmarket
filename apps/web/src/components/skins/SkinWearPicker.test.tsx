// @vitest-environment jsdom
import messages from "@csmarket/i18n/locales/ru/web.json";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { SkinWearPicker } from "./SkinWearPicker";

import type { SkinFamilyMember } from "@csmarket/utils/skins";
import type { ReactNode } from "react";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const wrap = (ui: ReactNode) =>
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      {ui}
    </NextIntlClientProvider>,
  );

const m = (
  slug: string,
  exterior: SkinFamilyMember["exterior"],
  over: Partial<SkinFamilyMember> = {},
): SkinFamilyMember => ({
  slug,
  exterior,
  stattrak: false,
  souvenir: false,
  price_usd: "10.00",
  price_uzs: "127000",
  count: 3,
  ...over,
});

const at = (all: SkinFamilyMember[], i: number): SkinFamilyMember => {
  const member = all[i];
  if (!member) throw new Error(`fixture has no member ${String(i)}`);
  return member;
};

describe("SkinWearPicker", () => {
  const family = [
    m("ak-mw", "MW"),
    m("ak-ft", "FT"),
    m("ak-bs", "BS", { price_usd: null, price_uzs: null, count: 0 }),
    m("st-ak-ft", "FT", { stattrak: true }),
  ];

  it("names each wear in full, marks the current one and greys a sold-out one", () => {
    wrap(<SkinWearPicker family={family} current={at(family, 1)} locale="ru" />);
    const current = screen.getByRole("link", { name: /После полевых/ });
    expect(current).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Немного поношенное/ })).toHaveAttribute(
      "href",
      "/item/ak-mw",
    );
    expect(screen.getByRole("link", { name: /Закалённое в боях/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("switches to the StatTrak twin of the same wear", () => {
    wrap(<SkinWearPicker family={family} current={at(family, 1)} locale="ru" />);
    expect(screen.getByRole("link", { name: /StatTrak/ })).toHaveAttribute(
      "href",
      "/item/st-ak-ft",
    );
    expect(screen.queryByRole("link", { name: /Souvenir/ })).not.toBeInTheDocument();
  });

  it("marks the variant you are on as the current page, not a pressed link", () => {
    wrap(<SkinWearPicker family={family} current={at(family, 3)} locale="ru" />);
    const on = screen.getByRole("link", { name: /StatTrak/ });
    expect(on).toHaveAttribute("aria-current", "page");
    expect(on).not.toHaveAttribute("aria-pressed");
  });
});
