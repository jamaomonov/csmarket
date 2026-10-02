/** Russian words for the dashboard. */
import { type Days } from "./api";

export const TABS: readonly [string, Days, string][] = [
  ["1", 1, "Сегодня"],
  ["7", 7, "7 дней"],
  ["30", 30, "30 дней"],
];

export const TAB_KEYS = TABS.map(([key]) => key);

/** «обновлено 4 мин назад», from the read time and now. */
export function freshness(readAt: string, nowMs: number = Date.now()): string {
  const minutes = Math.max(0, Math.round((nowMs - Date.parse(readAt)) / 60_000));
  return minutes === 0 ? "обновлено только что" : `обновлено ${String(minutes)} мин назад`;
}

/** `2026-10-02` → `02.10`. */
export function shortDay(day: string): string {
  const [, month, date] = day.split("-");
  return `${date ?? ""}.${month ?? ""}`;
}
