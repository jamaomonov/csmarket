/**
 * «Заявки на выплату»: status `Tabs` with counts (`?status=`), the day's totals, a search (sale
 * number, last four, name, Steam ID). «К выплате» is oldest first with the waiting time tinted
 * after 6 h and 10 h, and who is paying each request right now. Cards on a phone; refreshed every 15 s so
 * a request someone took or paid does not linger.
 */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PAYOUTS_KEY } from "./keys";
import { cardLabel, FLAG_DANGER, PAYOUT_TABS } from "./labels";
import {
  listPayouts,
  PAYOUT_STATUSES,
  type PayoutRow,
  type PayoutsPage as Page,
  type PayoutStatus,
  type PayoutTab,
  type PayoutTotals,
} from "./payoutsApi";
import { WAIT_CLASS, waitingFor } from "./waiting";

import { DataTable } from "@/components/DataTable";
import { FiltersBar, SearchBox } from "@/components/Filters";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusChip } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { LINK } from "@/components/TextLink";
import { UserCell } from "@/components/UserCell";
import { When } from "@/components/When";
import { errorText } from "@/features/users/labels";
import { reasonText } from "@/lib/dictionary";
import { formatSum } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const REFRESH_MS = 15_000;
const DEBOUNCE_MS = 300;

function Waiting({ row }: { row: PayoutRow }) {
  if (row.status !== "to_pay" || !row.to_pay_at) {
    return <When iso={row.paid_at ?? row.created_at} className="text-fg-muted" />;
  }
  const w = waitingFor(row.to_pay_at);
  return <span className={WAIT_CLASS[w.level]}>ждёт {w.text}</span>;
}

function Flags({ row }: { row: PayoutRow }) {
  const claimed = row.claimed_by ?? null;
  if ((row.flags ?? []).length === 0 && claimed === null) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {claimed !== null ? (
        <StatusChip tone="info">платит {claimed.display_name ?? "администратор"}</StatusChip>
      ) : null}
      {(row.flags ?? []).map((f) => (
        <StatusChip key={f} tone={FLAG_DANGER[f] ? "danger" : "progress"}>
          {reasonText("payoutFlag", f)}
        </StatusChip>
      ))}
    </div>
  );
}

function Totals({ totals }: { totals: PayoutTotals }) {
  return (
    <dl className="border-border bg-surface grid grid-cols-2 gap-2 rounded-lg border p-3 text-sm sm:grid-cols-3">
      <div>
        <dt className="text-fg-muted">К выплате сейчас</dt>
        <dd className="font-semibold tabular-nums">
          {totals.to_pay_count} · {formatSum(totals.to_pay_uzs)}
        </dd>
      </div>
      <div>
        <dt className="text-fg-muted">Выплачено сегодня</dt>
        <dd className="font-semibold tabular-nums">
          {totals.paid_today_count} · {formatSum(totals.paid_today_uzs)}
        </dd>
      </div>
      <div>
        <dt className="text-fg-muted">Отклонено сегодня</dt>
        <dd className="font-semibold tabular-nums">{totals.rejected_today_count}</dd>
      </div>
    </dl>
  );
}

function MobileCard({ row }: { row: PayoutRow }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <Money uzs={row.amount_uzs} className="text-lg font-semibold" />
        <Waiting row={row} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-mono">{cardLabel(row.card_type, row.card_masked)}</span>
        <span className="text-fg-muted">{row.user.display_name ?? "Без имени"}</span>
        <span className="text-fg-dim ml-auto font-mono text-xs">{row.sale_number}</span>
      </div>
      <Flags row={row} />
    </div>
  );
}

export function PayoutsPage() {
  const navigate = useNavigate();
  const url = useUrlParams();
  const q = upTo(url.get("q"), 64);
  const searching = q !== "";
  const status: PayoutTab = searching
    ? "all"
    : (pick(PAYOUT_STATUSES, url.get("status")) ?? "to_pay");
  const [text, setText] = useState(q);
  const typed = useDebounced(text.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typed !== q) set("q", typed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL
  }, [typed]);
  const query = useInfiniteQuery<
    Page,
    Error,
    InfiniteData<Page, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...PAYOUTS_KEY, status, q],
    queryFn: ({ pageParam }) => listPayouts(status, pageParam ?? undefined, q || undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    refetchInterval: REFRESH_MS,
  });
  const first = query.data?.pages[0];
  // The counts ride on every page; keep the last ones so the badges do not blink on a tab switch.
  const lastCounts = useRef<Page["counts"] | null>(null);
  if (first !== undefined) lastCounts.current = first.counts;
  const counts = lastCounts.current;
  const items = query.data?.pages.flatMap((p) => p.items);
  return (
    <section className="space-y-4">
      <PageHeader title="Заявки на выплату" />
      {first?.totals ? <Totals totals={first.totals} /> : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        {searching ? (
          <p className="text-fg-muted text-sm">Поиск по всем статусам.</p>
        ) : (
          <Tabs<PayoutStatus>
            label="Статусы"
            value={status === "all" ? "to_pay" : status}
            onChange={(s) => {
              url.set("status", s);
            }}
            items={PAYOUT_STATUSES.map((s) => ({
              key: s,
              label: PAYOUT_TABS[s],
              ...(counts !== null && { count: counts[s] }),
              alert: s === "to_pay",
            }))}
          />
        )}
        <FiltersBar>
          <SearchBox
            label="Продажа, карта, имя или Steam ID"
            value={text}
            maxLength={64}
            onChange={setText}
          />
        </FiltersBar>
      </div>
      <DataTable
        label="Заявки"
        rows={items}
        rowKey={(r) => r.id}
        loading={query.isPending}
        error={query.isError ? errorText(query.error) : undefined}
        empty="Заявок нет."
        attention={(r) =>
          (r.flags ?? []).some((f) => FLAG_DANGER[f]) ||
          (r.status === "to_pay" &&
            r.to_pay_at !== null &&
            waitingFor(r.to_pay_at).level === "overdue")
        }
        onRowClick={(r) => {
          void navigate(`/payouts/${r.id}`);
        }}
        columns={[
          {
            key: "sale",
            header: "Продажа",
            cell: (r) => (
              <Link to={`/payouts/${r.id}`} className={`${LINK} font-mono`}>
                {r.sale_number}
              </Link>
            ),
          },
          {
            key: "user",
            header: "Пользователь",
            cell: (r) => (
              <>
                <UserCell id={r.user.id} name={r.user.display_name} avatarUrl={r.user.avatar_url} />
                <Flags row={r} />
              </>
            ),
          },
          { key: "card", header: "Карта", cell: (r) => cardLabel(r.card_type, r.card_masked) },
          {
            key: "amount",
            header: "Сумма",
            align: "right",
            cell: (r) => <Money uzs={r.amount_uzs} />,
          },
          {
            key: "since",
            header: status === "to_pay" ? "Ждёт" : "Когда",
            cell: (r) => <Waiting row={r} />,
          },
        ]}
        mobileCard={(r) => <MobileCard row={r} />}
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
