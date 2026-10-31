/** Small shared pieces of «Мои сделки»: phone-sized targets, the two-way switches, words. */
import { Button, cn } from "@csmarket/ui";
import { Link } from "react-router-dom";

import { type Destination, type Method } from "./api";
import { deskErrorText, METHOD } from "./labels";

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
    <Pair
      group={`Куда: ${label}`}
      name={`dest-${label}`}
      options={[
        ["skinslink", "Skinslink"],
        ["stock", "Себе"],
      ]}
      value={value}
      onChange={onChange}
      disabled={disabled}
    />
  );
}

interface MethodSwitchProps {
  value: Method;
  onChange: (m: Method) => void;
}

/** How the deal was paid: напрямую | через гаранта. */
export function MethodSwitch({ value, onChange }: MethodSwitchProps) {
  return (
    <Pair
      group="Способ оплаты"
      name="method"
      options={[
        ["direct", METHOD.direct],
        ["guarantor", METHOD.guarantor],
      ]}
      value={value}
      onChange={onChange}
    />
  );
}

interface PairProps<T extends string> {
  group: string;
  name: string;
  options: readonly (readonly [T, string])[];
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
}

function Pair<T extends string>({
  group,
  name,
  options,
  value,
  onChange,
  disabled = false,
}: PairProps<T>) {
  return (
    <div role="radiogroup" aria-label={group} className="flex">
      {options.map(([d, word], n) => (
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
            name={name}
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

/** `n` with its Russian word: `plural(2, ["скин", "скина", "скинов"])` → «2 скина». */
export function plural(n: number, [one, few, many]: readonly [string, string, string]): string {
  const last = n % 10;
  const teen = n % 100 >= 11 && n % 100 <= 14;
  const word = last === 1 && !teen ? one : last >= 2 && last <= 4 && !teen ? few : many;
  return `${String(n)} ${word}`;
}

/** «1 скин», «2 скина», «5 скинов». */
export function skins(n: number): string {
  return plural(n, ["скин", "скина", "скинов"]);
}

/** Soʻm for a list row: `12 650 000` → «12,7 млн сум», `850 000` → «850 тыс. сум». */
export function compactUzs(value: string | number): string {
  const n = Number(value);
  const one = (x: number) => x.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
  if (Math.abs(n) >= 1_000_000) return `${one(n / 1_000_000)} млн сум`;
  if (Math.abs(n) >= 1_000) return `${one(n / 1_000)} тыс. сум`;
  return `${String(Math.round(n))} сум`;
}

/** Grey bars while a list loads. */
export function RowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <ul
      aria-busy="true"
      aria-label="Загружаем"
      className="divide-border border-border divide-y rounded-lg border"
    >
      {Array.from({ length: rows }, (_, n) => (
        <li key={n} className="flex items-center gap-3 px-3 py-3">
          <span className="bg-surface-2 h-9 w-12 shrink-0 animate-pulse rounded" />
          <span className="flex-1 space-y-2">
            <span className="bg-surface-2 block h-3 w-2/3 animate-pulse rounded" />
            <span className="bg-surface-2 block h-3 w-1/3 animate-pulse rounded" />
          </span>
        </li>
      ))}
    </ul>
  );
}

interface DeskErrorProps {
  error: unknown;
  onRetry: () => void;
  /** A way out under the retry («Мои сделки»). */
  back?: boolean;
}

/** A failed load: the reason in words, «Попробовать ещё раз» and the way back. */
export function DeskError({ error, onRetry, back = false }: DeskErrorProps) {
  return (
    <div role="alert" className="border-danger/40 space-y-3 rounded-lg border p-4">
      <p className="text-danger">{deskErrorText(error)}</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" className={TAP} onClick={onRetry}>
          Попробовать ещё раз
        </Button>
        {back && (
          <Link to="/desk" className="text-accent inline-flex min-h-11 items-center underline">
            Мои сделки
          </Link>
        )}
      </div>
    </div>
  );
}
