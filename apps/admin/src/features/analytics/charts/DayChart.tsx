/** Profit by day — earned and in flight stacked, buy-back beside — with revenue as a line. */
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { type DayOut } from "../api";
import { compactSom, som } from "../labels";

function rows(days: DayOut[]) {
  return days.map((d) => ({
    day: d.day.slice(8, 10) + "." + d.day.slice(5, 7),
    earned: Number(d.earned_profit_uzs),
    flying: Number(d.in_flight_profit_uzs),
    buyback: Number(d.buyback_profit_uzs),
    revenue: Number(d.revenue_uzs),
  }));
}

const NAMES: Record<string, string> = {
  earned: "Заработано",
  flying: "В пути",
  buyback: "Выкуп",
  revenue: "Оборот",
};

export function DayChart({ days }: { days: DayOut[] }) {
  return (
    <div data-testid="day-chart" className="h-72 w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows(days)} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="day" tick={{ fill: "var(--color-fg-muted)", fontSize: 11 }} />
          <YAxis
            yAxisId="profit"
            tickFormatter={(v: number) => compactSom(v)}
            tick={{ fill: "var(--color-fg-muted)", fontSize: 11 }}
            width={60}
          />
          <YAxis
            yAxisId="revenue"
            orientation="right"
            tickFormatter={(v: number) => compactSom(v)}
            tick={{ fill: "var(--color-fg-dim)", fontSize: 11 }}
            width={52}
          />
          <Tooltip
            formatter={(value: number, name: string) => [som(value), NAMES[name] ?? name]}
            contentStyle={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
            }}
          />
          <Legend formatter={(name: string) => NAMES[name] ?? name} />
          <Bar yAxisId="profit" dataKey="earned" stackId="p" fill="var(--color-accent)" />
          <Bar yAxisId="profit" dataKey="flying" stackId="p" fill="var(--color-fg-dim)" />
          <Bar yAxisId="profit" dataKey="buyback" fill="var(--color-info, #60a5fa)" />
          <Line
            yAxisId="revenue"
            dataKey="revenue"
            dot={false}
            stroke="var(--color-fg-muted)"
            strokeWidth={2}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
