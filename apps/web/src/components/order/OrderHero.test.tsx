// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { OrderHero, splitName } from "./OrderHero";

import { orderOut } from "@/test/orders";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function hero(over: Parameters<typeof orderOut>[1]) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <OrderHero order={orderOut("A", over)} locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("splitName", () => {
  it("splits the weapon from the skin and drops the wear", () => {
    expect(splitName("MAC-10 | Bronzer (Battle-Scarred)")).toEqual({
      weapon: "MAC-10",
      skin: "Bronzer",
    });
    expect(splitName("Sealed Genesis Terminal")).toEqual({
      weapon: null,
      skin: "Sealed Genesis Terminal",
    });
  });
});

describe("OrderHero", () => {
  it("shows the float under the skin and the pattern as a chip", () => {
    hero({ float_value: "0.6214", paint_seed: 412, exterior: "BS" });
    expect(screen.getByTestId("order-float")).toHaveTextContent("Float0.6214");
    expect(screen.getByText("412")).toBeInTheDocument();
    expect(screen.getByText("Закалённое в боях")).toBeInTheDocument();
  });

  it("shows an API order's price in dollars, not 0 soʻm", () => {
    hero({ channel: "api", price_uzs: "0", price_usd: "12.345000" });
    expect(screen.getByText("$12.345")).toBeInTheDocument();
    expect(screen.queryByText(/сум/)).toBeNull();
  });

  it("an older order without a float shows no bar", () => {
    hero({ float_value: null, paint_seed: null });
    expect(screen.queryByTestId("order-float")).toBeNull();
    expect(screen.queryByText("Паттерн")).toBeNull();
  });
});
