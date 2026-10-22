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

/** `DD.MM.YYYY HH:MM:SS`: the exact time an operator matches against a market's or Steam's log. */
export function formatDateTimeSeconds(iso: string): string {
  const s = new Date(iso).getSeconds();
  return `${formatDateTime(iso)}:${String(s).padStart(2, "0")}`;
}

const RATE = new Intl.NumberFormat("ru", { maximumFractionDigits: 4 });

/** A USD rate: `"12650.5000"` -> `12 650,5 сум за $` (trailing zeros dropped). */
export function formatRate(value: string | number): string {
  return `${RATE.format(Number(value))}\u00a0сум за $`;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * The one time format of list rows (admin UX audit §2): relative inside the last 24 hours
 * («только что», «5 мин назад», «3 ч назад»), absolute beyond — `DD.MM HH:MM` this year,
 * `DD.MM.YYYY` an earlier one. A time slightly ahead (clock skew) reads «только что».
 * Detail pages keep `formatDateTime`; a list row puts it in the tooltip (`When`).
 */
export function listTime(iso: string, now: number = Date.now()): string {
  const d = new Date(iso);
  const ms = Math.max(0, now - d.getTime());
  if (ms < MINUTE) return "только что";
  if (ms < HOUR) return `${String(Math.floor(ms / MINUTE))} мин назад`;
  if (ms < DAY) return `${String(Math.floor(ms / HOUR))} ч назад`;
  const full = formatDateTime(iso);
  if (d.getFullYear() !== new Date(now).getFullYear()) return full.slice(0, 10);
  return `${full.slice(0, 5)} ${full.slice(11)}`;
}

/** `"250.000"` -> `$250.000` (the API's three-decimal dollar string, as is). */
export function formatUsd(value: string): string {
  return `$${value}`;
}

/** `"+7.826"` -> `+$7.826`, `"-1.000"` -> `\u2212$1.000` (typographic minus). */
export function formatSignedUsd(value: string): string {
  const sign = value.startsWith("-") ? "\u2212" : "+";
  return `${sign}${formatUsd(value.replace(/^[+-]/, ""))}`;
}
