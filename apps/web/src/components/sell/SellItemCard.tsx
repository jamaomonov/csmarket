"use client";

import { cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { Check } from "lucide-react";

import { nameParts, type SellItem } from "@/lib/sell";

interface SellItemCardProps {
  item: SellItem;
  locale: string;
  selected: boolean;
  onToggle: () => void;
}

/** An item we buy now: a toggle (an accent frame and a tick when chosen). */
export function SellItemCard({ item, locale, selected, onToggle }: SellItemCardProps) {
  const parts = nameParts(item.name);
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      title={item.name}
      className={cn(
        "bg-surface group relative flex flex-col rounded-xl border-2 p-3 text-left transition-colors",
        "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
        selected ? "border-accent" : "hover:border-border-strong border-transparent",
      )}
    >
      <span className="text-fg-dim flex items-center gap-1.5 text-[11px] font-semibold">
        {item.exterior}
        {parts.stattrak ? <span className="text-stattrak">ST™</span> : null}
      </span>
      <span
        aria-hidden
        className={cn(
          "absolute right-2.5 top-2.5 grid size-5 place-items-center rounded-md border",
          selected ? "bg-accent border-accent text-accent-fg" : "border-border-strong",
        )}
      >
        {selected ? <Check className="size-3.5" strokeWidth={3} /> : null}
      </span>
      <span className="relative my-2 grid h-24 place-items-center">
        {item.rarity_color ? (
          <span
            aria-hidden
            className="absolute inset-x-4 bottom-1 h-10 rounded-full opacity-30 blur-xl"
            style={{ background: item.rarity_color }}
          />
        ) : null}
        {item.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images, as on the catalogue cards
          <img src={item.image_url} alt="" loading="lazy" className="relative max-h-24 w-auto" />
        ) : null}
      </span>
      <span className="text-fg-dim truncate text-xs">{parts.weapon}</span>
      <span className="truncate text-[13px] font-medium">{parts.skin}</span>
      <span className="text-accent num mt-1.5 text-sm font-semibold">
        {formatUzs(locale, item.price_uzs)}
      </span>
    </button>
  );
}
