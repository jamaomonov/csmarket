/**
 * App shell: a left sidebar of icon links in groups, a topbar and the outlet.
 *
 * - lg+: the sidebar is a fixed-width column, always visible.
 * - <lg: it slides in over the content as a drawer from the ☰ in the topbar and closes on
 *   navigation. The split is at lg: the admin's tables are wide, and a 240 px column on a
 *   tablet is not worth the room it takes.
 */
import { Button, Logo } from "@csmarket/ui";
import {
  Activity,
  ArrowLeftRight,
  CreditCard,
  Gauge,
  HandCoins,
  KeyRound,
  LogOut,
  Menu,
  Package,
  Percent,
  Receipt,
  Settings2,
  Users,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuthStore } from "@/features/auth/authStore";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}
interface NavGroup {
  /** The section heading; `null` for the pinned group at the top. */
  label: string | null;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  { label: null, items: [{ to: "/", label: "Дашборд", icon: Gauge, end: true }] },
  {
    label: "Каталог",
    items: [
      { to: "/catalogue", label: "Каталог", icon: Package },
      { to: "/pricing", label: "Цены", icon: Percent },
    ],
  },
  {
    label: "Операции",
    items: [
      { to: "/orders", label: "Заказы", icon: Receipt },
      { to: "/trades", label: "Обмены", icon: ArrowLeftRight },
      { to: "/payments", label: "Платежи", icon: CreditCard },
      { to: "/api-keys", label: "API-ключи", icon: KeyRound },
    ],
  },
  {
    label: "Выкуп",
    items: [
      { to: "/payouts", label: "Заявки на выплату", icon: Wallet },
      { to: "/sales", label: "Продажи", icon: HandCoins },
      { to: "/sale-settings", label: "Настройки выкупа", icon: Settings2 },
    ],
  },
  { label: "Поддержка", items: [{ to: "/users", label: "Пользователи", icon: Users }] },
  { label: "Аудит", items: [{ to: "/audit", label: "Журнал", icon: Activity }] },
];

const linkClass = ({ isActive }: { isActive: boolean }): string =>
  [
    "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
    isActive
      ? "bg-accent-subtle text-accent font-medium"
      : "text-fg-muted hover:bg-surface-2 hover:text-fg",
  ].join(" ");

export function Layout() {
  const me = useAuthStore((s) => s.me);
  const signOut = useAuthStore((s) => s.signOut);
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Close the drawer whenever the route changes.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Past lg the drawer is a static column: an open drawer would leave the body scroll-locked.
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 1024px)");
    const sync = () => {
      if (wide.matches) setDrawerOpen(false);
    };
    sync();
    wide.addEventListener("change", sync);
    return () => {
      wide.removeEventListener("change", sync);
    };
  }, []);

  // Keep the page from scrolling under the open drawer.
  useEffect(() => {
    document.body.style.overflow = drawerOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [drawerOpen]);

  return (
    <div className="flex min-h-screen">
      <a
        href="#main-content"
        className="focus:bg-accent focus:text-accent-fg sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:px-4 focus:py-2 focus:text-sm focus:font-medium"
      >
        Перейти к содержимому
      </a>

      <aside
        aria-label="Боковая панель"
        className={[
          "border-border bg-surface w-(--sidebar-width) fixed inset-y-0 left-0 z-40 flex h-screen flex-col border-r",
          "transition-transform duration-200 ease-out lg:sticky lg:top-0",
          drawerOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        ].join(" ")}
      >
        <div className="border-border h-(--topbar-height) flex items-center justify-between gap-2 border-b px-4">
          <div className="flex items-center gap-2">
            <Logo className="text-lg" />
            <span className="text-fg-dim text-xs font-medium uppercase tracking-wider">admin</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setDrawerOpen(false);
            }}
            className="text-fg-muted hover:bg-surface-2 rounded-md p-1 lg:hidden"
            aria-label="Закрыть меню"
          >
            <X className="size-4" />
          </button>
        </div>
        <nav aria-label="Основная навигация" className="flex-1 overflow-y-auto p-3">
          {NAV_GROUPS.map((group, idx) => (
            <div
              key={group.label ?? "pinned"}
              className={idx > 0 ? "border-border mt-3 border-t pt-3" : ""}
            >
              {group.label && (
                <p className="text-fg-dim mb-1 px-3 text-[10px] font-medium uppercase tracking-wider">
                  {group.label}
                </p>
              )}
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end ?? false} className={linkClass}>
                  <item.icon className="size-4" aria-hidden />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      {drawerOpen && (
        <button
          type="button"
          onClick={() => {
            setDrawerOpen(false);
          }}
          aria-label="Закрыть меню"
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-border bg-bg/95 h-(--topbar-height) sticky top-0 z-20 flex items-center justify-between border-b px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => {
                setDrawerOpen(true);
              }}
              className="text-fg-muted hover:bg-surface-2 rounded-md p-1.5 lg:hidden"
              aria-label="Открыть меню"
            >
              <Menu className="size-5" />
            </button>
            <span className="text-fg-muted truncate text-sm">
              {me?.display_name ?? "Администратор"}
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={signOut} aria-label="Выйти">
            <LogOut className="size-4" aria-hidden />
            <span className="hidden sm:inline">Выйти</span>
          </Button>
        </header>
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 p-4 focus-visible:outline-none md:p-6"
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
