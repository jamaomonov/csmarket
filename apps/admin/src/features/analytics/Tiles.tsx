/** The period's headline tiles, each against the previous period of the same length. */
import { type ReactNode } from "react";

import { type Totals } from "./api";
import { type Delta, delta, dollars, som } from "./labels";

/** `up` is good for money and orders; for refunds it is bad. */
function Change({ d, upIsBad = false }: { d: Delta; upIsBad?: boolean }) {
  const good = d.dir === "up" ? !upIsBad : d.dir === "down" ? upIsBad : null;
  const tone = good === null ? "text-fg-muted" : good ? "text-success" : "text-danger";
  return <span className={`text-xs font-medium ${tone}`}>{d.text}</span>;
}

interface TileProps {
  title: string;
  children: ReactNode;
  change?: Delta;
  upIsBad?: boolean;
  sub?: ReactNode;
}

function Tile({ title, children, change, upIsBad, sub }: TileProps) {
  return (
    <div data-testid={`tile-${title}`} className="border-border bg-surface rounded-lg border p-4">
      <div className="text-fg-muted text-sm">{title}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{children}</div>
      {sub !== undefined && <div className="text-fg-muted text-xs tabular-nums">{sub}</div>}
      {change !== undefined && <Change d={change} upIsBad={upIsBad ?? false} />}
    </div>
  );
}

export function Tiles({ now, before }: { now: Totals; before: Totals }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Tile
        title="Оборот"
        change={delta(now.revenue.uzs, before.revenue.uzs)}
        sub={dollars(now.revenue.usd)}
      >
        {som(now.revenue.uzs)}
      </Tile>
      <Tile
        title="Валовая прибыль"
        change={delta(now.gross_profit_uzs, before.gross_profit_uzs)}
        sub={`заказы ${som(now.profit.uzs)} · выкуп ${som(now.buyback_profit_uzs)}`}
      >
        {som(now.gross_profit_uzs)}
      </Tile>
      <Tile title="Маржа" sub={`прибыль заказов ${dollars(now.profit.usd)}`}>
        {now.margin_percent.replace(".", ",")} %
      </Tile>
      <Tile
        title="Заказов"
        change={delta(now.orders, before.orders)}
        sub={`в пути ${String(now.in_flight_orders)} · ${som(now.in_flight_profit_uzs)}`}
      >
        {now.orders}
      </Tile>
      <Tile title="Средний чек" change={delta(now.average_check_uzs, before.average_check_uzs)}>
        {som(now.average_check_uzs)}
      </Tile>
      <Tile title="Выкуп: прибыль" sub={dollars(now.buyback_profit_usd)}>
        {som(now.buyback_profit_uzs)}
      </Tile>
      <Tile
        title="Возвраты"
        change={delta(now.refunds, before.refunds)}
        upIsBad
        sub={som(now.refunds_uzs)}
      >
        {now.refunds}
      </Tile>
      <Tile title="Новых покупателей" change={delta(now.new_buyers, before.new_buyers)}>
        {now.new_buyers}
      </Tile>
    </div>
  );
}
