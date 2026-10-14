// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { ChargeLines } from "./ChargeLines";
import ru from "../../../../../packages/i18n/locales/ru/web.json";

function show(props: Parameters<typeof ChargeLines>[0]) {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru }}>
      <ChargeLines {...props} />
    </NextIntlClientProvider>,
  );
}

const flat = (s: string | null | undefined) => (s ?? "").replace(/\s/g, " ");

describe("ChargeLines", () => {
  it("shows the price, the kassa's fee and the total for an order", () => {
    const { container } = show({
      locale: "ru",
      base: 100000,
      charge: { slug: "payme", fee: 1000, total: 101000 },
      kind: "order",
    });
    const text = flat(container.textContent);
    expect(text).toContain("Цена");
    expect(text).toContain("Комиссия Payme");
    expect(text).toContain("Итого");
    expect(text).toContain("101 000");
  });

  it("says what reaches the balance for a top-up", () => {
    show({
      locale: "ru",
      base: 100000,
      charge: { slug: "click", fee: 1000, total: 101000 },
      kind: "topup",
    });
    expect(screen.getByText("На баланс")).toBeInTheDocument();
    expect(screen.getByText("К оплате")).toBeInTheDocument();
  });

  it("renders nothing without a fee", () => {
    const { container } = show({ locale: "ru", base: 100000, charge: null, kind: "order" });
    expect(container).toBeEmptyDOMElement();
  });
});
