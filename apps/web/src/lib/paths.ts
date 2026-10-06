/** Locale-less paths for next-intl's `Link` / `redirect`; the locale prefix is added there. */

export const HOME = "/";

export function itemPath(slug: string): string {
  return `/item/${slug}`;
}

export function categoryPath(category: string): string {
  return `/category/${category}`;
}

/** `weaponSlug` is the slugged weapon name (`ak-47`), see `skin-landing.ts`. */
export function weaponPath(weaponSlug: string): string {
  return `/weapon/${weaponSlug}`;
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

/** Sections that are on their way («Скоро» pages for now). */
export const SELL = "/sell";
export const STEAM_TOPUP = "/steam";
export const REVIEWS = "/reviews";
export const REFERRAL = "/account/referral";

/** «Пополнение баланса»: the wallet with the kassas (top-up; withdrawals later). */
export const DEPOSIT = "/deposit";
