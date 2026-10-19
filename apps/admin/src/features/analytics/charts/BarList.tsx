/** A breakdown as rows with a bar proportional to revenue: key, orders, revenue, profit. */
import { type Slice } from "../api";
import { dollars, som } from "../labels";

interface BarListProps {
  rows: Slice[];
  label: (key: string) => string;
}

export function BarList({ rows, label }: BarListProps) {
  if (rows.length === 0) return <p className="text-fg-muted text-sm">Нет заказов.</p>;
  const max = Math.max(...rows.map((r) => Number(r.revenue_uzs)), 1);
  return (
    <ul className="space-y-2 text-sm">
      {rows.map((r) => {
        const loss = Number(r.profit_uzs) < 0;
        return (
          <li key={r.key} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate font-medium">{label(r.key)}</span>
              <span className="text-fg-muted shrink-0 tabular-nums">
                {r.orders} · {som(r.revenue_uzs)}
              </span>
            </div>
            <div className="bg-surface-2 h-1.5 overflow-hidden rounded">
              <div
                className="bg-accent h-full rounded"
                style={{ width: `${String((Number(r.revenue_uzs) / max) * 100)}%` }}
              />
            </div>
            <div className={`text-xs tabular-nums ${loss ? "text-danger" : "text-fg-muted"}`}>
              прибыль <span>{som(r.profit_uzs)}</span> · {dollars(r.profit_usd)} ·{" "}
              {r.margin_percent.replace(".", ",")} %
            </div>
          </li>
        );
      })}
    </ul>
  );
}
