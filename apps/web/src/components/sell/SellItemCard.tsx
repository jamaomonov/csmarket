"use client";

import { cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { Check, Lock } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import type { SellItem } from "@/lib/sell";

interface SellItemCardProps {
  item: SellItem;
  locale: string;
  selected: boolean;
  onToggle: () => void;
}

/** An inventory item: a toggle (green frame and a tick when chosen), dimmed when not sellable. */
export function SellItemCard({ item, locale, selected, onToggle }: SellItemCardProps) {
  const t = useTranslations("web.sell");
  const format = useFormatter();
  const off = item.unavailable;
  const why =
    off === null
      ? null
      : off.reason === "tradeLock"
        ? t("unavailable.tradeLock", {
            date: format.dateTime(new Date(off.until), { day: "numeric", month: "short" }),
          })
        : t(`unavailable.${off.reason}`);
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={off !== null}
      aria-pressed={selected}
      title={item.name}
      className={cn(
        "bg-surface group relative flex flex-col rounded-xl border-2 p-3 text-left transition-colors",
        "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
        selected ? "border-accent" : "hover:border-border-strong border-transparent",
        off !== null && "cursor-not-allowed opacity-60",
      )}
    >
      <span className="text-fg-dim flex items-center gap-1.5 text-[11px] font-semibold">
        {item.exterior}
        {item.stattrak ? <span className="text-stattrak">ST™</span> : null}
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
        {item.rarityColor ? (
          <span
            aria-hidden
            className="absolute inset-x-4 bottom-1 h-10 rounded-full opacity-30 blur-xl"
            style={{ background: item.rarityColor }}
          />
        ) : null}
        {/* eslint-disable-next-line @next/next/no-img-element -- Steam CDN images, as on the catalogue cards */}
        <img src={item.imageUrl} alt="" loading="lazy" className="relative max-h-24 w-auto" />
      </span>
      {why ? (
        <span className="bg-warning/15 text-warning mb-1.5 flex items-center gap-1.5 self-start rounded-md px-2 py-0.5 text-[11px] font-semibold">
          <Lock className="size-3" aria-hidden />
          {why}
        </span>
      ) : null}
      <span className="text-fg-dim truncate text-xs">{item.weapon}</span>
      <span className="truncate text-[13px] font-medium">{item.skin ?? item.name}</span>
      <span className="text-accent num mt-1.5 text-sm font-semibold">
        {formatUzs(locale, item.priceUzs)}
      </span>
    </button>
  );
}
