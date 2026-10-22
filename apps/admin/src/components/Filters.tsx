/**
 * The filters row (admin UX audit §2): the main status is `Tabs` with counters above it; here a
 * search box in the normal font (a short placeholder, never cut) and secondary `FilterSelect`s.
 */
import { type ReactNode } from "react";

export function FiltersBar({ children }: { children: ReactNode }) {
  return <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{children}</div>;
}

interface SearchBoxProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  maxLength?: number;
}

export function SearchBox({ label, value, onChange, maxLength }: SearchBoxProps) {
  return (
    <input
      type="search"
      aria-label={label}
      placeholder={label}
      value={value}
      maxLength={maxLength}
      onChange={(e) => {
        onChange(e.target.value);
      }}
      className="border-border bg-bg h-11 w-full min-w-0 rounded-md border px-3 text-sm sm:w-80 md:h-9"
    />
  );
}

interface FilterSelectProps<T extends string> {
  label: string;
  value: string;
  options: readonly T[];
  text: (option: T) => string;
  onChange: (value: string) => void;
}

/**
 * «<label>: все» — the label is the empty option, so the select needs no caption above it. On a
 * phone the selects share one row (each shrinks); the search box above takes the full width.
 */
export function FilterSelect<T extends string>({
  label,
  value,
  options,
  text,
  onChange,
}: FilterSelectProps<T>) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
      }}
      className={`border-border bg-bg h-11 min-w-0 flex-1 rounded-md border px-2 text-sm sm:flex-none md:h-9 ${
        value !== "" ? "text-fg" : "text-fg-muted"
      }`}
    >
      <option value="">{label}: все</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {text(o)}
        </option>
      ))}
    </select>
  );
}
