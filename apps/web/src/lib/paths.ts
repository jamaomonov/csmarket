/** Locale-less paths for next-intl's `Link` / `redirect`; the locale prefix is added there. */

/** The SEO landing (the logo, «На главную»). */
export const HOME = "/";

/** The catalogue: filters, search, the grid. */
export const MARKET = "/market";

export function itemPath(slug: string): string {
  return `/item/${slug}`;
}

export function categoryPath(category: string): string {
  return `/category/${category}`;
}

/** The payment methods with a landing of their own (`/pay/click` …). */
export const PAY_METHODS = ["click", "payme", "uzum"] as const;
export type PayMethod = (typeof PAY_METHODS)[number];

/** Brand names, never translated. */
export const PAY_NAMES: Readonly<Record<PayMethod, string>> = {
  click: "Click",
  payme: "Payme",
  uzum: "Uzum",
};

export function payPath(method: PayMethod): string {
  return `/pay/${method}`;
}

/** Cheap skins, under `CHEAP_MAX_UZS` (`lib/landing.ts`). */
export const CHEAP = "/cheap";

/** A colour's landing (`/color/red`), spec 2026-10-14-skin-colors. */
export function colorPath(color: string): string {
  return `/color/${color}`;
}

/** `weaponSlug` is the slugged weapon name (`ak-47`), see `skin-landing.ts`. */
export function weaponPath(weaponSlug: string): string {
  return `/weapon/${weaponSlug}`;
}

/** A sale's page; the number is escaped (it is a path segment). */
export function salePath(number: string): string {
  return `/account/sales/${encodeURIComponent(number)}`;
}

/** An order's page; the number is escaped (it is a path segment). */
export function orderPath(number: string): string {
  return `/orders/${encodeURIComponent(number)}`;
}

/** The account page («В профиль»). */
export const ACCOUNT = "/account";

/** «Обмены»: purchases (and later sales); `?type=purchases|sales` filters. */
export const TRADES = "/account/trades";

/** «Транзакции»: the balance, top-up and its history; `?type=topup|withdrawal` filters. */
export const TRANSACTIONS = "/account/transactions";

/** «Продать скины». */
export const SELL = "/sell";

/** Sections that are on their way («Скоро» pages for now). */
export const STEAM_TOPUP = "/steam";
export const REVIEWS = "/reviews";
export const REFERRAL = "/account/referral";

/** «Пополнение баланса»: the wallet with the kassas (top-up; withdrawals later). */
export const DEPOSIT = "/deposit";

/** «Документы»: the index of the legal documents (`lib/legal.ts`). */
export const LEGAL = "/legal";

/** One legal document (`/legal/terms` …); the slugs are `LEGAL_DOCS`. */
export function legalPath(doc: string): string {
  return `${LEGAL}/${doc}`;
}

/** Articles: the list, a section list, one article (spec 2026-10-26-articles). */
export const ARTICLES = "/articles";

export function articlePath(slugOrSection: string): string {
  return `${ARTICLES}/${slugOrSection}`;
}
