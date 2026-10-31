/**
 * «Склад»: skins the owner took into his own Steam account — what they cost, what Skinslink gives
 * for them now, sold by hand. Filter by name, sort by cost or age; each row opens its deal.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DESK_KEY, listStock, type StockItem, stockPrices } from "./api";
import { deskErrorText } from "./labels";
import { DeskError, RowsSkeleton, skins, TAP } from "./Parts";
import { SellSheet } from "./SellSheet";
import { StockRow } from "./StockRow";

import { EmptyState } from "@/components/EmptyState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";

const SORTS = { cost: "Дороже сначала", age: "Давно лежат сначала" } as const;
type Sort = keyof typeof SORTS;

function arrange(items: StockItem[], q: string, sort: Sort): StockItem[] {
  const needle = q.trim().toLowerCase();
  const shown = needle ? items.filter((i) => i.name.toLowerCase().includes(needle)) : [...items];
  return shown.sort((a, b) =>
    sort === "cost"
      ? Number(b.cost_usd ?? 0) - Number(a.cost_usd ?? 0)
      : a.bought_at.localeCompare(b.bought_at),
  );
}

export function StockPage() {
  const [selling, setSelling] = useState<StockItem | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("cost");
  const stock = useQuery({ queryKey: [...DESK_KEY, "stock"], queryFn: listStock });
  const prices = useMutation({ mutationFn: stockPrices });
  const items = stock.data?.items ?? [];
  const field = "border-border bg-bg h-11 rounded-md border px-3";
  return (
    <section className="space-y-4">
      <PageHeader
        title="Склад"
        back={{ to: "/desk", label: "Мои сделки" }}
        meta={
          stock.data ? (
            <>
              {skins(items.length)} · <Money usd={stock.data.total_cost_usd} /> по себестоимости
            </>
          ) : null
        }
      />
      {stock.isError && (
        <DeskError
          error={stock.error}
          back
          onRetry={() => {
            void stock.refetch();
          }}
        />
      )}
      {stock.isPending && <RowsSkeleton />}
      {stock.data && items.length === 0 && (
        <EmptyState>На складе пусто. Сюда попадают скины, отмеченные «Себе».</EmptyState>
      )}
      {items.length > 0 && (
        <>
          <div className="flex flex-wrap items-end gap-3 text-sm">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              Найти на складе
              <input
                type="search"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                }}
                placeholder="Название скина"
                className={field}
              />
            </label>
            <label className="flex flex-col gap-1">
              Сортировка
              <select
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value === "age" ? "age" : "cost");
                }}
                className={field}
              >
                {(Object.keys(SORTS) as Sort[]).map((k) => (
                  <option key={k} value={k}>
                    {SORTS[k]}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="secondary"
              className={TAP}
              disabled={prices.isPending}
              onClick={() => {
                prices.mutate();
              }}
            >
              {prices.isPending ? "Спрашиваем Skinslink…" : "Обновить цены"}
            </Button>
          </div>
          {prices.isError && (
            <p role="alert" className="text-danger text-sm">
              {deskErrorText(prices.error)}
            </p>
          )}
          <ul className="divide-border border-border divide-y rounded-lg border" aria-label="Склад">
            {arrange(items, q, sort).map((i) => (
              <StockRow
                key={i.id}
                item={i}
                now={prices.data?.[i.name]}
                onSell={() => {
                  setSelling(i);
                }}
              />
            ))}
          </ul>
        </>
      )}
      {selling && (
        <SellSheet
          item={selling}
          onDone={() => {
            setSelling(null);
          }}
        />
      )}
    </section>
  );
}
