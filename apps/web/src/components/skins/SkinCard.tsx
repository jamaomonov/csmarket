import { Badge } from "@csmarket/ui";
import { isVanilla, rarityGlow, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { useTranslations } from "next-intl";

import type { SkinItem } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";
import { displayPrice } from "@/lib/skins";

/**
 * One catalogue tile (design system, variant B): wear, StatTrak and the lot count on
 * top, the discount vs Steam as a badge, the art over a glow in its rarity colour,
 * weapon and skin, the price in green and how much dearer Steam is.
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
      className="bg-surface hover:bg-surface-hover hover:border-border focus-visible:ring-accent focus-visible:ring-offset-bg group relative flex h-full flex-col rounded-lg border border-transparent px-3 pb-3 pt-2.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
    >
      <div className="text-fg-dim flex items-center gap-1.5 text-[11px]">
        {item.exterior && <span>{item.exterior}</span>}
        {item.stattrak && <span className="text-stattrak font-semibold">ST™</span>}
        {item.souvenir && <span className="text-rarity-contraband font-semibold">SV</span>}
        <span className="ml-auto">{t("pieces", { count: item.count })}</span>
      </div>
      {discount !== null && <Badge className="absolute right-3 top-8 z-10">−{discount}%</Badge>}
      <div className="relative my-1 aspect-[4/3] w-full">
        {glow && <span aria-hidden className="absolute inset-0" style={{ background: glow }} />}
        {item.image_url && (
          <Image
            src={steamImageSize(item.image_url, "256fx256f")}
            alt={item.name}
            fill
            // A Steam CDN image already cut to size (256fx256f): the optimizer adds nothing.
            unoptimized
            sizes="(min-width: 1280px) 20vw, (min-width: 640px) 33vw, 50vw"
            className="object-contain p-2 transition duration-300 group-hover:scale-[1.04]"
          />
        )}
      </div>
      {item.weapon && <div className="text-fg-dim truncate text-[12px]">{item.weapon}</div>}
      <div className="truncate text-[13px] font-medium">
        {isVanilla(item) ? t("vanilla") : (item.skin ?? item.name)}
        {item.phase && <span className="text-fg-dim"> · {item.phase}</span>}
      </div>
      <div className="mt-auto pt-2">
        {price ? (
          <span className="text-accent num text-[14px] font-semibold">{price}</span>
        ) : (
          <span className="text-fg-dim text-[12px]">{t("soldOut")}</span>
        )}
        {discount !== null && (
          <p className="text-fg-dim mt-0.5 text-[11px]">
            {t("steamHigher", { percent: discount })}
          </p>
        )}
      </div>
    </Link>
  );
}
