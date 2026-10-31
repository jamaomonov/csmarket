/**
 * «Трейдер» with the traders already dealt with suggested under it: deals, profit, reverts.
 * Picking one hands the caller the trader (and so his last trade link).
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DESK_KEY, listTraders, type Trader } from "./api";
import { plural } from "./Parts";

import { Money } from "@/components/Money";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 250;
const SHOWN = 5;

interface TraderFieldProps {
  value: string;
  onChange: (v: string) => void;
  onPick: (t: Trader) => void;
}

export function TraderField({ value, onChange, onPick }: TraderFieldProps) {
  const [typing, setTyping] = useState(false);
  const q = useDebounced(value.trim(), DEBOUNCE_MS);
  const found = useQuery({
    queryKey: [...DESK_KEY, "traders", q],
    queryFn: () => listTraders(q),
    enabled: typing && q !== "",
  });
  const list = typing ? (found.data?.items ?? []).slice(0, SHOWN) : [];
  const exact = list.length === 1 && list[0]?.trader === value.trim();
  return (
    <div className="relative">
      <label className="flex flex-col gap-1 text-sm">
        Трейдер
        <input
          value={value}
          autoComplete="off"
          onChange={(e) => {
            setTyping(true);
            onChange(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setTyping(false);
          }}
          placeholder="Имя или ник в чате"
          className="border-border bg-bg h-11 rounded-md border px-3"
        />
      </label>
      {list.length > 0 && !exact && (
        <ul
          aria-label="Знакомые трейдеры"
          className="border-border bg-surface absolute inset-x-0 top-full z-30 mt-1 rounded-lg border p-1 shadow-[var(--shadow-menu)]"
        >
          {list.map((t) => (
            <li key={t.trader}>
              <button
                type="button"
                onClick={() => {
                  setTyping(false);
                  onPick(t);
                }}
                className="hover:bg-surface-2 flex min-h-11 w-full flex-col items-start rounded-md px-3 py-1 text-left text-sm"
              >
                <span className="font-medium">{t.trader}</span>
                <span className="text-fg-muted text-xs">
                  {plural(t.deals, ["сделка", "сделки", "сделок"])} · прибыль{" "}
                  <Money usd={t.profit_usd} signed />
                  {t.reverts > 0 && <span className="text-danger"> · откатов: {t.reverts}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
