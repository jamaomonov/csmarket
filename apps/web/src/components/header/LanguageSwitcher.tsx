"use client";

import { LOCALES } from "@csmarket/i18n";
import { Dropdown } from "@csmarket/ui";
import { Globe } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { getPathname, usePathname } from "@/i18n/navigation";

/** Links to the same page in each language (path and query kept); the profile is untouched. */
export function LanguageSwitcher({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const pathname = usePathname();
  // Read the query when the menu opens (client only): `useSearchParams` would need a
  // Suspense boundary, and a boundary around the header hydrates after the auth state
  // settles — a server/client mismatch.
  const [tail, setTail] = useState("");
  return (
    <Dropdown
      align="end"
      onOpenChange={(open) => {
        if (open) setTail(window.location.search);
      }}
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
