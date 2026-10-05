"use client";

import { buttonVariants, cn, Logo } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { AccountMenu } from "./header/AccountMenu";
import { BalanceChip } from "./header/BalanceChip";
import { LanguageSwitcher } from "./header/LanguageSwitcher";
import { MobileMenu } from "./header/MobileMenu";

import { Link, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { HOME, ORDERS } from "@/lib/paths";

interface HeaderProps {
  locale: string;
}

const navClass = (on: boolean) =>
  `text-[15px] transition-colors ${on ? "text-fg" : "text-fg-dim hover:text-fg"}`;

/** Logo, nav, language and the account; on phones a balance and a ☰ menu. */
export function Header({ locale }: HeaderProps) {
  const t = useTranslations("web.nav");
  const { status } = useAuth();
  const pathname = usePathname();
  const signedIn = status === "signed_in";
  return (
    <header className="mx-auto flex h-[68px] max-w-[1320px] items-center gap-8 px-4 sm:px-6">
      <Link href={HOME} aria-label="csmarket">
        <Logo />
      </Link>
      <nav className="hidden items-center gap-6 md:flex">
        <Link href={HOME} className={navClass(pathname === HOME)}>
          {t("catalog")}
        </Link>
        <Link href={ORDERS} className={navClass(pathname.startsWith(ORDERS))}>
          {t("orders")}
        </Link>
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
            <span className="hidden md:block">
              <AccountMenu />
            </span>
          </>
        ) : (
          <SignIn locale={locale} />
        )}
        <span className="md:hidden">
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
      className={cn(buttonVariants({ size: "md" }), "hidden md:inline-flex")}
    >
      {t("signIn")}
    </a>
  );
}
