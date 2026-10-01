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
