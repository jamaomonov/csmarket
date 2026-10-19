/** The analytics period: last N days, a calendar month or a range of Tashkent dates. */

export type Period =
  | { kind: "days"; days: 7 | 30 | 90 }
  | { kind: "month"; month: string }
  | { kind: "range"; since: string; until: string };

export interface Span {
  since: string;
  until: string;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const DAY_MS = 86_400_000;

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function utcDate(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

/** Today's date in Tashkent (UTC+5, no daylight saving) as `YYYY-MM-DD`. */
export function tashkentToday(at: Date = new Date()): string {
  return iso(new Date(at.getTime() + 5 * 3_600_000));
}

export function monthOf(day: string): string {
  return day.slice(0, 7);
}

/** `"2026-01"` shifted by `delta` months. */
export function shiftMonth(month: string, delta: number): string {
  const [y = 0, m = 1] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return iso(d).slice(0, 7);
}

export function windowOf(p: Period, today: string): Span {
  switch (p.kind) {
    case "days":
      return {
        since: iso(new Date(utcDate(today).getTime() - (p.days - 1) * DAY_MS)),
        until: today,
      };
    case "month": {
      const first = `${p.month}-01`;
      const last = new Date(utcDate(`${shiftMonth(p.month, 1)}-01`).getTime() - DAY_MS);
      return { since: first, until: iso(last) };
    }
    case "range":
      return { since: p.since, until: p.until };
    default:
      return assertNever(p);
  }
}

function assertNever(value: never): never {
  throw new Error(`unexpected period ${JSON.stringify(value)}`);
}

/** The period as URL query keys: `p` (days), `m` (month) or `from` / `to` (range). */
export function toParams(p: Period): Record<string, string> {
  switch (p.kind) {
    case "days":
      return { p: String(p.days), m: "", from: "", to: "" };
    case "month":
      return { p: "", m: p.month, from: "", to: "" };
    case "range":
      return { p: "", m: "", from: p.since, to: p.until };
    default:
      return assertNever(p);
  }
}

/** Read the period back; anything malformed is the default 30 days. */
export function fromParams(get: (key: string) => string): Period {
  const from = get("from");
  const to = get("to");
  if (DATE.test(from) && DATE.test(to) && from <= to)
    return { kind: "range", since: from, until: to };
  const month = get("m");
  if (MONTH.test(month)) return { kind: "month", month };
  const days = get("p");
  if (days === "7" || days === "90") return { kind: "days", days: days === "7" ? 7 : 90 };
  return { kind: "days", days: 30 };
}
