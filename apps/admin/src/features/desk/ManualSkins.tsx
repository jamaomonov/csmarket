/**
 * Skins added from our catalogue, not the trader's inventory: they keep their picture, go to
 * «Себе» and take «оценка, $» — what Skinslink would give — so the price splits fairly.
 */
import { Button } from "@csmarket/ui";
import { useRef } from "react";

import { type NewItem } from "./api";
import { cleanAmount, TAP } from "./Parts";

import { MoneyInput } from "@/components/MoneyInput";
import { SkinThumb } from "@/components/SkinThumb";
import { findItems } from "@/features/catalogue/api";
import { SkinSearch } from "@/features/catalogue/SkinSearch";

export interface ManualSkin {
  key: string;
  name: string;
  image_url: string | null;
  /** Dollars as typed; empty when unknown. */
  estimate: string;
}

/** The API's items for the catalogue skins. */
export function manualItems(list: ManualSkin[]): NewItem[] {
  return list.map((m) => ({
    name: m.name,
    ...(m.image_url !== null && { image_url: m.image_url }),
    ...(Number(cleanAmount(m.estimate)) > 0 && { skinslink_usd: cleanAmount(m.estimate) }),
    destination: "stock" as const,
  }));
}

/** Their estimates, summed. */
export function manualSum(list: ManualSkin[]): number {
  return list.reduce((s, m) => s + (Number(cleanAmount(m.estimate)) || 0), 0);
}

interface ManualSkinsProps {
  value: ManualSkin[];
  onChange: (next: ManualSkin[]) => void;
}

export function ManualSkins({ value, onChange }: ManualSkinsProps) {
  const seq = useRef(0);
  return (
    <div className="space-y-2">
      <SkinSearch
        label="Скин из каталога"
        find={(q) => findItems({ q })}
        onPick={(i) => {
          seq.current += 1;
          onChange([
            ...value,
            { key: String(seq.current), name: i.name, image_url: i.image_url, estimate: "" },
          ]);
        }}
      />
      {value.length > 0 && (
        <ul className="divide-border divide-y text-sm" aria-label="Скины из каталога">
          {value.map((m) => (
            <li key={m.key} className="flex flex-wrap items-center gap-2 py-2">
              <SkinThumb url={m.image_url} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{m.name}</span>
                <span className="text-fg-muted text-xs">себе</span>
              </span>
              <MoneyInput
                label={`Оценка ${m.name}`}
                unit="$"
                decimal
                value={m.estimate}
                onChange={(estimate) => {
                  onChange(value.map((x) => (x.key === m.key ? { ...x, estimate } : x)));
                }}
                className="w-28"
              />
              <Button
                variant="secondary"
                className={TAP}
                onClick={() => {
                  onChange(value.filter((x) => x.key !== m.key));
                }}
              >
                Убрать
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-fg-muted text-xs">
        Оценка — сколько дал бы Skinslink; по ней делится цена.
      </p>
    </div>
  );
}
