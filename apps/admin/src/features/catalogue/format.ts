/** Owner-facing number and time formatting for the catalogue page. */

const NUMBER = new Intl.NumberFormat("ru");

export function formatNumber(n: number): string {
  return NUMBER.format(n);
}

/** `HH:MM, DD.MM` in the viewer's local time. */
export function formatWhen(iso: string): string {
  const d = new Date(iso);
  const p = (n: number): string => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}, ${p(d.getDate())}.${p(d.getMonth() + 1)}`;
}

/** `12700.0000` -> `12 700`. */
export function formatRate(usdUzs: string): string {
  return NUMBER.format(Math.round(Number(usdUzs)));
}
