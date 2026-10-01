// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import messages from "@csmarket/i18n/locales/ru/web.json";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SkinPriceFilter } from "./SkinPriceFilter";

const { replaceMock } = vi.hoisted(() => ({ replaceMock: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({ useRouter: () => ({ replace: replaceMock }) }));

function filter() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinPriceFilter query={{ sort: "-price", category: "rifles", minUzs: 1000 }} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  replaceMock.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

it("applies a typed price once typing pauses, with no button to press", () => {
  filter();
  expect(screen.queryByRole("button", { name: "Применить" })).not.toBeInTheDocument();
  const to = screen.getByPlaceholderText("До");
  fireEvent.change(to, { target: { value: "5" } });
  fireEvent.change(to, { target: { value: "50000" } });
  act(() => {
    vi.advanceTimersByTime(499);
  });
  expect(replaceMock).not.toHaveBeenCalled();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(replaceMock).toHaveBeenCalledTimes(1);
  const url = (replaceMock.mock.calls[0] as [string])[0];
  expect(url).toContain("max=50000");
  expect(url).toContain("min=1000");
  expect(url).toContain("category=rifles");
});

it("drops a bound that was cleared", () => {
  filter();
  fireEvent.change(screen.getByPlaceholderText("От"), { target: { value: "" } });
  act(() => {
    vi.advanceTimersByTime(500);
  });
  expect((replaceMock.mock.calls[0] as [string])[0]).not.toContain("min=");
});

it("keeps every active filter, team included, in the no-JS GET form", () => {
  const { container } = render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinPriceFilter
        query={{
          sort: "price",
          category: "agents",
          team: "ct",
          rarity: "Master",
          q: "dragon",
          stattrak: true,
        }}
      />
    </NextIntlClientProvider>,
  );
  const hidden = Object.fromEntries(
    [...container.querySelectorAll<HTMLInputElement>("form input[type=hidden]")].map((i) => [
      i.name,
      i.value,
    ]),
  );
  expect(hidden).toEqual({
    category: "agents",
    team: "ct",
    rarity: "Master",
    stattrak: "1",
    q: "dragon",
    sort: "price",
  });
  // No `action`: the form submits to the page it sits on, whatever the locale prefix.
  expect(container.querySelector("form")?.getAttribute("action")).toBeNull();
});
