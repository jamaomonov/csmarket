/** Short Russian times of the «Обмены» table, in the viewer's local time. */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const p = (n: number): string => String(n).padStart(2, "0");

/** `DD.MM HH:MM`. */
export function shortDateTime(iso: string): string {
  const d = new Date(iso);
  return `${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** `DD.MM`. */
export function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}`;
}

/** `HH:MM:SS`. */
export function clockTime(iso: string): string {
  const d = new Date(iso);
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** «только что», «3 мин назад», «5 ч назад», «2 д назад». */
export function ago(iso: string, now: number = Date.now()): string {
  const ms = Math.max(0, now - new Date(iso).getTime());
  if (ms < MINUTE) return "только что";
  if (ms < HOUR) return `${String(Math.floor(ms / MINUTE))} мин назад`;
  if (ms < DAY) return `${String(Math.floor(ms / HOUR))} ч назад`;
  return `${String(Math.floor(ms / DAY))} д назад`;
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
