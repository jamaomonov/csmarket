"use client";

import { LOCALES } from "@csmarket/i18n";
import { Dropdown, type DropdownEntry } from "@csmarket/ui";
import { Menu } from "lucide-react";
import { useTranslations } from "next-intl";

import { AppLink } from "./AccountMenu";

import { getPathname, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { ACCOUNT, BALANCE, HOME, ORDERS } from "@/lib/paths";

/** Phones: one ☰ menu with the nav, the languages and the account. */
export function MobileMenu({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const { status, signInHref, signOut } = useAuth();
  const pathname = usePathname();
  const items: DropdownEntry[] = [
    { key: "catalog", label: t("catalog"), href: HOME },
    { key: "orders", label: t("orders"), href: ORDERS },
    { key: "s1", separator: true },
    // A full navigation: the path is already locale-prefixed, AppLink would prefix it again.
    ...LOCALES.map((l) => ({
      key: `lang-${l}`,
      label: t(`languages.${l}`),
      onSelect: () => {
        window.location.assign(getPathname({ href: pathname, locale: l }) + window.location.search);
      },
      current: l === locale,
    })),
    { key: "s2", separator: true },
    ...(status === "signed_in"
      ? [
          { key: "profile", label: t("profile"), href: ACCOUNT },
          { key: "balance", label: t("balance"), href: BALANCE },
          {
            key: "out",
            label: t("signOut"),
            tone: "danger" as const,
            onSelect: () => void signOut(),
          },
        ]
      : [{ key: "in", label: t("signIn"), href: signInHref(locale), tone: "accent" as const }]),
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
