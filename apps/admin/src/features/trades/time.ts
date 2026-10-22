/** Short Russian times of the «Обмены» table (a hold's end); row times are `When`. */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const p = (n: number): string => String(n).padStart(2, "0");

/** `DD.MM`. */
export function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}`;
}

/** What is left until `iso`: «6д 4ч», «3ч 20м», «15м»; «истекает» once it has passed. */
export function timeLeft(iso: string, now: number = Date.now()): string {
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return "истекает";
  const days = Math.floor(ms / DAY);
  const hours = Math.floor((ms % DAY) / HOUR);
  const minutes = Math.floor((ms % HOUR) / MINUTE);
  if (days > 0) return `${String(days)}д ${String(hours)}ч`;
  if (hours > 0) return `${String(hours)}ч ${String(minutes)}м`;
  return `${String(Math.max(1, minutes))}м`;
}
