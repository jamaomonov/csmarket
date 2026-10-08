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
  `flex items-center gap-2 whitespace-nowrap text-[15px] transition-colors ${on ? "text-fg" : "text-fg-dim hover:text-fg"}`;

/** Logo, nav, language and the account; on phones a balance and a ☰ menu. */
export function Header({ locale }: HeaderProps) {
  const t = useTranslations("web.nav");
  const { status, user } = useAuth();
  const pathname = usePathname();
  const signedIn = status === "signed_in";
  return (
    <header className="mx-auto flex h-[68px] max-w-[1320px] items-center gap-8 px-4 sm:px-6">
      <Link href={HOME} aria-label="csmarket">
        <Logo />
      </Link>
      <nav className="hidden items-center gap-6 xl:flex">
        {MAIN_NAV.map((entry) => {
          const on = isCurrent(entry, pathname);
          return (
            <Link
              key={entry.key}
              href={entry.href}
              className={navClass(on)}
              aria-current={on ? "page" : undefined}
            >
              <entry.icon className={`size-4 ${on ? "text-accent" : ""}`} aria-hidden />
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
