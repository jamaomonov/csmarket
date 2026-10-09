/**
 * «Дашборд»: today / 7 / 30 Tashkent days — sales, revenue, margin, refunds — and what needs
 * a look now: orders in flight, open attentions, the Waxpeer, Skinslink and LIS-SKINS balances. Re-read every minute.
 */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { type DashboardOut, type Days, getDashboard } from "./api";
import { DASHBOARD_KEY } from "./keys";
import { freshness, shortDay, TAB_KEYS, TABS } from "./labels";

import { formatMoneyUsd } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { ApiError, formatApiError } from "@/lib/api";
import { formatSum } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const REFRESH_MS = 60_000;

interface TileProps {
  title: string;
  children: ReactNode;
  /** The whole tile opens this page. */
  to?: string;
  /** Something waits for an operator: a red edge. */
  alert?: boolean;
}

function Tile({ title, children, to, alert = false }: TileProps) {
  const body = (
    <>
      <div className="text-fg-muted text-sm">{title}</div>
      <div className="mt-1 flex flex-col gap-0.5 text-lg font-semibold tabular-nums">
        {children}
      </div>
    </>
  );
  const cls = `border-border bg-surface block rounded-lg border p-4 ${
    alert ? "shadow-[inset_3px_0_0_var(--color-danger)]" : ""
  }`;
  return (
    <div data-testid={`tile-${title}`}>
      {to === undefined ? (
        <div className={cls}>{body}</div>
      ) : (
        <Link to={to} className={`${cls} hover:bg-surface-hover`}>
          {body}
        </Link>
      )}
    </div>
  );
}

const usd = (v: string | number): string => formatMoneyUsd(v);

function Now({ data }: { data: DashboardOut }) {
  return (
    <section aria-label="Сделать сейчас" className="space-y-2">
      <h2 className="text-fg-muted text-xs font-medium uppercase tracking-wider">Сделать сейчас</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile title="Требуют внимания" to="/trades?view=attention" alert={data.attention > 0}>
          <span className={data.attention > 0 ? "text-danger" : ""}>{data.attention}</span>
        </Tile>
        <Tile title="К выплате" to="/payouts" alert={data.payouts.to_pay_count > 0}>
          <span className={data.payouts.to_pay_count > 0 ? "text-danger" : ""}>
            {data.payouts.to_pay_count}
          </span>
          <span className="text-fg-muted text-sm">{formatSum(data.payouts.to_pay_uzs)}</span>
        </Tile>
        <Tile title="В пути" to="/trades?view=active">
          {data.in_flight}
        </Tile>
      </div>
    </section>
  );
}

function Period({ data }: { data: DashboardOut }) {
  const { sales, refunds } = data;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Tile title="Продажи">{sales.count}</Tile>
      <Tile title="Выручка">
        <span>{formatSum(sales.revenue_uzs)}</span>
        <span className="text-fg-muted text-sm">{usd(sales.revenue_usd)}</span>
      </Tile>
      <Tile title="Маржа">
        <span>{usd(sales.margin_usd)}</span>
        <span className="text-fg-muted text-sm">{sales.margin_percent} % от выручки</span>
      </Tile>
      <Tile title="Возвраты">
        <span>{refunds.count}</span>
        <span className="text-fg-muted text-sm">{formatSum(refunds.amount_uzs)}</span>
      </Tile>
    </div>
  );
}

function Balances({ data }: { data: DashboardOut }) {
  const { waxpeer, skinslink, lisskins } = data;
  return (
    <section aria-label="Балансы площадок" className="space-y-2">
      <h2 className="text-fg-muted text-xs font-medium uppercase tracking-wider">
        Балансы площадок
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile title="Баланс Skinslink">
          {skinslink.available_usd === null || skinslink.read_at === null ? (
            <span>неизвестно</span>
          ) : (
            <>
              <span>{usd(skinslink.available_usd)}</span>
              <span className="text-fg-muted text-sm">
                в холде {usd(skinslink.hold_usd ?? "0")}
              </span>
              <span className="text-fg-dim text-xs">{freshness(skinslink.read_at)}</span>
            </>
          )}
        </Tile>
        <Tile title="Баланс LIS-SKINS">
          {lisskins.available_usd === null || lisskins.read_at === null ? (
            <span>неизвестно</span>
          ) : (
            <>
              <span>{usd(lisskins.available_usd)}</span>
              <span className="text-fg-muted text-sm">
                заблокировано {usd(lisskins.locked_usd ?? "0")}
              </span>
              <span className="text-fg-dim text-xs">{freshness(lisskins.read_at)}</span>
            </>
          )}
        </Tile>
        <Tile title="Баланс Waxpeer">
          {waxpeer.balance_usd === null || waxpeer.read_at === null ? (
            <span>неизвестно</span>
          ) : (
            <>
              <span>{usd(waxpeer.balance_usd)}</span>
              <span className="text-fg-dim text-xs">{freshness(waxpeer.read_at)}</span>
            </>
          )}
        </Tile>
      </div>
    </section>
  );
}

function ByDay({ data }: { data: DashboardOut }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-border text-fg-muted border-b text-left text-xs">
            <th className="px-3 py-2 font-normal">Дата</th>
            <th className="px-3 py-2 text-right font-normal">Продажи</th>
            <th className="px-3 py-2 text-right font-normal">Выручка</th>
            <th className="px-3 py-2 text-right font-normal">Маржа</th>
          </tr>
        </thead>
        <tbody>
          {[...data.by_day].reverse().map((d) => (
            <tr key={d.day} className="border-border border-b">
              <td className="px-3 py-2">{shortDay(d.day)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{d.sales_count}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {d.revenue_uzs === "0" ? "—" : formatSum(d.revenue_uzs)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{usd(d.margin_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DashboardPage() {
  const url = useUrlParams();
  const key = pick(TAB_KEYS, url.get("days")) ?? "1";
  const days: Days = TABS.find(([k]) => k === key)?.[1] ?? 1;
  const query = useQuery({
    queryKey: [...DASHBOARD_KEY, days],
    queryFn: () => getDashboard(days),
    refetchInterval: REFRESH_MS,
  });
  return (
    <section className="space-y-6">
      <PageHeader title="Дашборд" />
      {query.isError && (
        <p role="alert" className="text-danger">
          {query.error instanceof ApiError
            ? formatApiError(query.error)
            : "Не получилось загрузить."}
        </p>
      )}
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {query.data && <Now data={query.data} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-fg-muted text-xs font-medium uppercase tracking-wider">За период</h2>
        <div className="bg-surface inline-flex rounded-md p-0.5" role="group" aria-label="Период">
          {TABS.map(([k, , label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={k === key}
              onClick={() => {
                url.set("days", k === "1" ? "" : k);
              }}
              className={`rounded px-3 py-1 text-sm ${
                k === key ? "bg-surface-2 text-fg font-medium" : "text-fg-muted hover:text-fg"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {query.data && (
        <>
          <Period data={query.data} />
          <ByDay data={query.data} />
          <Balances data={query.data} />
        </>
      )}
    </section>
  );
}
