// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import messages from "@csmarket/i18n/locales/ru/web.json";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { SkinFilters } from "./SkinFilters";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

it("marks the chosen wear with a ticked box and the rest with empty ones", () => {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinFilters
        query={{ sort: "-price", exterior: "FN" }}
        facets={{
          categories: [],
          weapons: [],
          exteriors: [{ value: "FN", count: 3 }],
          rarities: [],
        }}
      />
    </NextIntlClientProvider>,
  );
  const fn = screen.getByRole("link", { name: /Прямо с завода/ });
  expect(fn).toHaveAttribute("aria-current", "true");
  expect(fn.querySelector("[data-check='on']")).not.toBeNull();
  const mw = screen.getByRole("link", { name: /Немного поношенное/ });
  expect(mw.querySelector("[data-check='off']")).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Применить" })).not.toBeInTheDocument();
});

function renderFilters(category: string | undefined, rarities: string[], exteriors: number) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinFilters
        query={{ sort: "-price", ...(category ? { category: category as "agents" } : {}) }}
        facets={{
          categories: [],
          weapons: [],
          exteriors: exteriors ? [{ value: "FN", count: 3 }] : [],
          rarities: rarities.map((value) => ({ value, count: 1, color: null })),
        }}
      />
    </NextIntlClientProvider>,
  );
}

it("shows agents only what agents have: their rarities, no wear, no StatTrak", () => {
  renderFilters("agents", ["Master", "Superior"], 0);
  expect(screen.getByRole("link", { name: /Master/ })).toBeInTheDocument();
  expect(screen.queryByText("Качество")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /StatTrak/ })).not.toBeInTheDocument();
});

it("offers the weapon rarity scale when no category is picked", () => {
  renderFilters(undefined, ["Covert", "Master", "Extraordinary", "Mil-Spec Grade"], 5);
  expect(screen.getByRole("link", { name: /Covert/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Mil-Spec Grade/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Master/ })).not.toBeInTheDocument();
  expect(screen.getByText("Качество")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /StatTrak/ })).toBeInTheDocument();
});

it("lets agents be narrowed to one side", () => {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinFilters
        query={{ sort: "-price", category: "agents", team: "ct" }}
        facets={{
          categories: [],
          weapons: [],
          exteriors: [],
          rarities: [],
          teams: [
            { value: "t", count: 2 },
            { value: "ct", count: 1 },
          ],
        }}
      />
    </NextIntlClientProvider>,
  );
  const ct = screen.getByRole("radio", { name: /Спецназ/ });
  expect(ct).toHaveAttribute("aria-checked", "true");
  const all = screen.getByRole("radio", { name: /Все агенты/ });
  expect(all).toHaveAttribute("aria-checked", "false");
  expect(all.getAttribute("href")).not.toContain("team=");
  expect(screen.getByRole("radio", { name: /Террористы/ }).getAttribute("href")).toContain(
    "team=t",
  );
});

it("has no side filter outside agents", () => {
  renderFilters(undefined, ["Covert"], 5);
  expect(screen.queryByRole("radio", { name: /Спецназ/ })).not.toBeInTheDocument();
});

it("resets only the panel's filters, keeping the category, and hides with none set", () => {
  const { unmount } = render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinFilters
        query={{ sort: "-price", category: "rifles", exterior: "FN", stattrak: true }}
        facets={{ categories: [], weapons: [], exteriors: [], rarities: [] }}
      />
    </NextIntlClientProvider>,
  );
  const reset = screen.getByRole("link", { name: /Сбросить/ });
  expect(reset).toHaveTextContent("2");
  const href = reset.getAttribute("href") ?? "";
  expect(href).toContain("category=rifles");
  expect(href).not.toContain("exterior");
  expect(href).not.toContain("stattrak");
  unmount();
  renderFilters("rifles", [], 0);
  expect(screen.queryByRole("link", { name: /Сбросить/ })).not.toBeInTheDocument();
});

it("clears the price boxes when the URL drops the bounds (Reset, back)", () => {
  const facets = { categories: [], weapons: [], exteriors: [], rarities: [] };
  const view = (query: Parameters<typeof SkinFilters>[0]["query"]) => (
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinFilters query={query} facets={facets} />
    </NextIntlClientProvider>
  );
  const { container, rerender } = render(view({ sort: "-price", minUzs: 100000, maxUzs: 500000 }));
  const box = (name: string) => container.querySelector<HTMLInputElement>(`input[name='${name}']`);
  expect(box("min")?.value).toBe("100000");
  expect(box("max")?.value).toBe("500000");
  rerender(view({ sort: "-price" }));
  expect(box("min")?.value).toBe("");
  expect(box("max")?.value).toBe("");
});

it("keeps the box (focus, typed digits) when its own price comes back in the URL", () => {
  vi.useFakeTimers();
  try {
    const facets = { categories: [], weapons: [], exteriors: [], rarities: [] };
    const view = (query: Parameters<typeof SkinFilters>[0]["query"]) => (
      <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
        <SkinFilters query={query} facets={facets} />
      </NextIntlClientProvider>
    );
    const { container, rerender } = render(view({ sort: "-price" }));
    const box = () => container.querySelector<HTMLInputElement>("input[name='min']");
    const typedInto = box();
    if (!typedInto) throw new Error("no min box");
    typedInto.focus();
    fireEvent.change(typedInto, { target: { value: "100000" } });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    // The buyer keeps typing while the page for 100 000 loads, then it arrives.
    fireEvent.change(typedInto, { target: { value: "1000000" } });
    rerender(view({ sort: "-price", minUzs: 100000 }));
    expect(box()).toBe(typedInto);
    expect(document.activeElement).toBe(typedInto);
    expect(box()?.value).toBe("1000000");
  } finally {
    vi.useRealTimers();
  }
});
