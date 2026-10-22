/**
 * The pieces of the admin's navigation (admin UX audit §1): the counter badge, a top-bar menu,
 * the phone's bottom bar and its «Ещё» sheet with every group under a heading.
 */
import { Logo } from "@csmarket/ui";
import { ArrowLeftRight, ChevronDown, LayoutGrid, ShieldAlert, Wallet, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  BOTTOM_ITEMS,
  COUNTER_LABEL,
  type Counter,
  countOf,
  DASHBOARD,
  GROUPS,
  type NavGroup,
  type NavItem,
} from "./nav";

export type Counters = Record<Counter, number>;

export function CounterBadge({ label, value }: { label: string; value: number }) {
  if (value <= 0) return null;
  return (
    <span
      aria-label={`${label}: ${String(value)}`}
      className="bg-danger text-danger-fg text-meta min-w-5 rounded-full px-1.5 text-center font-semibold tabular-nums"
    >
      {value}
    </span>
  );
}

function ItemBadge({ item, counters }: { item: NavItem; counters: Counters }) {
  if (item.counter === undefined) return null;
  return <CounterBadge label={COUNTER_LABEL[item.counter]} value={counters[item.counter]} />;
}

export const topLinkClass = (active: boolean): string =>
  [
    "flex h-full items-center gap-1.5 border-b-2 px-3 text-sm transition-colors whitespace-nowrap",
    active ? "border-accent text-fg font-medium" : "text-fg-muted hover:text-fg border-transparent",
  ].join(" ");

/** A plain link of the top bar (Дашборд, Аналитика, Журнал). */
export function TopLink({ item, current }: { item: NavItem; current: NavItem | undefined }) {
  return (
    <Link
      to={item.to}
      aria-current={current === item ? "page" : undefined}
      className={topLinkClass(current === item)}
    >
      {item.label}
    </Link>
  );
}

interface TopMenuProps {
  group: NavGroup;
  current: NavItem | undefined;
  pathname: string;
  counters: Counters;
}

/** A group of the top bar; closed, it shows the sum of its counters. */
export function TopMenu({ group, current, pathname, counters }: TopMenuProps) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const active = group.items.some((i) => i === current);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      // A click target is always a DOM node (DOM narrowing).
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("mousedown", close);
    };
  }, [open]);

  return (
    <div
      ref={box}
      className="relative h-full"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={topLinkClass(active)}
      >
        {group.label}
        <CounterBadge label={`${group.label}, ждут`} value={countOf(group.items, counters)} />
        <ChevronDown className="size-3.5" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={group.label}
          className="border-border bg-surface absolute left-0 top-full z-30 mt-1 min-w-56 rounded-lg border p-1 shadow-[var(--shadow-menu)]"
        >
          {group.items.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              role="menuitem"
              aria-current={item === current ? "page" : undefined}
              className={`flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm ${
                item === current ? "text-accent" : "hover:bg-surface-2"
              }`}
            >
              {item.label}
              <ItemBadge item={item} counters={counters} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

interface SheetLinkProps {
  item: NavItem;
  current: NavItem | undefined;
  counters: Counters;
  onPick: () => void;
}

function SheetLink({ item, current, counters, onPick }: SheetLinkProps) {
  return (
    <Link
      to={item.to}
      onClick={onPick}
      aria-current={item === current ? "page" : undefined}
      className={`text-lead flex min-h-11 items-center justify-between rounded-md px-3 ${
        item === current ? "bg-accent-subtle text-accent" : "hover:bg-surface-2"
      }`}
    >
      {item.label}
      <ItemBadge item={item} counters={counters} />
    </Link>
  );
}

interface MoreSheetProps {
  current: NavItem | undefined;
  counters: Counters;
  onClose: () => void;
}

/** «Ещё» on a phone: a bottom sheet with every page, each group under a heading and a divider. */
export function MoreSheet({ current, counters, onClose }: MoreSheetProps) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
  }, []);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Меню"
      className="fixed inset-0 z-50 lg:hidden"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <button
        type="button"
        aria-label="Закрыть меню"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <nav
        aria-label="Все разделы"
        className="border-border bg-surface absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-xl border-t p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      >
        <div className="mb-1 flex items-center justify-between px-1">
          <Logo className="text-lg" />
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="text-fg-muted hover:bg-surface-2 grid size-11 place-items-center rounded-md"
          >
            <X className="size-5" />
          </button>
        </div>
        <SheetLink item={DASHBOARD} current={current} counters={counters} onPick={onClose} />
        {GROUPS.map((group) => (
          <section
            key={group.label}
            aria-label={group.label}
            className="border-border mt-2 border-t pt-2"
          >
            {group.items.length > 1 && (
              <h2 className="text-fg-dim text-meta px-3 pb-1 font-medium uppercase tracking-wider">
                {group.label}
              </h2>
            )}
            {group.items.map((item) => (
              <SheetLink
                key={item.to}
                item={item}
                current={current}
                counters={counters}
                onPick={onClose}
              />
            ))}
          </section>
        ))}
      </nav>
    </div>
  );
}

const BOTTOM_ICONS: Record<string, ReactNode> = {
  "/trades": <ArrowLeftRight className="size-5" aria-hidden />,
  "/payouts": <Wallet className="size-5" aria-hidden />,
  "/payment-holds": <ShieldAlert className="size-5" aria-hidden />,
};

const cellClass = (active: boolean): string =>
  `relative flex flex-1 flex-col items-center justify-center gap-0.5 text-xs ${
    active ? "text-accent font-medium" : "text-fg-muted"
  }`;

interface BottomBarProps {
  current: NavItem | undefined;
  counters: Counters;
  moreOpen: boolean;
  onMore: () => void;
}

/** The phone's bottom bar: Обмены, Выплаты, Проверка with their counters, and «Ещё». */
export function BottomBar({ current, counters, moreOpen, onMore }: BottomBarProps) {
  const onBar = BOTTOM_ITEMS.some((i) => i === current);
  const rest = GROUPS.flatMap((g) => g.items).filter((i) => !BOTTOM_ITEMS.includes(i));
  return (
    <nav
      aria-label="Быстрый доступ"
      className="border-border bg-bg/95 h-(--bottom-nav) fixed inset-x-0 bottom-0 z-40 flex border-t pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      {BOTTOM_ITEMS.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          aria-current={item === current ? "page" : undefined}
          className={cellClass(item === current)}
        >
          <span className="relative">
            {BOTTOM_ICONS[item.to]}
            <span className="absolute -right-4 -top-1.5">
              <ItemBadge item={item} counters={counters} />
            </span>
          </span>
          {item.short ?? item.label}
        </Link>
      ))}
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={moreOpen}
        aria-current={!onBar && current !== undefined ? "page" : undefined}
        onClick={onMore}
        className={cellClass(!onBar && current !== undefined)}
      >
        <span className="relative">
          <LayoutGrid className="size-5" aria-hidden />
          <span className="absolute -right-4 -top-1.5">
            <CounterBadge label="Ещё ждут" value={countOf(rest, counters)} />
          </span>
        </span>
        Ещё
      </button>
    </nav>
  );
}
