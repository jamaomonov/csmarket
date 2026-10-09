/**
 * App shell: a top bar (admin UX review §2) — direct links, two menus (Выкуп, Настройки) and
 * red counters of what waits for an operator; on phones ☰ opens a sheet with every page.
 * API keys live on the user card, not here.
 */
import { Button, Logo } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuthStore } from "@/features/auth/authStore";
import { getDashboard } from "@/features/dashboard/api";
import { DASHBOARD_KEY } from "@/features/dashboard/keys";

type Counter = "attention" | "toPay";

interface NavLinkItem {
  to: string;
  label: string;
  end?: boolean;
  /** Other path prefixes the item stands for (an order page belongs to «Обмены»). */
  also?: string[];
  counter?: Counter;
}
interface NavMenu {
  label: string;
  items: NavLinkItem[];
}
type NavEntry = NavLinkItem | NavMenu;

const NAV: NavEntry[] = [
  { to: "/", label: "Дашборд", end: true },
  { to: "/trades", label: "Обмены", also: ["/orders/"], counter: "attention" },
  {
    label: "Выкуп",
    items: [
      { to: "/payouts", label: "Заявки на выплату", counter: "toPay" },
      { to: "/sales", label: "Продажи" },
    ],
  },
  { to: "/users", label: "Пользователи", also: ["/api-keys"] },
  { to: "/payments", label: "Платежи" },
  {
    label: "Настройки",
    items: [
      { to: "/pricing", label: "Цены" },
      { to: "/catalogue", label: "Каталог" },
      { to: "/sale-settings", label: "Выкуп" },
      { to: "/audit", label: "Журнал" },
    ],
  },
];

const COUNTER_LABEL: Record<Counter, string> = {
  attention: "ждут внимания",
  toPay: "к выплате",
};

const isMenu = (e: NavEntry): e is NavMenu => "items" in e;

function isCurrent(item: NavLinkItem, pathname: string): boolean {
  if ((item.also ?? []).some((p) => pathname.startsWith(p))) return true;
  return item.end === true ? pathname === item.to : pathname.startsWith(item.to);
}

/** Counters from the dashboard (one request a minute, shared with the dashboard page). */
function useCounters(): Record<Counter, number> {
  const query = useQuery({
    queryKey: [...DASHBOARD_KEY, 1],
    queryFn: () => getDashboard(1),
    refetchInterval: 60_000,
  });
  return {
    attention: query.data?.attention ?? 0,
    toPay: query.data?.payouts.to_pay_count ?? 0,
  };
}

function CounterBadge({ kind, value }: { kind: Counter; value: number }) {
  if (value <= 0) return null;
  return (
    <span
      aria-label={`${COUNTER_LABEL[kind]}: ${String(value)}`}
      className="bg-danger text-danger-fg rounded-full px-1.5 text-[11px] font-semibold tabular-nums"
    >
      {value}
    </span>
  );
}

const topLinkClass = (active: boolean): string =>
  [
    "flex h-full items-center gap-1.5 border-b-2 px-3 text-sm transition-colors",
    active ? "border-accent text-fg font-medium" : "text-fg-muted hover:text-fg border-transparent",
  ].join(" ");

function TopMenu({
  menu,
  pathname,
  counters,
}: {
  menu: NavMenu;
  pathname: string;
  counters: Record<Counter, number>;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const active = menu.items.some((i) => isCurrent(i, pathname));
  const counted = menu.items.find((i) => i.counter !== undefined)?.counter;

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
        {menu.label}
        {counted !== undefined && <CounterBadge kind={counted} value={counters[counted]} />}
        <ChevronDown className="size-3.5" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={menu.label}
          className="border-border bg-surface absolute left-0 top-full z-30 mt-1 min-w-52 rounded-lg border p-1 shadow-[var(--shadow-menu)]"
        >
          {menu.items.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              role="menuitem"
              aria-current={isCurrent(item, pathname) ? "page" : undefined}
              className={`flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm ${
                isCurrent(item, pathname) ? "text-accent" : "hover:bg-surface-2"
              }`}
            >
              {item.label}
              {item.counter && <CounterBadge kind={item.counter} value={counters[item.counter]} />}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function MobileSheet({
  pathname,
  counters,
  onClose,
}: {
  pathname: string;
  counters: Record<Counter, number>;
  onClose: () => void;
}) {
  const link = (item: NavLinkItem) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end ?? false}
      aria-current={isCurrent(item, pathname) ? "page" : undefined}
      className={`flex items-center justify-between rounded-md px-3 py-2.5 text-[15px] ${
        isCurrent(item, pathname) ? "bg-accent-subtle text-accent" : "hover:bg-surface-2"
      }`}
    >
      {item.label}
      {item.counter && <CounterBadge kind={item.counter} value={counters[item.counter]} />}
    </NavLink>
  );
  return (
    <div role="dialog" aria-modal="true" aria-label="Меню" className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        aria-label="Закрыть меню"
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <nav className="border-border bg-surface absolute inset-y-0 left-0 w-72 max-w-[85vw] overflow-y-auto border-r p-3">
        <div className="mb-3 flex items-center justify-between px-1">
          <Logo className="text-lg" />
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="text-fg-muted hover:bg-surface-2 rounded-md p-1"
          >
            <X className="size-4" />
          </button>
        </div>
        {NAV.map((entry) =>
          isMenu(entry) ? (
            <div key={entry.label} className="border-border mt-2 border-t pt-2">
              <p className="text-fg-dim px-3 pb-1 text-[11px] font-medium uppercase tracking-wider">
                {entry.label}
              </p>
              {entry.items.map(link)}
            </div>
          ) : (
            link(entry)
          ),
        )}
      </nav>
    </div>
  );
}

export function Layout() {
  const me = useAuthStore((s) => s.me);
  const signOut = useAuthStore((s) => s.signOut);
  const { pathname } = useLocation();
  const counters = useCounters();
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    setSheetOpen(false);
  }, [pathname]);
  useEffect(() => {
    document.body.style.overflow = sheetOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [sheetOpen]);

  const waiting = counters.attention + counters.toPay;
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="focus:bg-accent focus:text-accent-fg sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:px-4 focus:py-2 focus:text-sm focus:font-medium"
      >
        Перейти к содержимому
      </a>
      <header className="border-border bg-bg/95 h-(--topbar-height) sticky top-0 z-20 flex items-center gap-4 border-b px-4 backdrop-blur md:px-6">
        <button
          type="button"
          onClick={() => {
            setSheetOpen(true);
          }}
          className="text-fg-muted hover:bg-surface-2 relative rounded-md p-1.5 lg:hidden"
          aria-label="Открыть меню"
        >
          <Menu className="size-5" />
          {waiting > 0 && (
            <span aria-hidden className="bg-danger absolute right-1 top-1 size-2 rounded-full" />
          )}
        </button>
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <Logo className="text-lg" />
          <span className="text-fg-dim hidden text-xs font-medium uppercase tracking-wider sm:inline">
            admin
          </span>
        </Link>
        <nav aria-label="Основная навигация" className="hidden h-full items-stretch lg:flex">
          {NAV.map((entry) =>
            isMenu(entry) ? (
              <TopMenu key={entry.label} menu={entry} pathname={pathname} counters={counters} />
            ) : (
              <Link
                key={entry.to}
                to={entry.to}
                aria-current={isCurrent(entry, pathname) ? "page" : undefined}
                className={topLinkClass(isCurrent(entry, pathname))}
              >
                {entry.label}
                {entry.counter && (
                  <CounterBadge kind={entry.counter} value={counters[entry.counter]} />
                )}
              </Link>
            ),
          )}
        </nav>
        <div className="ml-auto flex min-w-0 items-center gap-2">
          <span className="text-fg-muted hidden truncate text-sm md:inline">
            {me?.display_name ?? "Администратор"}
          </span>
          <Button variant="ghost" size="sm" onClick={signOut} aria-label="Выйти">
            <LogOut className="size-4" aria-hidden />
            <span className="hidden sm:inline">Выйти</span>
          </Button>
        </div>
      </header>
      {sheetOpen && (
        <MobileSheet
          pathname={pathname}
          counters={counters}
          onClose={() => {
            setSheetOpen(false);
          }}
        />
      )}
      <main
        id="main-content"
        tabIndex={-1}
        className="mx-auto w-full max-w-[1600px] flex-1 p-4 focus-visible:outline-none md:p-6"
      >
        <Outlet />
      </main>
    </div>
  );
}
