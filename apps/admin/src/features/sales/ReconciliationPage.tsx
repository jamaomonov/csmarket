/**
 * «Сверка»: each sale Skinslink completed in the period — what it quoted, what it credited, the
 * difference — with the problems flagged: credited under 99 % of the quote, completed with no
 * amount, or rolled back (spec 2026-10-13-sales-pnl). Open a sale to see its Skinslink trade.
 */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  FLAG_LABELS,
  getReconciliation,
  RECON_KEY,
  type ReconDays,
  type ReconPage,
} from "./reconApi";
import { SaleStatusChip } from "./StatusChips";

import { DataTable } from "@/components/DataTable";
import { FilterSelect, FiltersBar } from "@/components/Filters";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { When } from "@/components/When";
import { errorText } from "@/features/users/labels";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const PERIODS = ["1", "7", "30"] as const;
const PERIOD_LABELS: Record<(typeof PERIODS)[number], string> = {
  "1": "Сегодня",
  "7": "7 дней",
  "30": "30 дней",
};

export function ReconciliationPage() {
  const navigate = useNavigate();
  const url = useUrlParams();
  const period = pick(PERIODS, url.get("days")) ?? "7";
  const days = Number(period) as ReconDays; // one of PERIODS, all valid windows
  const problems = url.get("problems") === "1";

  const query = useInfiniteQuery<
    ReconPage,
    Error,
    InfiniteData<ReconPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...RECON_KEY, days, problems],
    queryFn: ({ pageParam }) =>
      getReconciliation({ days, problems, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const first = query.data?.pages[0];
  const items = query.data?.pages.flatMap((p) => p.items);
  return (
    <section className="space-y-4">
      <PageHeader title="Сверка Skinslink" />
      {first && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Итоги">
          <Total title="Ожидали">
            <Money usd={first.expected_usd} />
          </Total>
          <Total title="Зачислено">
            <Money usd={first.credited_usd} />
          </Total>
          <Total title="Разница">
            <span className={first.diff_usd.startsWith("-") ? "text-danger" : ""}>
              <Money usd={first.diff_usd} />
            </span>
          </Total>
          <Total title="Проблемы">
            <span className={first.problems > 0 ? "text-danger" : ""}>{first.problems}</span>
          </Total>
        </div>
      )}
      <FiltersBar>
        <FilterSelect
          label="Период"
          value={period}
          options={PERIODS}
          text={(p) => PERIOD_LABELS[p]}
          onChange={(v) => {
            url.set("days", v === "7" ? "" : v);
          }}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={problems}
            onChange={(e) => {
              url.set("problems", e.target.checked ? "1" : "");
            }}
          />
          Только проблемы
        </label>
      </FiltersBar>
      <DataTable
        label="Сверка"
        rows={items}
        rowKey={(r) => r.number}
        loading={query.isPending}
        error={query.isError ? errorText(query.error) : undefined}
        empty="Продаж за период нет."
        attention={(r) => r.flag !== null}
        onRowClick={(r) => {
          void navigate(`/sales/${r.number}`);
        }}
        columns={[
          {
            key: "number",
            header: "Продажа",
            cell: (r) => (
              <Link to={`/sales/${r.number}`} className="font-mono font-medium hover:underline">
                {r.number}
              </Link>
            ),
          },
          {
            key: "flag",
            header: "Статус",
            cell: (r) => (
              <>
                <SaleStatusChip status={r.status} />
                {r.flag && <div className="text-danger text-xs">{FLAG_LABELS[r.flag]}</div>}
              </>
            ),
          },
          {
            key: "quoted",
            header: "Ожидали",
            align: "right",
            cell: (r) => <Money usd={r.quoted_usd} />,
          },
          {
            key: "amount",
            header: "Зачислено",
            align: "right",
            cell: (r) => (r.amount_usd === null ? "—" : <Money usd={r.amount_usd} />),
          },
          {
            key: "diff",
            header: "Разница",
            align: "right",
            cell: (r) => (r.diff_usd === null ? "—" : <Money usd={r.diff_usd} />),
          },
          {
            key: "done",
            header: "Завершена",
            cell: (r) =>
              r.done_at ? (
                <When iso={r.done_at} className="text-fg-muted" />
              ) : (
                <span className="text-fg-muted">—</span>
              ),
          },
        ]}
        mobileCard={(r) => (
          <div className="space-y-1 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono">{r.number}</span>
              {r.amount_usd === null ? "—" : <Money usd={r.amount_usd} />}
            </div>
            <div className="flex flex-wrap gap-2">
              <span>
                из <Money usd={r.quoted_usd} />
              </span>
              {r.flag && <span className="text-danger">{FLAG_LABELS[r.flag]}</span>}
              {r.done_at ? (
                <When iso={r.done_at} className="text-fg-dim ml-auto text-xs" />
              ) : (
                <span className="text-fg-dim ml-auto text-xs">—</span>
              )}
            </div>
          </div>
        )}
        footer={
          query.hasNextPage ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              Показать ещё
            </Button>
          ) : undefined
        }
      />
    </section>
  );
}

function Total({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-border bg-surface rounded-lg border p-4">
      <div className="text-fg-muted text-sm">{title}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{children}</div>
    </div>
  );
}
