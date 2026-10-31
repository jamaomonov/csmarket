/**
 * The owner's figures for a period: the profit first («+$X · N сделок»), the rest as tiles that
 * scroll sideways on a phone, «Вывел себе…» and what was taken out.
 */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { DESK_KEY, getSummary } from "./api";
import { DeskError, plural, TAP } from "./Parts";
import { Withdraw, Withdrawals } from "./Withdraw";

import { Money } from "@/components/Money";
import { Tabs } from "@/components/Tabs";

const PERIODS = {
  "1": "Сегодня",
  "7": "7 дней",
  "30": "30 дней",
  "365": "Год",
  custom: "Свой период",
} as const;
type Period = keyof typeof PERIODS;

/** Today's date in Tashkent as `YYYY-MM-DD`, whatever the browser's time zone. */
const TASHKENT_DAY = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Tashkent",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** `YYYY-MM-DD` of `days − 1` days ago, by the day in Tashkent (the server's window). */
function since(days: number): string {
  const d = new Date(`${TASHKENT_DAY.format(new Date())}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - (days - 1));
  return d.toISOString().slice(0, 10);
}

export function DeskSummary() {
  const [period, setPeriod] = useState<Period>("30");
  const [from, setFrom] = useState(since(30));
  const [to, setTo] = useState(since(1));
  const [withdrawing, setWithdrawing] = useState(false);
  const custom = period === "custom";
  const range: [string, string | undefined] = custom
    ? [from, to]
    : [since(Number(period)), undefined];
  const summary = useQuery({
    queryKey: [...DESK_KEY, "summary", ...range],
    queryFn: () => getSummary(...range),
    enabled: !custom || (from !== "" && to !== "" && from <= to),
  });
  const s = summary.data;
  const date = "border-border bg-bg h-11 rounded-md border px-2";
  return (
    <div className="space-y-3">
      <Tabs
        label="Период"
        value={period}
        onChange={setPeriod}
        items={(Object.keys(PERIODS) as Period[]).map((k) => ({ key: k, label: PERIODS[k] }))}
      />
      {custom && (
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex flex-col gap-1">
            С
            <input
              type="date"
              value={from}
              max={to}
              onChange={(e) => {
                setFrom(e.target.value);
              }}
              className={date}
            />
          </label>
          <label className="flex flex-col gap-1">
            По
            <input
              type="date"
              value={to}
              min={from}
              onChange={(e) => {
                setTo(e.target.value);
              }}
              className={date}
            />
          </label>
        </div>
      )}
      {summary.isError && (
        <DeskError
          error={summary.error}
          onRetry={() => {
            void summary.refetch();
          }}
        />
      )}
      {summary.isLoading && (
        <div aria-busy="true" className="bg-surface h-28 animate-pulse rounded-lg" />
      )}
      {s && (
        <div aria-label="Итоги" className="space-y-3">
          <div className="border-border bg-surface rounded-lg border p-3">
            <p className="text-fg-muted text-xs">Прибыль</p>
            <p className="text-h3 font-semibold" data-testid="desk-profit">
              <Money usd={s.profit_usd} signed /> ·{" "}
              {plural(s.deals_closed, ["сделка", "сделки", "сделок"])}
            </p>
          </div>
          <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:grid-cols-4 md:overflow-visible md:px-0">
            <Tile title="Зачислено Skinslink">
              <Money usd={s.revenue_usd} />
            </Tile>
            <Tile title="В пути" hint="Скины для Skinslink, ещё не зачисленные">
              <Money usd={s.in_transit_usd} />
            </Tile>
            <Tile title="На складе (по себестоимости)">
              <Money usd={s.stock_usd} />
            </Tile>
            <Tile title="Мои деньги на Skinslink" hint="Зачислено минус выведенное">
              <Money usd={s.skinslink_share_usd} />
              <Button
                variant="secondary"
                className={`mt-2 w-full ${TAP}`}
                onClick={() => {
                  setWithdrawing(true);
                }}
              >
                Вывел себе…
              </Button>
            </Tile>
          </div>
        </div>
      )}
      {withdrawing && (
        <Withdraw
          onClose={() => {
            setWithdrawing(false);
          }}
        />
      )}
      <Withdrawals />
    </div>
  );
}

interface TileProps {
  title: string;
  hint?: string;
  children: ReactNode;
}

function Tile({ title, hint, children }: TileProps) {
  return (
    <div className="border-border bg-surface min-w-44 shrink-0 snap-start rounded-lg border p-3 md:min-w-0">
      <p className="text-fg-muted text-xs">{title}</p>
      <div className="mt-1 font-semibold">{children}</div>
      {hint && <p className="text-fg-dim mt-1 text-xs">{hint}</p>}
    </div>
  );
}
