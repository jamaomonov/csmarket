/** The filters row (review §4.6): a compact search box and selects, one line on desktop. */
import { type ReactNode } from "react";

export function FiltersBar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2">{children}</div>;
}

interface SearchBoxProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  maxLength?: number;
  mono?: boolean;
}

export function SearchBox({ label, value, onChange, maxLength, mono }: SearchBoxProps) {
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
      className={`border-border bg-bg h-9 w-full rounded-md border px-3 text-sm sm:w-72 ${
        mono === true ? "font-mono" : ""
      }`}
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

/** «<label>: все» — the label is the empty option, so the select needs no caption above it. */
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
      className={`border-border bg-bg h-9 rounded-md border px-2 text-sm ${
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
