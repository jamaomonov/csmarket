"use client";

import {
  type ComponentType,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { cn } from "../../lib/cn";

export interface DropdownItem {
  key: string;
  label: ReactNode;
  href?: string;
  onSelect?: () => void;
  meta?: ReactNode;
  tone?: "default" | "danger" | "accent";
  current?: boolean;
}
export interface DropdownSeparator {
  key: string;
  separator: true;
}
export type DropdownEntry = DropdownItem | DropdownSeparator;

export interface DropdownLinkProps {
  href: string;
  className: string;
  role: "menuitem";
  tabIndex: number;
  onClick: () => void;
  children: ReactNode;
  "aria-current"?: "true";
}

export interface DropdownProps {
  label: ReactNode;
  triggerLabel?: string;
  triggerClassName?: string;
  items: DropdownEntry[];
  align?: "start" | "end";
  menuClassName?: string;
  loading?: boolean;
  status?: ReactNode;
  onOpenChange?: (open: boolean) => void;
  LinkComponent?: ComponentType<DropdownLinkProps>;
  /**
   * `fixed` places the menu from the trigger's box in viewport coordinates, so a menu
   * inside a scrolling row (the category chips on a phone) is not clipped; it follows the
   * trigger on scroll and resize. Default `absolute`.
   */
  strategy?: "absolute" | "fixed";
  /** The menu's height cap in px; longer lists scroll. A fixed menu also fits the viewport. */
  maxHeight?: number;
}

/** Keep a fixed menu this far from the viewport's edges. */
const EDGE = 8;
/** The menu's minimum width (`min-w-[200px]` below). */
const MENU_MIN = 200;
/** A fixed menu with less room than this below its trigger opens upwards if there is more there. */
const FLIP_BELOW = 240;

interface Place {
  top?: number;
  bottom?: number;
  left: number;
  maxHeight: number;
}

const isSeparator = (e: DropdownEntry): e is DropdownSeparator => "separator" in e;

function PlainLink({ children, ...props }: DropdownLinkProps) {
  return <a {...props}>{children}</a>;
}

const itemClass = (tone: DropdownItem["tone"], current: boolean | undefined) =>
  cn(
    "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-[14px] outline-none",
    "hover:bg-border-strong focus-visible:bg-border-strong",
    tone === "danger" ? "text-danger" : current || tone === "accent" ? "text-accent" : "text-fg",
  );

const px = (n: number) => `${String(n)}px`;

/** Inline placement: viewport coordinates for a fixed menu, and the height cap. */
function menuStyle(
  strategy: "absolute" | "fixed",
  place: Place | null,
  align: "start" | "end",
  maxHeight: number | undefined,
): CSSProperties | undefined {
  if (strategy === "fixed" && place) {
    return {
      position: "fixed",
      ...(place.top !== undefined ? { top: px(place.top) } : {}),
      ...(place.bottom !== undefined ? { bottom: px(place.bottom) } : {}),
      left: px(place.left),
      maxHeight: px(place.maxHeight),
      overflowY: "auto",
      ...(align === "end" ? { transform: "translateX(-100%)" } : {}),
    };
  }
  return maxHeight !== undefined ? { maxHeight: px(maxHeight), overflowY: "auto" } : undefined;
}

/**
 * A menu button (WAI-ARIA menu pattern): click / Enter / Space / ArrowDown open it, arrows,
 * Home and End move, Escape closes and returns focus, Tab or an outside press closes it.
 * Items are links (through `LinkComponent`, so an app can pass its router's Link) or actions.
 */
export function Dropdown({
  label,
  triggerLabel,
  triggerClassName,
  items,
  align = "start",
  menuClassName,
  loading = false,
  status,
  onOpenChange,
  LinkComponent = PlainLink,
  strategy = "absolute",
  maxHeight,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<Place | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const focusFirst = useRef(false);
  const id = useId();

  /** Viewport coordinates under the trigger (the `fixed` strategy). */
  const placeFromTrigger = useCallback(() => {
    if (!trigger.current) return;
    const box = trigger.current.getBoundingClientRect();
    const left = align === "end" ? box.right : box.left;
    // Start-aligned menus are at least MENU_MIN wide: keep that much on screen.
    const right = align === "end" ? window.innerWidth - EDGE : window.innerWidth - MENU_MIN - EDGE;
    const x = Math.max(EDGE, Math.min(left, right));
    const cap = maxHeight ?? Infinity;
    const below = window.innerHeight - box.bottom - 8 - EDGE;
    const above = box.top - 8 - EDGE;
    if (below < Math.min(cap, FLIP_BELOW) && above > below) {
      setPlace({
        bottom: window.innerHeight - box.top + 8,
        left: x,
        maxHeight: Math.min(cap, above),
      });
    } else {
      setPlace({ top: box.bottom + 8, left: x, maxHeight: Math.min(cap, below) });
    }
  }, [align, maxHeight]);

  const setOpenState = useCallback(
    (next: boolean) => {
      if (next && strategy === "fixed") placeFromTrigger();
      setOpen(next);
      onOpenChange?.(next);
    },
    [onOpenChange, strategy, placeFromTrigger],
  );

  const menuItems = (): HTMLElement[] =>
    Array.from(menu.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? []);

  // A keyboard open focuses the first item — also once lazily loaded items arrive.
  const itemCount = items.length;
  useEffect(() => {
    if (!open || !focusFirst.current) return;
    const first = menuItems()[0];
    if (first) {
      first.focus();
      focusFirst.current = false;
    }
  }, [open, loading, itemCount]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      // A DOM node from the event target: narrowing the EventTarget to a Node.
      if (!root.current?.contains(e.target as Node)) setOpenState(false);
    };
    document.addEventListener("pointerdown", onPointer);
    // The page or a row scrolled (or the window resized): keep the menu under its trigger.
    const onMove = (e: Event) => {
      // The menu's own scrolling (a long model list) is not the page moving.
      if (e.target instanceof Node && menu.current?.contains(e.target)) return;
      placeFromTrigger();
    };
    if (strategy === "fixed") {
      window.addEventListener("scroll", onMove, true);
      window.addEventListener("resize", onMove);
    }
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open, setOpenState, strategy, placeFromTrigger]);

  const close = (refocus: boolean) => {
    setOpenState(false);
    if (refocus) trigger.current?.focus();
  };

  const onTriggerKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (open) {
        close(false);
        return;
      }
      focusFirst.current = true;
      setOpenState(true);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      focusFirst.current = true;
      if (open) menuItems()[0]?.focus();
      else setOpenState(true);
    }
  };

  /** Escape and Tab work wherever focus is inside: the trigger or the menu. */
  const onRootKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "Tab") close(false);
  };

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = menuItems();
    const at = list.indexOf(document.activeElement as HTMLElement); // the focused DOM element
    const move = (i: number) => {
      e.preventDefault();
      list[(i + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(list.length - 1);
  };

  return (
    <div ref={root} className="relative" onKeyDown={onRootKey}>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={triggerLabel}
        onClick={() => {
          setOpenState(!open);
        }}
        onKeyDown={onTriggerKey}
        className={cn(
          "bg-surface text-fg inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[14px]",
          "focus-visible:ring-accent focus-visible:ring-offset-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
          triggerClassName,
        )}
      >
        {label}
      </button>
      {open && (
        <div
          ref={menu}
          id={id}
          role="menu"
          onKeyDown={onMenuKey}
          style={menuStyle(strategy, place, align, maxHeight)}
          className={cn(
            "bg-surface-2 shadow-menu z-50 min-w-[200px] rounded-lg p-1.5",
            strategy === "fixed"
              ? "max-w-[calc(100vw-16px)]"
              : cn("absolute mt-2", align === "end" ? "right-0" : "left-0"),
            menuClassName,
          )}
        >
          {status && <p className="text-fg-muted px-3 py-2 text-[13px]">{status}</p>}
          {loading ? (
            <p role="status" className="text-fg-muted px-3 py-2 text-[13px]">
              …
            </p>
          ) : (
            items.map((entry) => {
              if (isSeparator(entry)) {
                return <hr key={entry.key} className="border-border-strong my-1" />;
              }
              const body = (
                <>
                  <span className="truncate">{entry.label}</span>
                  {entry.meta !== undefined && (
                    <span className="text-fg-muted shrink-0 text-[13px]">{entry.meta}</span>
                  )}
                </>
              );
              if (entry.href !== undefined) {
                return (
                  <LinkComponent
                    key={entry.key}
                    href={entry.href}
                    role="menuitem"
                    tabIndex={-1}
                    onClick={() => {
                      close(false);
                    }}
                    className={itemClass(entry.tone, entry.current)}
                    {...(entry.current ? { "aria-current": "true" as const } : {})}
                  >
                    {body}
                  </LinkComponent>
                );
              }
              return (
                <button
                  key={entry.key}
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  onClick={() => {
                    entry.onSelect?.();
                    close(true);
                  }}
                  className={itemClass(entry.tone, entry.current)}
                >
                  {body}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
