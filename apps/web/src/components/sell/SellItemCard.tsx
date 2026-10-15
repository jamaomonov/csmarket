"use client";

import { cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { rarityGlow } from "@csmarket/utils/skins";
import { Check } from "lucide-react";

import { nameParts, type SellItem } from "@/lib/sell";

interface SellItemCardProps {
  item: SellItem;
  locale: string;
  selected: boolean;
  onToggle: () => void;
}

const HEX = /^#[0-9a-f]{6}$/i;

/**
 * An item we buy now, built like the market's skin card (the art over a faint rarity wash,
 * a thin rarity line, wear and StatTrak™ as tags, weapon, skin, price) and a toggle: a
 * green frame and a ticked box when chosen.
 */
export function SellItemCard({ item, locale, selected, onToggle }: SellItemCardProps) {
  const parts = nameParts(item.name);
  const glow = rarityGlow(item.rarity_color);
  const rarity = item.rarity_color && HEX.test(item.rarity_color) ? item.rarity_color : null;
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      title={item.name}
      className={cn(
        "bg-surface group relative flex flex-col overflow-hidden rounded-lg border text-left transition-colors",
        "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
        selected
          ? "border-accent ring-accent/30 ring-1"
          : "border-border hover:border-border-strong hover:bg-surface-hover",
      )}
    >
      <span className="relative block aspect-[4/3] w-full">
        {glow ? (
          <span aria-hidden className="absolute inset-0" style={{ background: glow }} />
        ) : null}
        {item.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images, as on the catalogue cards
          <img
            src={item.image_url}
            alt=""
            loading="lazy"
            className="absolute inset-0 size-full object-contain p-4 transition duration-300 group-hover:scale-[1.04]"
          />
        ) : null}
        <span className="absolute inset-x-2.5 top-2.5 flex items-center gap-1">
          {item.exterior ? (
            <span className="text-fg-muted text-meta rounded-sm bg-black/40 px-1.5 py-px font-medium">
              {item.exterior}
            </span>
          ) : null}
          {parts.stattrak ? (
            <span className="text-stattrak text-meta rounded-sm bg-black/40 px-1.5 py-px font-semibold">
              ST™
            </span>
          ) : null}
          <span
            aria-hidden
            className={cn(
              "ml-auto grid size-5 place-items-center rounded-md border transition-colors",
              selected
                ? "bg-accent border-accent text-accent-fg"
                : "border-border-strong bg-black/30",
            )}
          >
            {selected ? <Check className="size-3.5" strokeWidth={3} /> : null}
          </span>
        </span>
        {rarity ? (
          <span
            aria-hidden
            className="absolute inset-x-0 bottom-0 h-0.5 opacity-80"
            style={{ backgroundColor: rarity }}
          />
        ) : null}
      </span>
      <span className="border-border flex flex-1 flex-col border-t px-3 pb-3 pt-2.5">
        <span className="text-fg-dim text-label truncate">{parts.weapon}</span>
        <span className="text-small truncate font-medium">{parts.skin}</span>
        <span className="text-body mt-auto pt-2 font-semibold">
          {formatUzs(locale, item.price_uzs)}
        </span>
      </span>
    </button>
  );
}
