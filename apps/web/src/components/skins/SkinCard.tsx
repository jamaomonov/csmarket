import { isVanilla, rarityGlow, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { useTranslations } from "next-intl";

import type { SkinItem } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";
import { displayPrice } from "@/lib/skins";

/**
 * One catalogue tile: art, skin and weapon, wear, discount vs
 * Steam, price in soʻm. The rarity colour runs along the bottom edge — the
 * way the game and every CS2 market mark rarity, so it reads at a glance.
 *
 * No `"use client"`: rendered inside the server grid on `/`.
 */
export function SkinCard({ item, locale }: { item: SkinItem; locale: string }) {
  const t = useTranslations("web.skins");
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const glow = rarityGlow(item.rarity_color);
  // Under 5 % a badge on every other card only dilutes the ones that matter.
  const discount =
    item.discount_percent !== null && item.discount_percent >= 5 ? item.discount_percent : null;

  return (
    <Link
      href={itemPath(item.slug)}
      className="border-border bg-surface hover:border-border-strong group flex h-full flex-col overflow-hidden rounded-xl border transition hover:-translate-y-1"
    >
      <div className="bg-surface-2 relative aspect-[4/3] w-full overflow-hidden">
        {glow && (
          <span
            aria-hidden
            className="absolute inset-0 opacity-80 transition duration-500 group-hover:scale-110 group-hover:opacity-100"
            style={{ background: glow }}
          />
        )}
        {item.image_url && (
          <Image
            src={steamImageSize(item.image_url, "256fx256f")}
            alt={item.name}
            fill
            // A Steam CDN image already cut to size (256fx256f): the optimizer adds nothing.
            unoptimized
            sizes="(min-width: 1280px) 20vw, (min-width: 768px) 33vw, 50vw"
            className="object-contain p-3 transition duration-500 group-hover:scale-[1.05]"
          />
        )}
        {discount !== null && (
          <span className="bg-accent text-accent-fg absolute right-2 top-2 rounded-full px-2 py-0.5 text-[11px] font-bold">
            −{discount}%
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-0.5 p-3">
        <div className="text-fg-dim/80 flex items-center gap-1.5 text-[11px]">
          {item.stattrak && <span className="font-semibold text-orange-400">StatTrak™</span>}
          {item.souvenir && <span className="font-semibold text-yellow-400">Souvenir</span>}
          {item.weapon && <span className="truncate">{item.weapon}</span>}
          {item.exterior && (
            <span className="border-border ml-auto rounded border px-1 font-mono">
              {item.exterior}
            </span>
          )}
        </div>
        <div className="line-clamp-2 text-[13px] font-semibold leading-snug">
          {isVanilla(item) ? t("vanilla") : (item.skin ?? item.name)}
          {item.phase && <span className="text-fg-dim font-normal"> · {item.phase}</span>}
        </div>
        <div className="mt-auto pt-1.5 text-[14px] font-bold tabular-nums">
          {price ?? <span className="text-fg-dim font-sans text-[12px]">{t("soldOut")}</span>}
        </div>
      </div>
    </Link>
  );
}
