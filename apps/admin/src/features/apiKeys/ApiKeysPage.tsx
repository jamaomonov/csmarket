/** «API-ключи»: partners' keys with what each sold; live first, newest first. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  type AdminApiKeyRow,
  type AdminApiKeysPage,
  listApiKeys,
  type ListApiKeysParams,
} from "./api";
import { errorText, tariffLabel } from "./labels";

import { formatDateTime, formatUsd } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 300;

function params(q: string, cursor: string | null): ListApiKeysParams {
  return { ...(q !== "" && { q }), ...(cursor !== null && { cursor }) };
}

function KeyRow({ row }: { row: AdminApiKeyRow }) {
  return (
    <tr className="border-border border-t">
      <td className="py-2 pr-3">
        <Link to={`/api-keys/${row.id}`} className="font-medium hover:underline">
          {row.user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="py-2 pr-3">{tariffLabel(row.pricing_profile)}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{row.orders}</td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatUsd(row.revenue_usd)}
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatUsd(row.cost_usd)}
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2 pr-3">
        {row.last_used_at ? formatDateTime(row.last_used_at) : "—"}
      </td>
      <td className="py-2">
        {row.revoked_at ? (
          <span className="bg-danger text-danger-fg rounded px-2 py-0.5 text-xs">отозван</span>
        ) : (
          <span className="text-fg-muted">действует</span>
        )}
      </td>
    </tr>
  );
}

export function ApiKeysPage() {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), DEBOUNCE_MS);
  const list = useInfiniteQuery<
    AdminApiKeysPage,
    Error,
    InfiniteData<AdminApiKeysPage, string | null>,
    readonly ["admin", "api-keys", "list", string],
    string | null
  >({
    queryKey: ["admin", "api-keys", "list", q],
    queryFn: ({ pageParam }) => listApiKeys(params(q, pageParam)),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">API-ключи</h1>
      <label className="flex max-w-md flex-col gap-1 text-sm">
        Имя владельца
        <input
          type="search"
          value={text}
          maxLength={80}
          onChange={(e) => {
            setText(e.target.value);
          }}
          className="border-border bg-bg h-10 rounded-md border px-3 text-base"
        />
      </label>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && <p className="text-fg-muted">Ключей нет.</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="api-keys-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">Владелец</th>
                <th className="py-1 font-normal">Тариф</th>
                <th className="py-1 text-right font-normal">Заказы</th>
                <th className="py-1 text-right font-normal">Выручка</th>
                <th className="py-1 text-right font-normal">Себестоимость</th>
                <th className="py-1 font-normal">Был в сети</th>
                <th className="py-1 font-normal">Статус</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <KeyRow key={r.id} row={r} />
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
