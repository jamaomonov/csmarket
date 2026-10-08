"use client";

import { cn } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { ACCOUNT_NAV, isCurrent } from "@/components/header/nav";
import { Link, usePathname } from "@/i18n/navigation";

const item = (on: boolean) =>
  cn(
    "-mb-px flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-1 pb-3 pt-1 text-[15px] font-medium transition-colors",
    on ? "border-accent text-fg" : "text-fg-muted hover:text-fg border-transparent",
  );

/** The profile's sections as tabs along the top, a scrolling row on phones; «Выйти» is in the account menu. */
export function AccountSidebar() {
  const t = useTranslations("web.nav");
  const a = useTranslations("web.account");
  const pathname = usePathname();
  return (
    <nav
      aria-label={a("profile.nav")}
      className="border-border -mx-4 flex gap-6 overflow-x-auto border-b px-4 [scrollbar-width:none] sm:mx-0 sm:px-0"
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
    </nav>
  );
}
