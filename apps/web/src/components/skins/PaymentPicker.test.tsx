// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PaymentPicker, type PaymentPickerProps } from "./PaymentPicker";

const LABELS = {
  legend: "Способ оплаты",
  test: "Тестовая оплата",
  none: "Оплата сейчас недоступна.",
  maintenance: "Технические работы",
};

function setup(over: Partial<PaymentPickerProps> = {}) {
  const onPick = vi.fn<(method: string) => void>();
  render(
    <PaymentPicker
      providers={[
        { slug: "click", fee_pct: "0" },
        { slug: "payme", fee_pct: "1.5" },
        { slug: "mock", fee_pct: "0" },
        { slug: "odd", fee_pct: "0" },
      ]}
      method="click"
      onPick={onPick}
      labels={LABELS}
      locale="ru"
      {...over}
    />,
  );
  return onPick;
}

describe("PaymentPicker", () => {
  it("shows kassas as brands, the dev kassa as a test payment, and skips unknown ones", () => {
    setup();
    expect(screen.getByRole("group", { name: "Способ оплаты" })).toBeInTheDocument();
    for (const name of ["Click", /^Payme/, "Тестовая оплата"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /odd/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Click" })).toHaveAttribute("aria-pressed", "true");
  });

  it("puts the kassa's app icon beside its name; the test kassa has none", () => {
    setup();
    const icon = (name: string | RegExp) =>
      screen.getByRole("button", { name }).querySelector("img")?.getAttribute("src");
    expect(icon("Click")).toBe("/pay/click.png");
    expect(icon(/^Payme/)).toBe("/pay/payme.png");
    expect(icon("Тестовая оплата")).toBeUndefined();
  });

  it("shows a kassa's fee under its name, and nothing for a kassa without one", () => {
    setup();
    expect(screen.getByRole("button", { name: /Payme/ })).toHaveTextContent(/1,5\s%/);
    expect(screen.getByRole("button", { name: "Click" })).not.toHaveTextContent("%");
  });

  it("reports a tap", () => {
    const onPick = setup();
    fireEvent.click(screen.getByRole("button", { name: /^Payme/ }));
    expect(onPick).toHaveBeenCalledWith("payme");
  });

  it("says payment is unavailable when no kassa is open", () => {
    setup({ providers: [] });
    expect(screen.getByText("Оплата сейчас недоступна.")).toBeInTheDocument();
  });

  it("pulses while the kassas load", () => {
    setup({ providers: undefined });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("a balance that covers is a tile to pick", () => {
    const onPick = setup({
      method: "wallet",
      wallet: { label: "Баланс", detail: "500 000 сум", covers: true },
    });
    const tile = screen.getByRole("button", { name: /Баланс/ });
    expect(tile).toHaveAttribute("aria-pressed", "true");
    expect(tile).toHaveTextContent("500 000 сум");
    fireEvent.click(tile);
    expect(onPick).toHaveBeenCalledWith("wallet");
  });

  it("a short balance is disabled and shows its action", () => {
    setup({
      providers: [],
      wallet: {
        label: "Баланс",
        detail: "Не хватает 1 000 сум",
        covers: false,
        action: <a href="#top-up">Пополнить</a>,
      },
    });
    expect(screen.getByRole("button", { name: /Баланс/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Пополнить" })).toBeInTheDocument();
    expect(screen.getByText("Оплата сейчас недоступна.")).toBeInTheDocument();
  });

  it("greys a kassa under maintenance, says so, and never picks it", () => {
    const onPick = setup({
      providers: [
        { slug: "click", fee_pct: "0", status: "maintenance" },
        { slug: "payme", fee_pct: "0" },
      ],
      method: "payme",
    });
    const click = screen.getByRole("button", { name: /Click/ });
    expect(click).toBeDisabled();
    expect(click).toHaveTextContent("Технические работы");
    fireEvent.click(click);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("offers a top-up-only kassa on the deposit page only", () => {
    const providers = [
      { slug: "click", fee_pct: "0" },
      { slug: "mock", fee_pct: "0", topup_only: true },
    ];
    setup({ providers });
    expect(screen.queryByRole("button", { name: "Тестовая оплата" })).not.toBeInTheDocument();
  });
});
