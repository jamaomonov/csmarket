/** «Платежи»: find a payment by number, filter by status, kassa and purpose, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { type AdminPaymentsPage, listPayments, type ListPaymentsParams } from "./api";
import { PAYMENT_PROVIDERS, PAYMENT_PURPOSES, PAYMENT_STATUSES } from "./kinds";
import { PURPOSE_LABELS, STATUS_LABELS } from "./labels";
import { StatusChip } from "./StatusChip";

import { DataTable } from "@/components/DataTable";
import { FilterSelect, FiltersBar, SearchBox } from "@/components/Filters";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { UserCell } from "@/components/UserCell";
import { errorText, providerLabel } from "@/features/users/labels";
import { formatDateTime } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;
/** The API's `q` ceiling (and the input's `maxLength`). */
const Q_MAX = 32;

export function PaymentsPage() {
  const navigate = useNavigate();
  const url = useUrlParams();
  const urlQ = upTo(url.get("q"), Q_MAX);
  const status = pick(PAYMENT_STATUSES, url.get("status"));
  const provider = pick(PAYMENT_PROVIDERS, url.get("provider"));
  const purpose = pick(PAYMENT_PURPOSES, url.get("purpose"));

  // The box starts from `?q=` (links from the user card) and writes back once typing settles.
  const [text, setText] = useState(urlQ);
  const typed = useDebounced(text.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typed !== urlQ) set("q", typed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL; an outside change of `q` must not be overwritten by a stale box
  }, [typed]);

  const list = useInfiniteQuery<
    AdminPaymentsPage,
    Error,
    InfiniteData<AdminPaymentsPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: ["admin", "payments", "list", urlQ, status, provider, purpose],
    queryFn: ({ pageParam }) => {
      const params: ListPaymentsParams = {
        ...(urlQ !== "" && { q: urlQ }),
        ...(status && { status }),
        ...(provider && { provider }),
        ...(purpose && { purpose }),
        ...(pageParam !== null && { cursor: pageParam }),
      };
      return listPayments(params);
    },
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const payments = list.data?.pages.flatMap((p) => p.items);

  return (
    <section className="space-y-4">
      <PageHeader title="Платежи" />
      <FiltersBar>
        <SearchBox
          label="Номер платежа или пополнения"
          value={text}
          maxLength={Q_MAX}
          mono
          onChange={setText}
        />
        <FilterSelect
          label="Статус"
          value={status ?? ""}
          options={PAYMENT_STATUSES}
          text={(o) => STATUS_LABELS[o]}
          onChange={(v) => {
            url.set("status", v);
          }}
        />
        <FilterSelect
          label="Касса"
          value={provider ?? ""}
          options={PAYMENT_PROVIDERS}
          text={providerLabel}
          onChange={(v) => {
            url.set("provider", v);
          }}
        />
        <FilterSelect
          label="Назначение"
          value={purpose ?? ""}
          options={PAYMENT_PURPOSES}
          text={(o) => PURPOSE_LABELS[o]}
          onChange={(v) => {
            url.set("purpose", v);
          }}
        />
      </FiltersBar>
      <div
        data-testid={payments !== undefined && payments.length > 0 ? "payments-table" : undefined}
      >
        <DataTable
          label="Платежи"
          rows={payments}
          rowKey={(p) => p.id}
          loading={list.isPending}
          error={list.isError ? errorText(list.error) : undefined}
          empty="Ничего не нашли."
          onRowClick={(p) => {
            void navigate(`/payments/${p.id}`);
          }}
          columns={[
            {
              key: "number",
              header: "Номер",
              cell: (p) => (
                <>
                  <Link to={`/payments/${p.id}`} className="font-mono font-medium hover:underline">
                    {p.number}
                  </Link>
                  <div className="text-fg-muted text-xs">{PURPOSE_LABELS[p.purpose]}</div>
                </>
              ),
            },
            {
              key: "sum",
              header: "Сумма",
              align: "right",
              cell: (p) => <Money uzs={p.amount_uzs} />,
            },
            { key: "kassa", header: "Касса", cell: (p) => providerLabel(p.provider) },
            { key: "status", header: "Статус", cell: (p) => <StatusChip status={p.status} /> },
            {
              key: "user",
              header: "Пользователь",
              cell: (p) => <UserCell id={p.user.id} name={p.user.display_name} />,
            },
            {
              key: "created",
              header: "Создан",
              cell: (p) => (
                <span className="text-fg-muted whitespace-nowrap">
                  {formatDateTime(p.created_at)}
                </span>
              ),
            },
          ]}
          mobileCard={(p) => (
            <div className="space-y-1 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono">{p.number}</span>
                <Money uzs={p.amount_uzs} />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusChip status={p.status} />
                <span className="text-fg-muted">{providerLabel(p.provider)}</span>
                <span className="text-fg-dim ml-auto text-xs">{formatDateTime(p.created_at)}</span>
              </div>
            </div>
          )}
          footer={
            list.hasNextPage ? (
              <Button
                variant="secondary"
                size="sm"
                disabled={list.isFetchingNextPage}
                onClick={() => {
                  void list.fetchNextPage();
                }}
              >
                Показать ещё
              </Button>
            ) : undefined
          }
        />
      </div>
    </section>
  );
}
