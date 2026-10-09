/**
 * The admin's list table (review §4.1): padded cells, right-aligned tabular numbers, a hover
 * row, a red left bar for rows needing an operator, loading / empty / error states, a footer,
 * and cards instead of the table on a narrow screen when `mobileCard` is given.
 */
import { type ReactNode } from "react";

import { EmptyState } from "./EmptyState";

import { useNarrow } from "@/lib/useNarrow";

export interface Column<R> {
  key: string;
  header: ReactNode;
  align?: "left" | "right";
  /** A Tailwind width class (`w-32`). */
  width?: string;
  cell: (row: R) => ReactNode;
}

interface DataTableProps<R> {
  columns: Column<R>[];
  rows: R[] | undefined;
  rowKey: (row: R) => string;
  label: string;
  loading?: boolean;
  error?: ReactNode;
  empty?: ReactNode;
  footer?: ReactNode;
  onRowClick?: (row: R) => void;
  attention?: (row: R) => boolean;
  mobileCard?: (row: R) => ReactNode;
  /** Rendered under a row (an expanded row), full width. */
  below?: (row: R) => ReactNode;
}

const SKELETON_ROWS = 5;

export function DataTable<R>({
  columns,
  rows,
  rowKey,
  label,
  loading = false,
  error,
  empty = "Ничего не найдено.",
  footer,
  onRowClick,
  attention,
  mobileCard,
  below,
}: DataTableProps<R>) {
  const narrow = useNarrow();
  if (error !== undefined && error !== null && error !== false) {
    return <EmptyState tone="danger">{error}</EmptyState>;
  }
  const list = rows ?? [];
  const showSkeleton = loading && list.length === 0;
  if (!showSkeleton && list.length === 0) return <EmptyState>{empty}</EmptyState>;

  const table = (
    <div
      className={mobileCard !== undefined ? "hidden overflow-x-auto md:block" : "overflow-x-auto"}
    >
      <table aria-label={label} className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-border text-fg-muted border-b text-xs">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`whitespace-nowrap px-3 py-2 font-normal ${
                  c.align === "right" ? "text-right" : "text-left"
                } ${c.width ?? ""}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {showSkeleton
            ? Array.from({ length: SKELETON_ROWS }, (_, i) => (
                <tr key={`sk-${String(i)}`} className="border-border border-b">
                  {columns.map((c) => (
                    <td key={c.key} className="px-3 py-3">
                      <span className="bg-surface-2 block h-3 w-full max-w-24 animate-pulse rounded" />
                    </td>
                  ))}
                </tr>
              ))
            : list.map((row) => {
                const flagged = attention?.(row) ?? false;
                const extra = below?.(row);
                return (
                  <TableRow
                    key={rowKey(row)}
                    row={row}
                    columns={columns}
                    flagged={flagged}
                    onRowClick={onRowClick}
                    extra={extra}
                  />
                );
              })}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="space-y-2">
      {(mobileCard === undefined || !narrow || showSkeleton) && table}
      {mobileCard !== undefined && narrow && !showSkeleton && (
        <ul aria-label={label} className="space-y-2">
          {list.map((row) => (
            <li
              key={rowKey(row)}
              className={`border-border bg-surface rounded-lg border p-3 ${
                attention?.(row) === true ? "border-l-danger border-l-[3px]" : ""
              } ${onRowClick !== undefined ? "cursor-pointer" : ""}`}
              onClick={
                onRowClick === undefined
                  ? undefined
                  : () => {
                      onRowClick(row);
                    }
              }
            >
              {mobileCard(row)}
            </li>
          ))}
        </ul>
      )}
      {footer !== undefined && <div className="text-fg-muted px-1 text-sm">{footer}</div>}
    </div>
  );
}

interface TableRowProps<R> {
  row: R;
  columns: Column<R>[];
  flagged: boolean;
  onRowClick: ((row: R) => void) | undefined;
  extra: ReactNode;
}

function TableRow<R>({ row, columns, flagged, onRowClick, extra }: TableRowProps<R>) {
  return (
    <>
      <tr
        className={`border-border hover:bg-surface-hover border-b align-top ${
          onRowClick !== undefined ? "cursor-pointer" : ""
        }`}
        onClick={
          onRowClick === undefined
            ? undefined
            : (e) => {
                // A link or a button inside the row does its own thing. `target` of a click on a
                // table row is always an element (DOM narrowing).
                if ((e.target as HTMLElement).closest("a,button,input,select,textarea")) return;
                onRowClick(row);
              }
        }
      >
        {columns.map((c, i) => (
          <td
            key={c.key}
            className={`px-3 py-2.5 ${c.align === "right" ? "text-right tabular-nums" : ""} ${
              i === 0 && flagged ? "shadow-[inset_3px_0_0_var(--color-danger)]" : ""
            }`}
          >
            {c.cell(row)}
          </td>
        ))}
      </tr>
      {extra !== undefined && extra !== null && extra !== false && (
        <tr className="border-border bg-surface/60 border-b">
          <td colSpan={columns.length} className="px-3 py-3">
            {extra}
          </td>
        </tr>
      )}
    </>
  );
}
