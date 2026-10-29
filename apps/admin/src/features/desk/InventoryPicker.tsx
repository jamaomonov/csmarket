/** A trader's inventory as Skinslink prices it: tick a skin by its whole row; a ticked one
 * gets its Skinslink | Себе switch. A long list gets a name filter. */
import { useState } from "react";

import { type Destination, type InventoryItem } from "./api";
import { DestinationSwitch, usdToUzs } from "./Parts";

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
}

const FILTER_FROM = 20;

export function InventoryPicker({ items, picked, onChange, rate }: InventoryPickerProps) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const shown = needle ? items.filter((i) => i.name.toLowerCase().includes(needle)) : items;
  const toggle = (it: InventoryItem) => {
    if (picked[it.asset_id]) {
      onChange(Object.fromEntries(Object.entries(picked).filter(([k]) => k !== it.asset_id)));
    } else {
      onChange({ ...picked, [it.asset_id]: { item: it, destination: "skinslink" } });
    }
  };
  if (items.length === 0) {
    return <p className="text-fg-muted">Skinslink сейчас ничего из этого инвентаря не берёт.</p>;
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
