/** An editable list of two-field rows (a bracket, a band, a markup) with add / remove. */
import { Button } from "@csmarket/ui";

export interface Column {
  /** The row's field this column edits. */
  field: string;
  label: string;
  inputMode?: "decimal" | "numeric" | "text";
}

interface RowsTableProps {
  title: string;
  columns: [Column, Column];
  rows: Record<string, string>[];
  addLabel: string;
  removeLabel: string;
  onChange: (rows: Record<string, string>[]) => void;
}

export function RowsTable({
  title,
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
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-semibold">{title}</legend>
      {rows.length > 0 && (
        <div aria-hidden className="text-fg-muted flex gap-2 text-xs">
          {columns.map((col) => (
            <span key={col.field} className="w-36">
              {col.label}
            </span>
          ))}
        </div>
      )}
      {rows.map((row, i) => (
        // Rows have no identity of their own: the position is the key while editing.
        <div key={i} className="flex items-end gap-2">
          {columns.map((col) => (
            <label key={col.field} className="flex flex-col gap-1 text-xs">
              <span className="sr-only">{col.label}</span>
              <input
                aria-label={col.label}
                inputMode={col.inputMode ?? "decimal"}
                value={row[col.field] ?? ""}
                placeholder={col.label}
                onChange={(e) => {
                  set(i, col.field, e.target.value);
                }}
                className="border-border bg-bg h-9 w-36 rounded-md border px-2 text-sm"
              />
            </label>
          ))}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={removeLabel}
            onClick={() => {
              onChange(rows.filter((_, j) => j !== i));
            }}
          >
            ✕
          </Button>
        </div>
      ))}
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
