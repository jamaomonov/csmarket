/**
 * The word for a UZS amount in a locale: ru «сум», uz «soʻm», anything else the ISO
 * code. Accepts a bare language tag ("ru") or a region-qualified one ("ru-RU").
 */
export function uzsWord(locale: string): string {
  const lang = locale.slice(0, 2).toLowerCase();
  if (lang === "ru") return "сум";
  if (lang === "uz") return "soʻm";
  return "UZS";
}

/**
 * Format whole soʻm for display: the locale's digit grouping, no decimals, then the
 * locale's word (`Intl`'s own currency style would print the bare ISO code). Amounts
 * travel as strings; one that is not a number renders as 0.
 */
export function formatUzs(locale: string, amount: string | number): string {
  const num = typeof amount === "number" ? amount : Number.parseFloat(amount);
  const safe = Number.isFinite(num) ? num : 0;
  const number = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(safe);
  return `${number} ${uzsWord(locale)}`;
}
