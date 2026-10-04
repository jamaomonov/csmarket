"use client";

import { LOCALES } from "@csmarket/i18n";
import { Dropdown } from "@csmarket/ui";
import { Globe } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { getPathname, usePathname } from "@/i18n/navigation";

/** Links to the same page in each language (path and query kept); the profile is untouched. */
export function LanguageSwitcher({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const tail = search ? `?${search}` : "";
  return (
    <Dropdown
      align="end"
      triggerLabel={`${t("language")}: ${locale.toUpperCase()}`}
      label={
        <>
          <Globe className="size-4" aria-hidden />
          {locale.toUpperCase()}
        </>
      }
      items={LOCALES.map((l) => ({
        key: l,
        label: t(`languages.${l}`),
        href: getPathname({ href: pathname, locale: l }) + tail,
        current: l === locale,
      }))}
    />
  );
}
