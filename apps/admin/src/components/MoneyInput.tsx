/**
 * A money field (admin UX audit §5): `inputMode="numeric"` (or `decimal` for dollars), the digits
 * grouped as typed («2 000 000») and the unit on the right. The value it hands back is exactly
 * what was typed minus the group spaces — `"2000000"`, never a number — so a form sends the API
 * the same string it sent before; the form keeps its own validation.
 */
import { type ReactNode, useLayoutEffect, useRef } from "react";

/** A no-break space: a sum never wraps between its groups. */
const GROUP = " ";
const PLAIN = /^(-?)(\d+)(\.\d*)?$/;

/** `"2000000"` -> `"2 000 000"`, `"-1500.25"` -> `"-1 500.25"`; anything else as it is. */
export function groupDigits(raw: string): string {
  const m = PLAIN.exec(raw);
  if (m === null) return raw;
  const [, sign = "", whole = "", frac = ""] = m;
  return `${sign}${whole.replace(/\B(?=(\d{3})+$)/g, GROUP)}${frac}`;
}

/** What the field holds without the group spaces (and any space typed or pasted). */
export function ungroup(text: string): string {
  return text.replace(/\s/g, "");
}

/** Where the caret goes in `shown` so that `kept` non-space characters stand before it. */
function caretAfter(shown: string, kept: number): number {
  let seen = 0;
  for (let i = 0; i < shown.length; i += 1) {
    if (seen === kept) return i;
    if (!/\s/.test(shown.charAt(i))) seen += 1;
  }
  return shown.length;
}

interface MoneyInputProps {
  /** What the sum is («Минимум на карту»); the accessible name is «<label>, <unit>». */
  label: string;
  /** The raw value: digits (a sign, a dot), no spaces. */
  value: string;
  onChange: (raw: string) => void;
  /** «сум», «$» (or «%», «ч» for a plain number with a unit): inside the field on the right. */
  unit: string;
  /** Dollars take a decimal keyboard; whole soʻm a numeric one. */
  decimal?: boolean;
  maxLength?: number;
  className?: string;
  id?: string;
}

export function MoneyInput({
  label,
  value,
  onChange,
  unit,
  decimal = false,
  maxLength,
  className = "w-full sm:w-44",
  id,
}: MoneyInputProps) {
  const input = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  const shown = groupDigits(value);
  useLayoutEffect(() => {
    const el = input.current;
    if (el === null || caret.current === null || document.activeElement !== el) return;
    const at = caretAfter(shown, caret.current);
    el.setSelectionRange(at, at);
    caret.current = null;
  }, [shown]);
  return (
    <span
      className={`border-border bg-bg focus-within:border-accent focus-within:ring-accent/30 flex h-10 min-w-0 items-center rounded-md border focus-within:ring-2 ${className}`}
    >
      <input
        ref={input}
        id={id}
        aria-label={`${label}, ${unit}`}
        inputMode={decimal ? "decimal" : "numeric"}
        autoComplete="off"
        value={shown}
        maxLength={maxLength}
        onChange={(e) => {
          const text = e.target.value;
          const at = e.target.selectionStart ?? text.length;
          caret.current = ungroup(text.slice(0, at)).length;
          onChange(ungroup(text));
        }}
        className="h-full min-w-0 flex-1 bg-transparent px-2 text-right tabular-nums outline-none sm:px-3"
      />
      <span aria-hidden className="text-fg-muted pr-2 text-sm sm:pr-3">
        {unit}
      </span>
    </span>
  );
}

interface MoneyFieldProps extends MoneyInputProps {
  /** A muted line under the field. */
  hint?: ReactNode;
}

/** A `MoneyInput` with its label above it (and an optional hint under it). */
export function MoneyField({ hint, className = "w-full", ...props }: MoneyFieldProps) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      {props.label}
      <MoneyInput {...props} className={className} />
      {hint !== undefined && <span className="text-fg-muted text-xs">{hint}</span>}
    </label>
  );
}
