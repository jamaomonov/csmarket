/** Landing number formatting: digit groups in the page's locale (soʻm amounts are whole). */
const LOCALE_TAG: Record<string, string> = { ru: "ru-RU", uz: "uz-Latn-UZ", en: "en-US" };

/** `"171800"` → `171 800` (ru / uz) or `171,800` (en); `null` stays `null`. */
export function groupDigits(locale: string, value: string | number | null): string | null {
  if (value === null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return new Intl.NumberFormat(LOCALE_TAG[locale] ?? "ru-RU", { maximumFractionDigits: 0 }).format(
    n,
  );
}

/** Rarity colour → a soft CSS var value for the card glows (falls back to Mil-Spec blue). */
export function rarityVar(color: string | null): Record<string, string> {
  return { "--r": color ?? "#4b69ff" };
}

/** Joins class names, skipping falsy ones (a leading-space template is trimmed by the formatter). */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}
