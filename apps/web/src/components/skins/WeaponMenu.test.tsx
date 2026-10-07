// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WeaponMenu } from "./WeaponMenu";

import type { SkinQuery, WeaponFacet } from "@csmarket/utils/skins";

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
const replace = vi.hoisted(() => vi.fn());
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ replace }),
}));

const RIFLES = [
  { value: "AK-47", count: 412, category: "rifles", image: "https://x/ak.png" },
  { value: "AWP", count: 326, category: "rifles", image: null },
];

function renderMenu(query: SkinQuery = { sort: "-price" }, initial?: WeaponFacet[]) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <WeaponMenu
        category="rifles"
        label="Винтовки"
        query={query}
        {...(initial ? { initial } : {})}
      />
    </NextIntlClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Модели: Винтовки" }));
}

const lastUrl = () => replace.mock.calls.at(-1)?.[0] as string; // the router's recorded URL

describe("WeaponMenu", () => {
  beforeEach(() => {
    fetchFacets.mockReset();
    replace.mockReset();
  });

  it("loads the models on first open: a box and a picture each, no counts", async () => {
    impl.fn = () => Promise.resolve({ weapons: RIFLES });
    renderMenu();
    const ak = await screen.findByRole("menuitemcheckbox", { name: /AK-47/ });
    expect(ak).toHaveAttribute("aria-checked", "false");
    expect(ak.querySelector("img")).not.toBeNull();
    // The picture sits on a red glow, as Covert skins are shown.
    expect(ak.querySelector("[data-model-glow]")).not.toBeNull();
    // «Выбрать все» is set apart from the models by a line.
    expect(screen.getByRole("menu").querySelector("hr")).not.toBeNull();
    expect(screen.queryByText("412")).toBeNull();
    expect(screen.getByRole("menuitemcheckbox", { name: "Выбрать все" })).toBeInTheDocument();
    expect(fetchFacets).toHaveBeenCalledWith("rifles", expect.any(AbortSignal));
  });

  it("ticks several models without closing; the URL follows", () => {
    renderMenu({ sort: "-price" }, RIFLES);
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: /AK-47/ }));
    expect(lastUrl()).toContain("category=rifles");
    expect(lastUrl()).toContain("weapon=AK-47");
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: /AWP/ }));
    // Both ticked is the whole category.
    expect(lastUrl()).toBe("/?category=rifles");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("a model of another category keeps the first and drops the category", () => {
    renderMenu({ sort: "-price", category: "pistols", weapon: "Glock-18" }, RIFLES);
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: /AWP/ }));
    expect(lastUrl()).toBe("/?weapon=AWP%2CGlock-18");
  });

  it("«Выбрать все» takes the whole category, and unticked clears it", () => {
    renderMenu({ sort: "-price" }, RIFLES);
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Выбрать все" }));
    expect(lastUrl()).toBe("/?category=rifles");
    expect(screen.getByRole("menuitemcheckbox", { name: "Выбрать все" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Выбрать все" }));
    expect(lastUrl()).toBe("/");
  });

  it("failed load still offers the category and says so", async () => {
    impl.fn = () => Promise.reject(new Error("down"));
    renderMenu();
    expect(await screen.findByText("Не удалось загрузить модели")).toBeInTheDocument();
    expect(screen.getByRole("menuitemcheckbox", { name: "Выбрать все" })).toBeInTheDocument();
  });

  it("aborts the models request when the menu goes away", () => {
    impl.fn = () => new Promise(() => undefined);
    const { unmount } = render(
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <WeaponMenu category="rifles" label="Винтовки" query={{ sort: "-price" }} />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Модели: Винтовки" }));
    const signal = fetchFacets.mock.calls[0]?.[1] as AbortSignal; // the mock's recorded argument
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
