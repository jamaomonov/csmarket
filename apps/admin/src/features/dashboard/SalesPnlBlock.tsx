/**
 * «Выкуп» on the dashboard: what buying skins from users earned in the period — what
 * Skinslink credited, what went to cards (with the bank's fee) and balances (with the bonus),
 * what is still to pay, and the profit at the CBU rate (spec 2026-10-13-sales-pnl).
 */
import { type SalesPnlOut } from "./api";
import { Tile } from "./Tile";

import { formatMoneyUsd } from "@/components/Money";
import { formatSum } from "@/lib/format";

const usd = (v: string): string => formatMoneyUsd(v);

export function SalesPnlBlock({ pnl }: { pnl: SalesPnlOut | undefined }) {
  if (pnl === undefined || pnl.count === 0) return null;
  const loss = pnl.profit_usd.startsWith("-");
  return (
    <section aria-label="Выкуп" className="space-y-2">
      <h2 className="text-fg-muted text-xs font-medium uppercase tracking-wider">Выкуп</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile title="Выкуп: получено" to="/sales/reconciliation">
          <span>{usd(pnl.income_usd)}</span>
          <span className="text-fg-muted text-sm font-normal">продаж: {pnl.count}</span>
        </Tile>
        <Tile title="Выкуп: выплачено">
          <span>{formatSum(pnl.cost_uzs)}</span>
          <span className="text-fg-muted text-sm font-normal">
            карты {formatSum(pnl.to_cards_uzs)} · балансы {formatSum(pnl.to_balances_uzs)}
          </span>
          {pnl.to_pay_uzs !== "0" && (
            <span className="text-fg-muted text-sm font-normal">
              к выплате {formatSum(pnl.to_pay_uzs)}
            </span>
          )}
        </Tile>
        <Tile title="Выкуп: комиссии">
          <span>{formatSum(pnl.withheld_uzs)}</span>
          <span className="text-fg-muted text-sm font-normal">банку {formatSum(pnl.bank_uzs)}</span>
        </Tile>
        <Tile title="Выкуп: прибыль" alert={loss}>
          <span className={loss ? "text-danger" : ""}>{usd(pnl.profit_usd)}</span>
          <span className="text-fg-muted text-sm font-normal">
            {pnl.profit_percent} % от полученного
          </span>
        </Tile>
      </div>
    </section>
  );
}
