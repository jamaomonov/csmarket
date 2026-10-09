/** Underlined tabs with counters (review §4.7); `segmented` for a period switch. */
import { type ReactNode } from "react";

export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
  count?: number;
  /** Paints the counter red (things waiting for an operator). */
  alert?: boolean;
}

interface TabsProps<K extends string> {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  variant?: "underline" | "segmented";
}

export function Tabs<K extends string>({
  items,
  value,
  onChange,
  label,
  variant = "underline",
}: TabsProps<K>) {
  if (variant === "segmented") {
    return (
      <div role="tablist" aria-label={label} className="bg-surface inline-flex rounded-md p-0.5">
        {items.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={t.key === value}
            onClick={() => {
              onChange(t.key);
            }}
            className={`rounded px-3 py-1 text-sm ${
              t.key === value ? "bg-surface-2 text-fg font-medium" : "text-fg-muted hover:text-fg"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div
      role="tablist"
      aria-label={label}
      className="border-border -mb-px flex gap-1 overflow-x-auto border-b"
    >
      {items.map((t) => {
        const active = t.key === value;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => {
              onChange(t.key);
            }}
            className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm ${
              active
                ? "border-accent text-fg font-medium"
                : "text-fg-muted hover:text-fg border-transparent"
            }`}
          >
            {t.label}
            {t.count !== undefined && (
              <span
                className={`rounded-full px-1.5 text-xs tabular-nums ${
                  t.alert === true && t.count > 0
                    ? "bg-danger/15 text-danger"
                    : "bg-surface-2 text-fg-muted"
                }`}
              >
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
