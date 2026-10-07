"use client";

import { LOCALES } from "@csmarket/i18n";
import { Dropdown, type DropdownEntry } from "@csmarket/ui";
import { Languages, LogOut, Menu } from "lucide-react";
import { useTranslations } from "next-intl";

import { AppLink } from "./AccountMenu";
import { ACCOUNT_NAV, MAIN_NAV, type NavEntry } from "./nav";
import { SteamIcon } from "../icons/SteamIcon";

import { getPathname, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";

/** Phones: one ☰ menu with the nav, the languages and the account. */
export function MobileMenu({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const { status, signInHref, signOut } = useAuth();
  const pathname = usePathname();
  const link = (entry: NavEntry) => ({
    key: entry.key,
    label: t(entry.key),
    href: entry.href,
    icon: <entry.icon className="text-fg-dim size-4 shrink-0" aria-hidden />,
  });
  const items: DropdownEntry[] = [
    ...MAIN_NAV.map(link),
    { key: "s1", separator: true },
    // A full navigation: the path is already locale-prefixed, AppLink would prefix it again.
    ...LOCALES.map((l) => ({
      key: `lang-${l}`,
      label: t(`languages.${l}`),
      icon: <Languages className="text-fg-dim size-4 shrink-0" aria-hidden />,
      onSelect: () => {
        window.location.assign(getPathname({ href: pathname, locale: l }) + window.location.search);
      },
      current: l === locale,
    })),
    { key: "s2", separator: true },
    ...(status === "signed_in"
      ? [
          ...ACCOUNT_NAV.map(link),
          {
            key: "out",
            label: t("signOut"),
            tone: "danger" as const,
            icon: <LogOut className="size-4 shrink-0" aria-hidden />,
            onSelect: () => void signOut(),
          },
        ]
      : [
          {
            key: "in",
            label: t("signIn"),
            href: signInHref(locale),
            tone: "accent" as const,
            icon: <SteamIcon className="size-4 shrink-0" aria-hidden />,
          },
        ]),
  ];
  return (
    <Dropdown
      align="end"
      triggerLabel={t("menu")}
      triggerClassName="size-10 justify-center px-0"
      menuClassName="w-[calc(100vw-2rem)] max-w-sm"
      LinkComponent={AppLink}
      label={<Menu className="size-5" aria-hidden />}
      items={items}
    />
  );
}
