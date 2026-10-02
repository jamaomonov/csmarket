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

/** «Мои заказы». */
export const ORDERS = "/account/orders";

/** The balance page («Открыть баланс», «Пополнить»). */
export const BALANCE = "/account/balance";
