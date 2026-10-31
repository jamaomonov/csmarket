/** A trader's inventory as Skinslink prices it, dearest first: tick a skin by its whole row (or
 * «Выбрать все»); a ticked one gets its Skinslink | Себе switch. A long list gets a name filter. */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type Destination, type InventoryItem } from "./api";
import { DestinationSwitch, TAP, usdToUzs } from "./Parts";

import { Money } from "@/components/Money";
import { SkinThumb } from "@/components/SkinThumb";

export interface Picked {
  item: InventoryItem;
  destination: Destination;
}

interface InventoryPickerProps {
  items: InventoryItem[];
  picked: Record<string, Picked>;
  onChange: (next: Record<string, Picked>) => void;
  /** The CBU rate, for the soʻm in brackets; `null` hides them. */
  rate: string | null;
  /** Asset ids not to offer (already in the deal). */
  exclude?: ReadonlySet<string>;
}

const FILTER_FROM = 20;

export function InventoryPicker({
  items: all,
  picked,
  onChange,
  rate,
  exclude,
}: InventoryPickerProps) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const items = all
    .filter((i) => exclude?.has(i.asset_id) !== true)
    .sort((a, b) => Number(b.price_usd) - Number(a.price_usd));
  const shown = needle ? items.filter((i) => i.name.toLowerCase().includes(needle)) : items;
  const allPicked = shown.length > 0 && shown.every((i) => picked[i.asset_id] !== undefined);
  const pickAll = () => {
    if (allPicked) {
      const off = new Set(shown.map((i) => i.asset_id));
      onChange(Object.fromEntries(Object.entries(picked).filter(([k]) => !off.has(k))));
      return;
    }
    const next = { ...picked };
    for (const it of shown) next[it.asset_id] ??= { item: it, destination: "skinslink" };
    onChange(next);
  };
  const toggle = (it: InventoryItem) => {
    if (picked[it.asset_id]) {
      onChange(Object.fromEntries(Object.entries(picked).filter(([k]) => k !== it.asset_id)));
    } else {
      onChange({ ...picked, [it.asset_id]: { item: it, destination: "skinslink" } });
    }
  };
  if (items.length === 0) {
    return (
      <p className="text-fg-muted">
        {all.length > 0
          ? "Все скины из инвентаря уже в сделке."
          : "Skinslink сейчас ничего из этого инвентаря не берёт."}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {items.length > FILTER_FROM && (
        <label className="flex flex-col gap-1 text-sm">
          Найти в инвентаре
          <input
            type="search"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
            }}
            placeholder="Название скина"
            className="border-border bg-bg h-11 rounded-md border px-3"
          />
        </label>
      )}
      {shown.length > 1 && (
        <Button variant="secondary" className={TAP} onClick={pickAll}>
          {allPicked ? "Снять все" : "Выбрать все"}
        </Button>
      )}
      {needle && shown.length === 0 && (
        <p className="text-fg-muted">Ничего не нашли по «{q.trim()}».</p>
      )}
      <ul aria-label="Инвентарь трейдера" className="divide-border divide-y">
        {shown.map((it) => {
          const p = picked[it.asset_id];
          return (
            <li key={it.asset_id} className="py-1">
              <label className="hover:bg-surface-2 flex min-h-11 cursor-pointer items-center gap-3 rounded px-1">
                <input
                  type="checkbox"
                  className="accent-accent size-5 shrink-0"
                  aria-label={it.name}
                  checked={p !== undefined}
                  onChange={() => {
                    toggle(it);
                  }}
                />
                <SkinThumb url={it.image_url} />
                <span className="min-w-0 flex-1 truncate">{it.name}</span>
                <span className="text-right">
                  <Money usd={it.price_usd} />
                  <UzsNote usd={it.price_usd} rate={rate} />
                </span>
              </label>
              {p && (
                <div className="pb-2 pl-9">
                  <DestinationSwitch
                    label={it.name}
                    value={p.destination}
                    onChange={(destination) => {
                      onChange({ ...picked, [it.asset_id]: { item: it, destination } });
                    }}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** «(14 300 000 сум)» under a dollar price, at the CBU rate. */
export function UzsNote({ usd, rate }: { usd: string | number; rate: string | null }) {
  const uzs = usdToUzs(usd, rate);
  if (uzs === null) return null;
  return (
    <span className="text-fg-muted block text-xs">
      (<Money uzs={uzs} />)
    </span>
  );
}
