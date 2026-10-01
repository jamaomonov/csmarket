/** Operator-facing money and time formatting, shared by the admin pages (Russian). */
import { formatUzs } from "@csmarket/utils";

/** `"30000"` -> `30 000 сум`. */
export function formatSum(value: string | number): string {
  return formatUzs("ru", value);
}

/** `"+50000"` -> `+50 000 сум`, `"-20000"` -> `−20 000 сум` (typographic minus). */
export function formatSignedSum(value: string | number): string {
  const wire = String(value);
  const sign = wire.startsWith("-") ? "\u2212" : "+";
  return `${sign}${formatSum(wire.replace(/^[+-]/, ""))}`;
}

/** `DD.MM.YYYY HH:MM` in the viewer's local time. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const p = (n: number): string => String(n).padStart(2, "0");
  const date = `${p(d.getDate())}.${p(d.getMonth() + 1)}.${String(d.getFullYear())}`;
  return `${date} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
