/**
 * App shell (admin UX audit §1): a top bar with Дашборд and the menu groups (Очередь, Деньги,
 * Люди, Аналитика, Настройки, Журнал) and red counters of what waits for an operator. Below
 * `lg` the groups move to a bottom bar — Обмены, Выплаты, Проверка and «Ещё» with every page.
 * API keys live on the user card, not here.
 */
import { Button, Logo } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { currentItem, DASHBOARD, GROUPS } from "./nav";
import { BottomBar, type Counters, MoreSheet, TopLink, TopMenu } from "./NavParts";

import { useAuthStore } from "@/features/auth/authStore";
import { getDashboard } from "@/features/dashboard/api";
import { DASHBOARD_KEY } from "@/features/dashboard/keys";

/** Counters from the dashboard (one request a minute, shared with the dashboard page). */
function useCounters(): Counters {
  const query = useQuery({
    queryKey: [...DASHBOARD_KEY, 1],
    queryFn: () => getDashboard(1),
    refetchInterval: 60_000,
  });
  return {
    attention: query.data?.attention ?? 0,
    toPay: query.data?.payouts.to_pay_count ?? 0,
    salesAttention: query.data?.payouts.sales_attention ?? 0,
    holds: query.data?.holds_open ?? 0,
    reviews: query.data?.reviews_bad_open ?? 0,
  };
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

  const current = currentItem(pathname);
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="focus:bg-accent focus:text-accent-fg sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:px-4 focus:py-2 focus:text-sm focus:font-medium"
      >
        Перейти к содержимому
      </a>
      <header className="border-border bg-bg/95 h-(--topbar-height) sticky top-0 z-20 flex items-center gap-4 border-b px-4 backdrop-blur md:px-6">
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <Logo className="text-lg" />
          <span className="text-fg-dim hidden text-xs font-medium uppercase tracking-wider sm:inline">
            admin
          </span>
        </Link>
        <nav aria-label="Основная навигация" className="hidden h-full items-stretch lg:flex">
          <TopLink item={DASHBOARD} current={current} />
          {GROUPS.map((group) =>
            group.items.length === 1 && group.items[0] !== undefined ? (
              <TopLink key={group.label} item={group.items[0]} current={current} />
            ) : (
              <TopMenu
                key={group.label}
                group={group}
                current={current}
                pathname={pathname}
                counters={counters}
              />
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
        <MoreSheet
          current={current}
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
      {/* Keeps the end of a page above the phone's bottom bar. */}
      <div aria-hidden className="h-(--bottom-nav) shrink-0" />
      <BottomBar
        current={current}
        counters={counters}
        moreOpen={sheetOpen}
        onMore={() => {
          setSheetOpen(true);
        }}
      />
    </div>
  );
}
