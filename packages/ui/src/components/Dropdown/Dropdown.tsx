"use client";

import {
  type ComponentType,
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
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const focusFirst = useRef(false);
  const id = useId();

  const setOpenState = useCallback(
    (next: boolean) => {
      setOpen(next);
      onOpenChange?.(next);
    },
    [onOpenChange],
  );

  const menuItems = (): HTMLElement[] =>
    Array.from(menu.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? []);

  useEffect(() => {
    if (!open) return;
    if (focusFirst.current) {
      menuItems()[0]?.focus();
      focusFirst.current = false;
    }
    const onPointer = (e: PointerEvent) => {
      // A DOM node from the event target: narrowing the EventTarget to a Node.
      if (!root.current?.contains(e.target as Node)) setOpenState(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, setOpenState]);

  const close = (refocus: boolean) => {
    setOpenState(false);
    if (refocus) trigger.current?.focus();
  };

  const onTriggerKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      focusFirst.current = true;
      setOpenState(true);
    }
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
    else if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "Tab") close(false);
  };

  return (
    <div ref={root} className="relative">
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
          className={cn(
            "bg-surface-2 shadow-menu absolute z-50 mt-2 min-w-[200px] rounded-lg p-1.5",
            align === "end" ? "right-0" : "left-0",
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
