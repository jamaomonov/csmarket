/**
 * An editable list of two-field rows (a price range, a band, a markup) with add / remove: one
 * grid of three columns — the two fields and «×» — with the column names once above it, one row
 * per line on a phone too.
 */
import { Button } from "@csmarket/ui";
import { type ReactNode } from "react";

import { MoneyInput } from "@/components/MoneyInput";

export interface Column {
  /** The row's field this column edits. */
  field: string;
  label: string;
  /** A number with a unit («$», «%», «шт»); without one the column is text. */
  unit?: string;
  /** Whole numbers only (a numeric keyboard). */
  whole?: boolean;
  placeholder?: string;
}

interface RowsTableProps {
  title: string;
  hint?: ReactNode;
  columns: [Column, Column];
  rows: Record<string, string>[];
  addLabel: string;
  removeLabel: string;
  onChange: (rows: Record<string, string>[]) => void;
}

function Cell({
  col,
  value,
  onChange,
}: {
  col: Column;
  value: string;
  onChange: (v: string) => void;
}) {
  if (col.unit !== undefined) {
    return (
      <MoneyInput
        label={col.label}
        unit={col.unit}
        decimal={col.whole !== true}
        className="w-full"
        value={value}
        onChange={onChange}
      />
    );
  }
  return (
    <input
      aria-label={col.label}
      value={value}
      placeholder={col.placeholder}
      autoComplete="off"
      onChange={(e) => {
        onChange(e.target.value);
      }}
      className="border-border bg-bg h-10 w-full min-w-0 rounded-md border px-3 text-sm"
    />
  );
}

export function RowsTable({
  title,
  hint,
  columns,
  rows,
  addLabel,
  removeLabel,
  onChange,
}: RowsTableProps) {
  const set = (index: number, field: string, value: string): void => {
    onChange(rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  };
  return (
    <fieldset className="flex min-w-0 flex-col gap-2">
      <legend className="mb-1 text-sm font-semibold">{title}</legend>
      {hint !== undefined && <p className="text-fg-muted -mt-1 text-xs">{hint}</p>}
      <div className="grid grid-cols-[1fr_1fr_auto] items-center gap-2">
        {rows.length > 0 &&
          columns.map((col) => (
            <span key={col.field} aria-hidden className="text-fg-muted text-xs">
              {col.label}
            </span>
          ))}
        {rows.length > 0 && <span aria-hidden />}
        {rows.map((row, i) =>
          // Rows have no identity of their own: the position is the key while editing.
          [
            ...columns.map((col) => (
              <Cell
                key={`${String(i)}-${col.field}`}
                col={col}
                value={row[col.field] ?? ""}
                onChange={(v) => {
                  set(i, col.field, v);
                }}
              />
            )),
            <Button
              key={`${String(i)}-x`}
              type="button"
              variant="ghost"
              aria-label={removeLabel}
              className="size-10 px-0"
              onClick={() => {
                onChange(rows.filter((_, j) => j !== i));
              }}
            >
              ✕
            </Button>,
          ],
        )}
      </div>
      <div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => {
            onChange([...rows, Object.fromEntries(columns.map((c) => [c.field, ""]))]);
          }}
        >
          {addLabel}
        </Button>
      </div>
    </fieldset>
  );
}
