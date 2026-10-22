/** A previewed price and every component behind it. */
import { type PreviewOut } from "./api";
import { APPLIED } from "./labels";

import { formatSum } from "@/lib/format";

/** Percentage points added to the margin, in plain words: «+5 %», «−2 %», «0 %». */
export function points(pp: string): string {
  if (Number(pp) === 0) return "0 %";
  return pp.startsWith("-") ? `−${pp.slice(1)} %` : `+${pp} %`;
}

interface QuoteViewProps {
  quote: PreviewOut;
}

export function QuoteView({ quote }: QuoteViewProps) {
  const rows: [string, string][] = [
    ["Себестоимость", `$${quote.cost_usd}`],
    ["Расходы", `$${quote.expenses_usd}`],
    ["Маржа по себестоимости", `$${quote.bracket_margin_usd}`],
    ["Надбавка категории", points(quote.category_pp)],
    ["Надбавка оружия", points(quote.weapon_pp)],
    ["За мало лотов", points(quote.liquidity_pp)],
    ["Своя надбавка скина", points(quote.item_pp)],
    ["Итого наценка", `${quote.effective_percent} %`],
  ];
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-2xl font-bold">${quote.price_usd}</span>
        <span className="text-fg-muted">
          {quote.price_uzs === null ? "курс неизвестен" : formatSum(quote.price_uzs)}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-fg-muted">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        <dt className="text-fg-muted">Как посчитано</dt>
        <dd>{APPLIED[quote.applied]}</dd>
      </dl>
    </div>
  );
}
