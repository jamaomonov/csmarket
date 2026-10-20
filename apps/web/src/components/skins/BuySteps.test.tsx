// @vitest-environment jsdom
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { BuySteps, type BuyStage } from "./BuySteps";

const states = (stage: BuyStage): (string | null)[] => {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru }}>
      <BuySteps stage={stage} />
    </NextIntlClientProvider>,
  );
  return screen.getAllByRole("listitem").map((li) => li.getAttribute("data-state"));
};

describe("BuySteps", () => {
  it("lights sign-in for a guest", () => {
    expect(states(1)).toEqual(["now", "todo", "todo", "todo"]);
  });

  it("lights the trade link once signed in, payment once the link works", () => {
    expect(states(3)).toEqual(["done", "done", "now", "todo"]);
  });

  it("ends with accepting the trade in Steam", () => {
    states(2);
    expect(screen.getByText("Принять обмен")).toBeInTheDocument();
  });
});
