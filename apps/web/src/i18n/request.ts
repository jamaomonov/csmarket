import enCommon from "@csmarket/i18n/locales/en/common.json";
import enLegal from "@csmarket/i18n/locales/en/legal.json";
import enWeb from "@csmarket/i18n/locales/en/web.json";
import ruCommon from "@csmarket/i18n/locales/ru/common.json";
import ruLegal from "@csmarket/i18n/locales/ru/legal.json";
import ruWeb from "@csmarket/i18n/locales/ru/web.json";
import uzCommon from "@csmarket/i18n/locales/uz/common.json";
import uzLegal from "@csmarket/i18n/locales/uz/legal.json";
import uzWeb from "@csmarket/i18n/locales/uz/web.json";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { routing } from "./routing";

const CATALOGS = {
  // `legal` is server-only: the layout leaves it out of the client provider (`lib/legal.ts`).
  ru: { common: ruCommon, web: ruWeb, legal: ruLegal },
  uz: { common: uzCommon, web: uzWeb, legal: uzLegal },
  en: { common: enCommon, web: enWeb, legal: enLegal },
} as const;

export default getRequestConfig(
  async ({
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
    requestLocale,
  }) => {
    const requested = await requestLocale;
    const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
    return { locale, messages: CATALOGS[locale] };
  },
);
