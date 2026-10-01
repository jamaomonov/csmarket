/** «Журнал»: what admins did, newest first. Read-only. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  type AuditPage as AuditPageData,
  type AuditRow,
  listAudit,
  type ListAuditParams,
} from "./api";
import {
  ACTION_LABELS,
  actionLabel,
  payloadLines,
  TARGET_TYPE_LABELS,
  targetPath,
  targetTypeLabel,
} from "./labels";

import { errorText } from "@/features/users/labels";
import { formatDateTime } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;

interface FilterSelectProps {
  label: string;
  value: string;
  labels: Readonly<Record<string, string>>;
  onChange: (value: string) => void;
}

function FilterSelect({ label, value, labels, onChange }: FilterSelectProps) {
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
        {Object.entries(labels).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}

function Target({ row }: { row: AuditRow }) {
  const path = targetPath(row.target_type, row.target_id);
  const inner = (
    <>
      {targetTypeLabel(row.target_type)} <span className="font-mono text-xs">{row.target_id}</span>
    </>
  );
  return path === null ? (
    <span>{inner}</span>
  ) : (
    <Link to={path} className="hover:underline">
      {inner}
    </Link>
  );
}

function AuditTableRow({ row }: { row: AuditRow }) {
  return (
    <tr className="border-border border-t align-top">
      <td className="text-fg-muted whitespace-nowrap py-2 pr-3">
        {formatDateTime(row.created_at)}
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${row.actor.id}`} className="hover:underline">
          {row.actor.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="py-2 pr-3" title={row.action}>
        {actionLabel(row.action)}
      </td>
      <td className="break-all py-2 pr-3">
        <Target row={row} />
      </td>
      <td className="py-2">
        <ul className="space-y-0.5">
          {payloadLines(row.payload).map((l) => (
            <li key={l.key}>{l.text}</li>
          ))}
        </ul>
      </td>
    </tr>
  );
}

export function AuditPage() {
  const url = useUrlParams();
  const action = url.get("action");
  const targetType = url.get("target_type");
  const targetId = url.get("target_id");

  const [idText, setIdText] = useState(targetId);
  const typedId = useDebounced(idText.trim(), DEBOUNCE_MS);
  const { set } = url;
  useEffect(() => {
    if (typedId !== targetId) set("target_id", typedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a settled edit writes the URL
  }, [typedId]);

  const list = useInfiniteQuery<
    AuditPageData,
    Error,
    InfiniteData<AuditPageData, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: ["admin", "audit", "list", action, targetType, targetId],
    queryFn: ({ pageParam }) => {
      const params: ListAuditParams = {
        ...(action !== "" && { action }),
        ...(targetType !== "" && { target_type: targetType }),
        ...(targetId !== "" && { target_id: targetId }),
        ...(pageParam !== null && { cursor: pageParam }),
      };
      return listAudit(params);
    },
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">Журнал</h1>
      <div className="flex flex-wrap items-end gap-4">
        <FilterSelect
          label="Действие"
          value={action}
          labels={ACTION_LABELS}
          onChange={(v) => {
            url.set("action", v);
          }}
        />
        <FilterSelect
          label="Тип цели"
          value={targetType}
          labels={TARGET_TYPE_LABELS}
          onChange={(v) => {
            url.set("target_type", v);
          }}
        />
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          Id цели
          <input
            type="search"
            value={idText}
            maxLength={64}
            onChange={(e) => {
              setIdText(e.target.value);
            }}
            className="border-border bg-bg h-10 rounded-md border px-3 font-mono text-base"
          />
        </label>
      </div>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && <p className="text-fg-muted">Записей нет.</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="audit-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">Когда</th>
                <th className="py-1 font-normal">Кто</th>
                <th className="py-1 font-normal">Действие</th>
                <th className="py-1 font-normal">Цель</th>
                <th className="py-1 font-normal">Данные</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <AuditTableRow key={r.id} row={r} />
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
