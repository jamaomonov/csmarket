"use client";

import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";

interface HeaderProps {
  locale: string;
}

export function Header({ locale }: HeaderProps) {
  const t = useTranslations("web.nav");
  const common = useTranslations("common");
  const { status, user, signInHref } = useAuth();
  return (
    <header className="border-border flex h-14 items-center justify-between border-b px-5">
      <Link href="/" className="font-mono text-sm font-bold uppercase tracking-widest">
        {common("brand")}
      </Link>
      {status === "signed_in" && user ? (
        <Link href="/account" className="flex items-center gap-2 text-sm font-semibold">
          {user.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatars; next/image would need remotePatterns per CDN host
            <img src={user.avatar_url} alt="" width={28} height={28} className="rounded-full" />
          ) : null}
          <span>{user.display_name ?? t("account")}</span>
        </Link>
      ) : status === "loading" ? (
        <span aria-hidden className="bg-surface h-8 w-32 animate-pulse rounded-md" />
      ) : (
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-4 py-2 text-sm font-semibold"
        >
          {t("signIn")}
        </a>
      )}
    </header>
  );
}
