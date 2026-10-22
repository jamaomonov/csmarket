/**
 * «Журнал»: what admins did, newest first and grouped by day («Сегодня», «Вчера», «12 октября»),
 * filtered by one row of `FilterSelect`s; on a phone each entry is a card, not a squeezed row. Targets read
 * by name (the API's `target_label`), never by UUID; actions and payload keys in words. Read-only.
 */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

import {
  type AuditPage as AuditPageData,
  type AuditRow,
  listAudit,
  type ListAuditParams,
} from "./api";
import {
  ACTION_LABELS,
  actionWord,
  payloadLines,
  TARGET_TYPE_LABELS,
  targetPath,
  targetTypeLabel,
} from "./labels";

import { FilterSelect, FiltersBar, SearchBox } from "@/components/Filters";
import { PageHeader } from "@/components/PageHeader";
import { TextLink } from "@/components/TextLink";
import { errorText } from "@/features/users/labels";
import { clockTime, dayHeading, dayKey, formatDateTime } from "@/lib/format";
import { pick, upTo } from "@/lib/url-guards";
import { useDebounced } from "@/lib/useDebounced";
import { useNarrow } from "@/lib/useNarrow";
import { useUrlParams } from "@/lib/useUrlParams";

const DEBOUNCE_MS = 300;
/** The API's `target_id` ceiling (and the input's `maxLength`). */
const TARGET_ID_MAX = 64;
const ACTIONS = Object.keys(ACTION_LABELS);
const TARGET_TYPES = Object.keys(TARGET_TYPE_LABELS);

/** Targets whose id is already readable: an order or sale number, an alias. */
const READABLE_IDS: ReadonlySet<string> = new Set(["order", "sale", "skin_alias"]);

/** A target's name: the API's label, a readable id, a hold's payment number — never a UUID. */
function targetName(row: AuditRow): ReactNode {
  if (row.target_label) return row.target_label;
  if (READABLE_IDS.has(row.target_type)) return <span className="font-mono">{row.target_id}</span>;
  const number = row.payload.number;
  if (row.target_type === "payment_hold" && typeof number === "string") {
    return <span className="font-mono">{number}</span>;
  }
  return null;
}

function Target({ row }: { row: AuditRow }) {
  const path = targetPath(row.target_type, row.target_id);
  const name = targetName(row);
  const type = targetTypeLabel(row.target_type);
  const inner =
    name === null ? (
      type
    ) : (
      <>
        <span className="text-fg-muted">{type}</span> {name}
      </>
    );
  return path === null ? <span>{inner}</span> : <TextLink to={path}>{inner}</TextLink>;
}

function Action({ action }: { action: string }) {
  const a = actionWord(action);
  return (
    <>
      {a.word}
      {a.unknown !== null && (
        <>
          {" "}
          <span className="text-fg-dim text-meta">{a.unknown}</span>
        </>
      )}
    </>
  );
}

function Payload({ row }: { row: AuditRow }) {
  const lines = payloadLines(row.payload, row.target_type === "payment_hold" ? ["number"] : []);
  if (lines.length === 0) return null;
  return (
    <ul className="space-y-0.5 break-words">
      {lines.map((l) => (
        <li key={l.key}>
          {l.label ?? <span className="text-fg-dim text-meta">{l.key}</span>}: {l.text}
        </li>
      ))}
    </ul>
  );
}

/** The row's time under its day heading: `HH:MM`, the full date in the tooltip. */
function Clock({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} title={formatDateTime(iso)} className="whitespace-nowrap tabular-nums">
      {clockTime(iso)}
    </time>
  );
}

function Actor({ row }: { row: AuditRow }) {
  return <TextLink to={`/users/${row.actor.id}`}>{row.actor.display_name ?? "Без имени"}</TextLink>;
}

function AuditTableRow({ row }: { row: AuditRow }) {
  return (
    <tr className="border-border border-t align-top">
      <td className="text-fg-muted w-16 py-2 pr-3">
        <Clock iso={row.created_at} />
      </td>
      <td className="py-2 pr-3">
        <Actor row={row} />
      </td>
      <td className="py-2 pr-3">
        <Action action={row.action} />
      </td>
      <td className="py-2 pr-3">
        <Target row={row} />
      </td>
      <td className="py-2">
        <Payload row={row} />
      </td>
    </tr>
  );
}

/** A phone's row: a card that reads as a sentence, so nothing is squeezed into a narrow cell. */
function AuditCard({ row }: { row: AuditRow }) {
  return (
    <li className="space-y-1 px-3 py-2.5 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="text-fg-muted">
          <Clock iso={row.created_at} />
        </span>
        <span className="min-w-0 break-words font-medium">
          <Action action={row.action} />
        </span>
      </div>
      <div className="min-w-0 break-words">
        <Actor row={row} /> <span className="text-fg-muted">·</span> <Target row={row} />
      </div>
      <div className="text-fg-muted">
        <Payload row={row} />
      </div>
    </li>
  );
}

interface Day {
  key: string;
  heading: string;
  rows: AuditRow[];
}

/** Rows (newest first) grouped by the viewer's local day. */
function byDay(rows: AuditRow[]): Day[] {
  const days: Day[] = [];
  for (const row of rows) {
    const key = dayKey(row.created_at);
    const last = days.at(-1);
    if (last?.key === key) last.rows.push(row);
    else days.push({ key, heading: dayHeading(row.created_at), rows: [row] });
  }
  return days;
}

function AuditList({ rows }: { rows: AuditRow[] }) {
  const narrow = useNarrow();
  const days = byDay(rows);
  if (narrow) {
    return (
      <div className="space-y-4" data-testid="audit-table">
        {days.map((d) => (
          <section key={d.key} aria-label={d.heading}>
            <h2 className="text-fg-muted mb-1 text-sm font-semibold">{d.heading}</h2>
            <ul className="border-border bg-surface divide-border divide-y rounded-lg border">
              {d.rows.map((r) => (
                <AuditCard key={r.id} row={r} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" data-testid="audit-table">
        <thead className="text-fg-muted">
          <tr>
            <th className="py-1 font-normal">Время</th>
            <th className="py-1 font-normal">Кто</th>
            <th className="py-1 font-normal">Действие</th>
            <th className="py-1 font-normal">Цель</th>
            <th className="py-1 font-normal">Данные</th>
          </tr>
        </thead>
        {days.map((d) => (
          <tbody key={d.key}>
            <tr>
              <th colSpan={5} scope="colgroup" className="pb-1 pt-4 text-sm font-semibold">
                {d.heading}
              </th>
            </tr>
            {d.rows.map((r) => (
              <AuditTableRow key={r.id} row={r} />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

export function AuditPage() {
  const url = useUrlParams();
  // A hand-edited URL never reaches the API: unknown options and over-long ids are dropped.
  const action = pick(ACTIONS, url.get("action")) ?? "";
  const targetType = pick(TARGET_TYPES, url.get("target_type")) ?? "";
  const targetId = upTo(url.get("target_id"), TARGET_ID_MAX);

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
    <section className="space-y-4">
      <PageHeader title="Журнал" />
      <FiltersBar>
        <SearchBox label="Id цели" value={idText} maxLength={TARGET_ID_MAX} onChange={setIdText} />
        <FilterSelect
          label="Действие"
          value={action}
          options={ACTIONS}
          text={(k) => ACTION_LABELS[k] ?? k}
          onChange={(v) => {
            url.set("action", v);
          }}
        />
        <FilterSelect
          label="Тип цели"
          value={targetType}
          options={TARGET_TYPES}
          text={(k) => TARGET_TYPE_LABELS[k] ?? k}
          onChange={(v) => {
            url.set("target_type", v);
          }}
        />
      </FiltersBar>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && <p className="text-fg-muted">Записей нет.</p>}
      {rows.length > 0 && <AuditList rows={rows} />}
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
