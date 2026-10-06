"use client";

import { cn } from "@csmarket/ui";
import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { ACCOUNT_NAV, isCurrent } from "@/components/header/nav";
import { Link, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";

const item = (on: boolean) =>
  cn(
    "flex shrink-0 items-center gap-3 whitespace-nowrap rounded-lg px-3.5 py-2.5 text-[15px] font-medium transition-colors",
    on ? "bg-surface text-fg" : "text-fg-muted hover:bg-surface hover:text-fg",
  );

/** The profile's sections: a column on desktop, a scrolling row of tabs on phones. */
export function AccountSidebar() {
  const t = useTranslations("web.nav");
  const a = useTranslations("web.account");
  const pathname = usePathname();
  const { status, signOut } = useAuth();
  return (
    <nav
      aria-label={a("profile.nav")}
      className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 [scrollbar-width:none] lg:mx-0 lg:w-60 lg:shrink-0 lg:flex-col lg:self-start lg:overflow-visible lg:px-0"
    >
      {ACCOUNT_NAV.map((entry) => {
        // The profile is /account itself, not everything under it.
        const on = entry.href === "/account" ? pathname === "/account" : isCurrent(entry, pathname);
        return (
          <Link
            key={entry.key}
            href={entry.href}
            className={item(on)}
            aria-current={on ? "page" : undefined}
          >
            <entry.icon className={cn("size-[18px]", on && "text-accent")} aria-hidden />
            {t(entry.key)}
          </Link>
        );
      })}
      {status === "signed_in" && (
        <button
          type="button"
          onClick={() => void signOut()}
          className={cn(
            item(false),
            "lg:border-border lg:mt-3 lg:rounded-none lg:border-t lg:pt-4",
          )}
        >
          <LogOut className="size-[18px]" aria-hidden />
          {t("signOut")}
        </button>
      )}
    </nav>
  );
}
