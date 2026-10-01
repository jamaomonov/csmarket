/** «Платежи»: find a payment by number, filter by status, kassa and purpose, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  type AdminPaymentRow,
  type AdminPaymentsPage,
  listPayments,
  type ListPaymentsParams,
} from "./api";
import { PAYMENT_PROVIDERS, PAYMENT_PURPOSES, PAYMENT_STATUSES } from "./kinds";
import { PURPOSE_LABELS, STATUS_LABELS } from "./labels";
import { StatusChip } from "./StatusChip";

import { errorText, providerLabel } from "@/features/users/labels";
import { formatDateTime, formatSum } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;

/** The value if it is one of `allowed`, else `undefined` (a hand-edited URL is ignored). */
function pick<T extends string>(allowed: readonly T[], value: string): T | undefined {
  return allowed.find((a) => a === value);
}

interface FilterSelectProps<T extends string> {
  label: string;
  value: string;
  options: readonly T[];
  text: (option: T) => string;
  onChange: (value: string) => void;
}

function FilterSelect<T extends string>({
  label,
  value,
  options,
  text,
  onChange,
}: FilterSelectProps<T>) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <select
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        className="border-border bg-bg h-10 rounded-md border px-3 text-base"
      >
        <option value="">Все</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {text(o)}
          </option>
        ))}
      </select>
    </label>
  );
}

function PaymentRow({ payment }: { payment: AdminPaymentRow }) {
  return (
    <tr className="border-border border-t">
      <td className="py-2 pr-3">
        <Link to={`/payments/${payment.id}`} className="font-mono font-medium hover:underline">
          {payment.number}
        </Link>
        <div className="text-fg-muted text-xs">{PURPOSE_LABELS[payment.purpose]}</div>
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatSum(payment.amount_uzs)}
      </td>
      <td className="py-2 pr-3">{providerLabel(payment.provider)}</td>
      <td className="py-2 pr-3">
        <StatusChip status={payment.status} />
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${payment.user.id}`} className="hover:underline">
          {payment.user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2">{formatDateTime(payment.created_at)}</td>
    </tr>
  );
}

export function PaymentsPage() {
  const url = useUrlParams();
  const urlQ = url.get("q");
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
  const payments = list.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">Платежи</h1>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          Номер платежа или пополнения
          <input
            type="search"
            value={text}
            maxLength={32}
            onChange={(e) => {
              setText(e.target.value);
            }}
            className="border-border bg-bg h-10 rounded-md border px-3 font-mono text-base"
          />
        </label>
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
      </div>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && payments.length === 0 && <p className="text-fg-muted">Ничего не нашли.</p>}
      {payments.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="payments-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">Номер</th>
                <th className="py-1 text-right font-normal">Сумма</th>
                <th className="py-1 font-normal">Касса</th>
                <th className="py-1 font-normal">Статус</th>
                <th className="py-1 font-normal">Пользователь</th>
                <th className="py-1 font-normal">Создан</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <PaymentRow key={p.id} payment={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <Button
          variant="secondary"
          disabled={list.isFetchingNextPage}
          onClick={() => {
            void list.fetchNextPage();
          }}
        >
          Показать ещё
        </Button>
      )}
    </section>
  );
}
