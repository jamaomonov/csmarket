/** Money as the admin shows it: digit groups, `$` in front, a typographic minus (review §4.3). */
import { formatSum } from "@/lib/format";

/** `"1.1"` -> `$1.10`; `digits` 3 only for the USD wallet. */
export function formatMoneyUsd(value: string | number, digits = 2): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return `$${String(value)}`;
  const abs = Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${n < 0 ? "−" : ""}$${abs.replace(/,/g, " ")}`;
}

interface MoneyProps {
  uzs?: string | number;
  usd?: string | number;
  digits?: number;
  /** Shows a leading `+` on positive amounts and colours a negative one. */
  signed?: boolean;
  className?: string;
  title?: string;
}

export function Money({ uzs, usd, digits = 2, signed = false, className = "", title }: MoneyProps) {
  const raw = uzs ?? usd ?? 0;
  const negative = Number(raw) < 0;
  let text: string;
  if (uzs !== undefined) {
    text = formatSum(String(uzs).replace(/^-/, ""));
    if (negative) text = `−${text}`;
  } else {
    text = formatMoneyUsd(usd ?? 0, digits);
  }
  if (signed && !negative && Number(raw) > 0) text = `+${text}`;
  return (
    <span
      title={title}
      className={`whitespace-nowrap tabular-nums ${negative ? "text-danger" : ""} ${className}`}
    >
      {text}
    </span>
  );
}
