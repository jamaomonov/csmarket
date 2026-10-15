"use client";

import { buttonVariants, cn, Logo } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { UserAvatar } from "./account/UserAvatar";
import { AccountMenu } from "./header/AccountMenu";
import { BalanceChip } from "./header/BalanceChip";
import { LanguageSwitcher } from "./header/LanguageSwitcher";
import { MobileMenu } from "./header/MobileMenu";
import { isCurrent, MAIN_NAV } from "./header/nav";
import { SteamIcon } from "./icons/SteamIcon";

import { Link, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { HOME } from "@/lib/paths";

interface HeaderProps {
  locale: string;
}

const navClass = (on: boolean) =>
  `relative flex h-full items-center whitespace-nowrap text-body font-medium transition-colors ${on ? "text-fg after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:rounded-full after:bg-accent" : "text-fg-muted hover:text-fg"}`;

/** Logo, nav, language and the account; on phones a balance and a ☰ menu. */
export function Header({ locale }: HeaderProps) {
  const t = useTranslations("web.nav");
  const { status, user } = useAuth();
  const pathname = usePathname();
  const signedIn = status === "signed_in";
  return (
    <div className="border-border bg-bg/85 sticky top-0 z-40 border-b backdrop-blur-md">
      <header className="mx-auto flex h-16 max-w-[1320px] items-center gap-10 px-4 sm:px-6">
        <Link href={HOME} aria-label="csmarket" className="shrink-0">
          <Logo className="text-[22px]" />
        </Link>
        <nav className="hidden h-full items-center gap-7 xl:flex">
          {MAIN_NAV.map((entry) => {
            const on = isCurrent(entry, pathname);
            return (
              <Link
                key={entry.key}
                href={entry.href}
                className={navClass(on)}
                aria-current={on ? "page" : undefined}
              >
                {t(entry.key)}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2.5">
          <div className="hidden md:block">
            <LanguageSwitcher locale={locale} />
          </div>
          {status === "loading" ? (
            <span
              aria-hidden
              className="bg-surface hidden h-10 w-40 animate-pulse rounded-lg md:block"
            />
          ) : signedIn ? (
            <>
              <span className="hidden md:block">
                <BalanceChip />
              </span>
              <span className="md:hidden">
                <BalanceChip compact />
              </span>
              {/* Phones: the avatar is the menu — no separate ☰. */}
              {user && (
                <span className="md:hidden">
                  <MobileMenu locale={locale} avatar={<UserAvatar user={user} size={40} />} />
                </span>
              )}
              <span className="hidden md:block">
                <AccountMenu />
              </span>
            </>
          ) : (
            <SignIn locale={locale} />
          )}
          <span className={signedIn && user ? "hidden md:block xl:hidden" : "xl:hidden"}>
            <MobileMenu locale={locale} />
          </span>
        </div>
      </header>
    </div>
  );
}

function SignIn({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const { signInHref } = useAuth();
  return (
    <a
      href={signInHref(locale)}
      className={cn(buttonVariants({ size: "md" }), "hidden gap-2 md:inline-flex")}
    >
      <SteamIcon className="size-[18px]" aria-hidden />
      {t("signIn")}
    </a>
  );
}
