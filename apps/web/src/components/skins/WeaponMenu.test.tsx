// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WeaponMenu } from "./WeaponMenu";

// A plain delegate, not the vi.fn itself: vitest's spy chains a derived promise on the
// returned one without a rejection handler, so a rejecting mock would fail the test as
// unhandled even though WeaponMenu catches it.
const fetchFacets = vi.hoisted(() => vi.fn());
const impl = vi.hoisted(() => ({
  fn: (..._args: unknown[]): Promise<unknown> => Promise.resolve({}),
}));
vi.mock("@/lib/skins", () => ({
  fetchSkinFacets: (category: string, signal: AbortSignal) => {
    fetchFacets(category, signal);
    return impl.fn(category, signal);
  },
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const query = { sort: "-price" as const };

function renderMenu() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <WeaponMenu category="rifles" label="Винтовки" query={query} />
    </NextIntlClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Модели: Винтовки" }));
}

describe("WeaponMenu", () => {
  beforeEach(() => fetchFacets.mockReset());

  it("loads the models on first open and links each", async () => {
    impl.fn = () =>
      Promise.resolve({
        weapons: [
          { value: "AK-47", count: 412 },
          { value: "AWP", count: 326 },
        ],
      });
    renderMenu();
    const ak = await screen.findByRole("menuitem", { name: /AK-47/ });
    expect(ak.getAttribute("href")).toContain("category=rifles");
    expect(ak.getAttribute("href")).toContain("weapon=AK-47");
    expect(screen.getByText("412")).toBeInTheDocument();
    const all = screen.getByRole("menuitem", { name: "Все винтовки" });
    expect(all.getAttribute("href")).not.toContain("weapon=");
    expect(fetchFacets).toHaveBeenCalledWith("rifles", expect.any(AbortSignal));
  });

  it("failed load still offers the category and says so", async () => {
    impl.fn = () => Promise.reject(new Error("down"));
    renderMenu();
    expect(await screen.findByText("Не удалось загрузить модели")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Все винтовки" })).toBeInTheDocument();
  });
});
