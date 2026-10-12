/** How long a payable request has waited, and whether it is late (6 h) or overdue (10 h):
 * sellers are promised the card within 12 h. */

export type WaitLevel = "ok" | "late" | "overdue";

const HOUR = 3_600_000;
const LATE_HOURS = 6;
const OVERDUE_HOURS = 10;

/** `"2 д 3 ч"`, `"5 ч 10 мин"`, `"12 мин"` since `iso`, and the tint it deserves. */
export function waitingFor(
  iso: string,
  nowMs: number = Date.now(),
): { text: string; level: WaitLevel } {
  const ms = Math.max(0, nowMs - new Date(iso).getTime());
  const minutes = Math.floor(ms / 60_000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const text =
    days > 0
      ? `${String(days)} д ${String(hours % 24)} ч`
      : hours > 0
        ? `${String(hours)} ч ${String(minutes % 60)} мин`
        : `${String(minutes)} мин`;
  const level: WaitLevel =
    ms >= OVERDUE_HOURS * HOUR ? "overdue" : ms >= LATE_HOURS * HOUR ? "late" : "ok";
  return { text, level };
}

export const WAIT_CLASS: Record<WaitLevel, string> = {
  ok: "text-fg-muted",
  late: "text-warning font-medium",
  overdue: "text-danger font-semibold",
};
