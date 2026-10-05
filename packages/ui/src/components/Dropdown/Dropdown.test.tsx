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

  it("fixed strategy escapes a scrolling row and follows its trigger when the page moves", () => {
    render(<Dropdown label="m" strategy="fixed" items={[{ key: "a", label: "A", href: "#" }]} />);
    const trigger = screen.getByRole("button", { name: "m" });
    let top = 100;
    // A DOMRect stand-in: jsdom does no layout.
    trigger.getBoundingClientRect = () =>
      ({
        top,
        bottom: top + 36,
        left: 40,
        right: 120,
        width: 80,
        height: 36,
        x: 40,
        y: top,
      }) as DOMRect;
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(menu.style.position).toBe("fixed");
    expect(menu.style.top).toBe("144px");
    expect(menu.style.left).toBe("40px");
    top = 60; // the row or the page scrolled (e.g. to bring the focused trigger into view)
    fireEvent.scroll(window);
    expect(screen.getByRole("menu").style.top).toBe("104px");
  });

  it("a fixed menu near the right edge stays on screen", () => {
    window.innerWidth = 390;
    render(<Dropdown label="m" strategy="fixed" items={[{ key: "a", label: "A", href: "#" }]} />);
    const trigger = screen.getByRole("button", { name: "m" });
    // A DOMRect stand-in: jsdom does no layout.
    trigger.getBoundingClientRect = () =>
      ({
        top: 0,
        bottom: 36,
        left: 300,
        right: 360,
        width: 60,
        height: 36,
        x: 300,
        y: 0,
      }) as DOMRect;
    fireEvent.click(trigger);
    expect(screen.getByRole("menu").style.left).toBe("182px"); // 390 − 200 (min width) − 8
  });

  it("keyboard open while loading focuses the first item once it arrives", () => {
    const { rerender } = render(<Dropdown label="m" loading items={[]} />);
    const trigger = screen.getByRole("button", { name: "m" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    rerender(<Dropdown label="m" items={[{ key: "a", label: "AK-47", href: "#" }]} />);
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "AK-47" }));
  });

  it("with focus on the trigger, Escape closes and Tab closes", () => {
    const trigger = setup();
    fireEvent.click(trigger); // a mouse open leaves focus on the trigger
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "Tab" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("Enter on an open trigger closes it", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("a fixed menu fits the viewport height: capped below, flipped above near the bottom", () => {
    window.innerHeight = 800;
    let top = 100;
    render(
      <Dropdown
        label="m"
        strategy="fixed"
        maxHeight={360}
        items={[{ key: "a", label: "A", href: "#" }]}
      />,
    );
    const trigger = screen.getByRole("button", { name: "m" });
    // A DOMRect stand-in: jsdom does no layout.
    trigger.getBoundingClientRect = () =>
      ({
        top,
        bottom: top + 36,
        left: 40,
        right: 120,
        width: 80,
        height: 36,
        x: 40,
        y: top,
      }) as DOMRect;
    fireEvent.click(trigger);
    let menu = screen.getByRole("menu");
    expect(menu.style.maxHeight).toBe("360px");
    expect(menu.style.overflowY).toBe("auto");
    top = 564; // 200 px left below: open upwards
    fireEvent.scroll(window);
    menu = screen.getByRole("menu");
    expect(menu.style.top).toBe("");
    expect(menu.style.bottom).toBe("244px"); // 800 − 564 + 8
    expect(menu.style.maxHeight).toBe("360px");
    window.innerHeight = 300; // a landscape phone: little room either way, stay below
    top = 100;
    fireEvent(window, new Event("resize"));
    menu = screen.getByRole("menu");
    expect(menu.style.bottom).toBe("");
    expect(menu.style.top).toBe("144px");
    expect(menu.style.maxHeight).toBe("148px"); // 300 − 144 − 8
  });

  it("an item can carry an icon before its label", () => {
    render(
      <Dropdown
        label="m"
        items={[{ key: "p", label: "Профиль", href: "#", icon: <svg data-testid="ico" /> }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "m" }));
    const item = screen.getByRole("menuitem", { name: "Профиль" });
    expect(item.firstElementChild?.firstElementChild).toBe(screen.getByTestId("ico"));
  });
});
