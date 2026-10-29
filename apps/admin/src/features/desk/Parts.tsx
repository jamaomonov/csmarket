/** Small shared pieces of «Мои сделки»: phone-sized targets and the Skinslink | Себе switch. */
import { cn } from "@csmarket/ui";

import { type Destination } from "./api";

/** A button a thumb can hit on a phone (44 px), a normal one from `sm` up. */
export const TAP = "min-h-11 sm:min-h-10";

interface DestinationSwitchProps {
  /** Names the pair for a screen reader («AK-47 | Redline»). */
  label: string;
  value: Destination;
  onChange: (d: Destination) => void;
  disabled?: boolean;
}

/** Where a skin goes: two options, the chosen one filled — never a button naming the other. */
export function DestinationSwitch({
  label,
  value,
  onChange,
  disabled = false,
}: DestinationSwitchProps) {
  return (
    <div role="radiogroup" aria-label={`Куда: ${label}`} className="flex">
      {(
        [
          ["skinslink", "Skinslink"],
          ["stock", "Себе"],
        ] as const
      ).map(([d, word], n) => (
        <label
          key={d}
          className={cn(
            "border-border flex min-h-11 cursor-pointer items-center border px-3 text-sm sm:min-h-10",
            n === 0 ? "rounded-l-md" : "-ml-px rounded-r-md",
            value === d ? "bg-accent text-accent-fg border-accent" : "bg-bg",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          <input
            type="radio"
            className="sr-only"
            name={`dest-${label}`}
            checked={value === d}
            disabled={disabled}
            onChange={() => {
              onChange(d);
            }}
            aria-label={word}
          />
          {word}
        </label>
      ))}
    </div>
  );
}

/** `"12 650,5"` → `"12650.5"`. */
export function cleanAmount(raw: string): string {
  return raw.replace(/\s/g, "").replace(",", ".");
}

/** A rate or a sum for the eye: `12650.5` → `12 650,5`. */
export function grouped(value: string | number): string {
  return Number(value)
    .toLocaleString("ru-RU", { maximumFractionDigits: 4 })
    .replace(/\u00a0/g, " ");
}

/** Dollars in soʻm at the CBU rate, whole soʻm (for the eye only); `null` without a rate. */
export function usdToUzs(usd: string | number, rate: string | null | undefined): string | null {
  const r = Number(rate);
  if (!(r > 0)) return null;
  return String(Math.round(Number(usd) * r));
}
