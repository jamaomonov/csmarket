/** «Календарь»: a month by day, Monday first; pick a day or two to open them in «Бизнес». */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Channel, type DayOut, getCalendar } from "./api";
import { calendarKey } from "./keys";
import { som } from "./labels";
import { shiftMonth, type Span } from "./period";

import { useNarrow } from "@/lib/useNarrow";

const MONTHS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];
const GENITIVE = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];
const WEEK = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

type Tone = "profit" | "loss" | "empty";

function profitOf(d: DayOut): number {
  return (
    Number(d.earned_profit_uzs) + Number(d.in_flight_profit_uzs) + Number(d.buyback_profit_uzs)
  );
}

function toneOf(d: DayOut): Tone {
  if (d.orders === 0 && Number(d.buyback_profit_uzs) === 0) return "empty";
  return profitOf(d) < 0 ? "loss" : "profit";
}

/** `09.10` of `2026-10-09`. */
function short(day: string): string {
  return `${day.slice(8, 10)}.${day.slice(5, 7)}`;
}

/** Monday-first offset of the month's first day. */
function leadingBlanks(month: string): number {
  const first = new Date(`${month}-01T00:00:00Z`).getUTCDay(); // 0 = Sunday
  return (first + 6) % 7;
}

interface CalendarTabProps {
  month: string;
  channel: Channel;
  onMonth: (month: string) => void;
  onOpen: (span: Span) => void;
}

export function CalendarTab({ month, channel, onMonth, onOpen }: CalendarTabProps) {
  const narrow = useNarrow();
  const [picked, setPicked] = useState<string[]>([]);
  const q = useQuery({
    queryKey: calendarKey(month, channel),
    queryFn: () => getCalendar(month, channel),
  });
  const days = q.data?.days ?? [];
  const best = Math.max(1, ...days.map(profitOf));
  const [y, m] = month.split("-").map(Number);
  const title = `${MONTHS[(m ?? 1) - 1] ?? ""} ${String(y)}`;
  const pick = (day: string) => {
    setPicked((now) => (now.length === 1 && now[0] !== day ? [now[0] ?? day, day].sort() : [day]));
  };
  const span: Span | null =
    picked.length === 0 ? null : { since: picked[0] ?? "", until: picked[picked.length - 1] ?? "" };
  const cells: (DayOut | null)[] = [...Array<null>(leadingBlanks(month)).fill(null), ...days];
  const weeks: (DayOut | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          aria-label="Предыдущий месяц"
          onClick={() => {
            setPicked([]);
            onMonth(shiftMonth(month, -1));
          }}
        >
          ‹
        </Button>
        <h2 className="min-w-36 text-center font-semibold">{title}</h2>
        <Button
          size="sm"
          variant="secondary"
          aria-label="Следующий месяц"
          onClick={() => {
            setPicked([]);
            onMonth(shiftMonth(month, 1));
          }}
        >
          ›
        </Button>
        {span !== null && (
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => {
              onOpen(span);
            }}
          >
            {span.since === span.until
              ? `Открыть ${short(span.since)}`
              : `Открыть ${short(span.since)} – ${short(span.until)}`}
          </Button>
        )}
      </div>
      {q.isPending ? (
        <p className="text-fg-muted">Загрузка…</p>
      ) : (
        <div role="grid" aria-label={title} className="space-y-1">
          <div role="row" className="text-fg-muted grid grid-cols-7 gap-1 text-center text-xs">
            {WEEK.map((w) => (
              <div key={w} role="columnheader">
                {w}
              </div>
            ))}
          </div>
          {weeks.map((week, i) => (
            <div key={i} role="row" className="grid grid-cols-7 gap-1">
              {week.map((d, j) =>
                d === null ? (
                  <div key={`blank-${String(j)}`} role="gridcell" />
                ) : (
                  <div key={d.day} role="gridcell">
                    <DayCell
                      day={d}
                      tone={toneOf(d)}
                      share={Math.max(0, profitOf(d)) / best}
                      selected={span !== null && d.day >= span.since && d.day <= span.until}
                      narrow={narrow}
                      onPick={pick}
                    />
                  </div>
                ),
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface DayCellProps {
  day: DayOut;
  tone: Tone;
  share: number;
  selected: boolean;
  narrow: boolean;
  onPick: (day: string) => void;
}

function DayCell({ day, tone, share, selected, narrow, onPick }: DayCellProps) {
  const n = Number(day.day.slice(8, 10));
  const month = Number(day.day.slice(5, 7));
  const profit = profitOf(day);
  const background =
    tone === "loss"
      ? "color-mix(in oklab, var(--color-danger) 18%, transparent)"
      : tone === "profit"
        ? // Kept faint (8–22 %) so the day's figures stay readable on it at any profit.
          `color-mix(in oklab, var(--color-accent) ${String(Math.round(8 + share * 14))}%, transparent)`
        : undefined;
  return (
    <button
      type="button"
      data-tone={tone}
      aria-pressed={selected}
      aria-label={`${String(n)} ${GENITIVE[month - 1] ?? ""}: прибыль ${som(profit)}, оборот ${som(day.revenue_uzs)}`}
      onClick={() => {
        onPick(day.day);
      }}
      style={background !== undefined ? { background } : undefined}
      className={`border-border flex h-16 w-full flex-col items-start rounded border p-1 text-left text-xs tabular-nums sm:h-20 ${
        tone === "empty" ? "opacity-50" : ""
      } ${selected ? "ring-accent ring-2" : ""}`}
    >
      <span className="font-medium">{n}</span>
      {tone !== "empty" && (
        <>
          <span className={`font-semibold ${tone === "loss" ? "text-danger" : ""}`}>
            {som(profit)}
          </span>
          {!narrow && <span className="text-fg">{som(day.revenue_uzs)}</span>}
        </>
      )}
    </button>
  );
}
