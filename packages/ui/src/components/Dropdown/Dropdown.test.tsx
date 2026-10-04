import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dropdown, type DropdownEntry } from "./Dropdown";

const items: DropdownEntry[] = [
  { key: "p", label: "Профиль", href: "/account" },
  { key: "o", label: "Мои заказы", href: "/account/orders", meta: "3" },
  { key: "s", separator: true },
  { key: "x", label: "Выйти", tone: "danger", onSelect: vi.fn() },
];

/** The i-th menu item; throws when the menu has fewer. */
function item(i: number): HTMLElement {
  const el = screen.getAllByRole("menuitem")[i];
  if (!el) throw new Error(`no menu item ${String(i)}`);
  return el;
}

function setup(extra: Partial<Parameters<typeof Dropdown>[0]> = {}) {
  render(
    <>
      <Dropdown label="Jam" items={items} {...extra} />
      <button type="button">outside</button>
    </>,
  );
  return screen.getByRole("button", { name: "Jam" });
}

describe("Dropdown", () => {
  it("opens on click and reports it", () => {
    const trigger = setup();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")).toHaveLength(3);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("keyboard: ArrowDown opens on the first item, arrows move, End/Home jump", () => {
    const trigger = setup();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(document.activeElement).toBe(item(0));
    fireEvent.keyDown(item(0), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item(1));
    fireEvent.keyDown(item(1), { key: "End" });
    expect(document.activeElement).toBe(item(2));
    fireEvent.keyDown(item(2), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item(0));
    fireEvent.keyDown(item(0), { key: "ArrowUp" });
    expect(document.activeElement).toBe(item(2));
  });

  it("escape closes and returns focus to the trigger", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(item(0), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("tab closes the menu", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(item(0), { key: "Tab" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("an outside pointer press closes it", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("selecting an action runs it and closes", () => {
    const onSelect = vi.fn();
    render(<Dropdown label="m" items={[{ key: "a", label: "Act", onSelect }]} />);
    fireEvent.click(screen.getByRole("button", { name: "m" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Act" }));
    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("tells the owner when it opens (lazy loading) and shows loading / status rows", () => {
    const onOpenChange = vi.fn();
    render(
      <Dropdown
        label="m"
        items={[]}
        loading
        status="Не удалось загрузить"
        onOpenChange={onOpenChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "m" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Не удалось загрузить")).toBeInTheDocument();
  });

  it("renders links through the given LinkComponent and marks the current item", () => {
    render(
      <Dropdown
        label="lang"
        items={[{ key: "ru", label: "Русский", href: "/", current: true }]}
        LinkComponent={({ children, ...p }) => (
          <a data-custom {...p}>
            {children}
          </a>
        )}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "lang" }));
    const link = screen.getByRole("menuitem", { name: "Русский" });
    expect(link).toHaveAttribute("data-custom");
    expect(link).toHaveAttribute("aria-current", "true");
  });
});
