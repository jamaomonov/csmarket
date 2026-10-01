import { DEFAULT_LOCALE, LOCALES } from "@csmarket/i18n";
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: "as-needed",
  // A URL means one language, for everybody: hreflang does the matching, the
  // switcher is a set of links, and Cloudflare caches pages that set no cookie.
  localeDetection: false,
  localeCookie: false,
});

export type AppLocale = (typeof routing.locales)[number];
