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
