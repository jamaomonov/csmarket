/**
 * «Дашборд»: today / 7 / 30 Tashkent days — sales, revenue, margin, refunds — and what needs
 * a look now: orders in flight, open attentions, the Waxpeer, Skinslink and LIS-SKINS balances. Re-read every minute.
 */
import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { type DashboardOut, type Days, getDashboard } from "./api";
import { freshness, shortDay, TAB_KEYS, TABS } from "./labels";

import { ApiError, formatApiError } from "@/lib/api";
import { formatSum } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const REFRESH_MS = 60_000;

interface TileProps {
  title: string;
  children: ReactNode;
}

function Tile({ title, children }: TileProps) {
  return (
    <div data-testid={`tile-${title}`} className="border-border bg-surface rounded-lg border p-4">
      <div className="text-fg-muted text-sm">{title}</div>
      <div className="mt-1 flex flex-col gap-0.5 text-lg font-semibold">{children}</div>
    </div>
  );
}

function Tiles({ data }: { data: DashboardOut }) {
  const { sales, refunds, waxpeer, skinslink, lisskins } = data;
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Tile title="Продажи">{sales.count}</Tile>
      <Tile title="Выручка">
        <span>{formatSum(sales.revenue_uzs)}</span>
        <span className="text-fg-muted text-sm">${sales.revenue_usd}</span>
      </Tile>
      <Tile title="Маржа">
        <span>${sales.margin_usd}</span>
        <span className="text-fg-muted text-sm">{sales.margin_percent} % от выручки</span>
      </Tile>
      <Tile title="Возвраты">
        <span>{refunds.count}</span>
        <span className="text-fg-muted text-sm">{formatSum(refunds.amount_uzs)}</span>
      </Tile>
      <Tile title="В пути">{data.in_flight}</Tile>
      <Tile title="Требуют внимания">
        <Link
          to="/trades?view=attention"
          className={data.attention > 0 ? "text-danger underline" : "underline"}
        >
          {data.attention}
        </Link>
      </Tile>
      <Tile title="К выплате">
        <Link
          to="/payouts"
          className={data.payouts.to_pay_count > 0 ? "text-danger underline" : "underline"}
        >
          {data.payouts.to_pay_count}
        </Link>
        <span className="text-fg-muted text-sm">{formatSum(data.payouts.to_pay_uzs)}</span>
      </Tile>
      <Tile title="Баланс Waxpeer">
        {waxpeer.balance_usd === null || waxpeer.read_at === null ? (
          <span>неизвестно</span>
        ) : (
          <>
            <span>${waxpeer.balance_usd}</span>
            <span className="text-fg-muted text-sm">{freshness(waxpeer.read_at)}</span>
          </>
        )}
      </Tile>
      <Tile title="Баланс Skinslink">
        {skinslink.available_usd === null || skinslink.read_at === null ? (
          <span>неизвестно</span>
        ) : (
          <>
            <span>${skinslink.available_usd}</span>
            <span className="text-fg-muted text-sm">в холде ${skinslink.hold_usd ?? "0"}</span>
            <span className="text-fg-muted text-sm">{freshness(skinslink.read_at)}</span>
          </>
        )}
      </Tile>
      <Tile title="Баланс LIS-SKINS">
        {lisskins.available_usd === null || lisskins.read_at === null ? (
          <span>неизвестно</span>
        ) : (
          <>
            <span>${lisskins.available_usd}</span>
            <span className="text-fg-muted text-sm">
              заблокировано ${lisskins.locked_usd ?? "0"}
            </span>
            <span className="text-fg-muted text-sm">{freshness(lisskins.read_at)}</span>
          </>
        )}
      </Tile>
    </div>
  );
}

function ByDay({ data }: { data: DashboardOut }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-fg-muted text-left">
          <th className="py-2 font-normal">Дата</th>
          <th className="py-2 font-normal">Продажи</th>
          <th className="py-2 font-normal">Выручка</th>
          <th className="py-2 font-normal">Маржа</th>
        </tr>
      </thead>
      <tbody>
        {[...data.by_day].reverse().map((d) => (
          <tr key={d.day} className="border-border border-t">
            <td className="py-2">{shortDay(d.day)}</td>
            <td className="py-2">{d.sales_count}</td>
            <td className="py-2">{d.revenue_uzs === "0" ? "—" : formatSum(d.revenue_uzs)}</td>
            <td className="py-2">${d.margin_usd}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function DashboardPage() {
  const url = useUrlParams();
  const key = pick(TAB_KEYS, url.get("days")) ?? "1";
  const days: Days = TABS.find(([k]) => k === key)?.[1] ?? 1;
  const query = useQuery({
    queryKey: ["admin", "dashboard", days],
    queryFn: () => getDashboard(days),
    refetchInterval: REFRESH_MS,
  });
  return (
    <section className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-bold">Дашборд</h1>
        <div className="flex gap-2">
          {TABS.map(([k, , label]) => (
            <Button
              key={k}
              type="button"
              size="sm"
              variant={k === key ? "primary" : "secondary"}
              aria-pressed={k === key}
              onClick={() => {
                url.set("days", k === "1" ? "" : k);
              }}
            >
              {label}
            </Button>
          ))}
        </div>
      </header>
      {query.isError && (
        <p role="alert" className="text-danger">
          {query.error instanceof ApiError
            ? formatApiError(query.error)
            : "Не получилось загрузить."}
        </p>
      )}
      {query.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {query.data && (
        <>
          <Tiles data={query.data} />
          <ByDay data={query.data} />
        </>
      )}
    </section>
  );
}
