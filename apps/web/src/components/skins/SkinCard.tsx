import { isVanilla, rarityGlow, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { useTranslations } from "next-intl";

import type { SkinItem } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";
import { displayPrice } from "@/lib/skins";

/**
 * One catalogue tile: the art over a faint wash of its rarity with a thin rarity line
 * under it, wear / StatTrak / Souvenir as small tags, the discount vs Steam, weapon and
 * skin, then the price and the lot count on one line.
 *
 * No `"use client"`: rendered inside the server grid on `/`.
 */
interface SkinCardProps {
  item: SkinItem;
  locale: string;
  /** Load the picture eagerly, with high priority: the first row, likely the page's LCP. */
  priority?: boolean;
}

const HEX = /^#[0-9a-f]{6}$/i;

export function SkinCard({ item, locale, priority = false }: SkinCardProps) {
  const t = useTranslations("web.skins");
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const glow = rarityGlow(item.rarity_color);
  const rarity = item.rarity_color && HEX.test(item.rarity_color) ? item.rarity_color : null;
  // Under 5 % a badge on every other card only dilutes the ones that matter.
  const discount =
    item.discount_percent !== null && item.discount_percent >= 5 ? item.discount_percent : null;

  return (
    <Link
      href={itemPath(item.slug)}
      className="bg-surface border-border hover:border-border-strong hover:bg-surface-hover focus-visible:ring-accent focus-visible:ring-offset-bg group relative flex h-full flex-col overflow-hidden rounded-lg border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
    >
      <div className="relative aspect-[4/3] w-full">
        {glow && <span aria-hidden className="absolute inset-0" style={{ background: glow }} />}
        {item.image_url && (
          <Image
            src={steamImageSize(item.image_url, "256fx256f")}
            alt={item.name}
            fill
            priority={priority}
            // A Steam CDN image already cut to size (256fx256f): the optimizer adds nothing.
            unoptimized
            sizes="(min-width: 1280px) 20vw, (min-width: 640px) 33vw, 50vw"
            className="object-contain p-4 transition duration-300 group-hover:scale-[1.04]"
          />
        )}
        <div className="absolute inset-x-2.5 top-2.5 flex items-center gap-1">
          {item.exterior && (
            <span className="bg-bg/70 text-fg-muted text-meta rounded-sm px-1.5 py-px font-medium">
              {item.exterior}
            </span>
          )}
          {item.stattrak && (
            <span className="bg-bg/70 text-stattrak text-meta rounded-sm px-1.5 py-px font-semibold">
              ST™
            </span>
          )}
          {item.souvenir && (
            <span className="bg-bg/70 text-rarity-contraband text-meta rounded-sm px-1.5 py-px font-semibold">
              SV
            </span>
          )}
          {discount !== null && (
            <span className="bg-accent-subtle text-accent text-meta ml-auto rounded-sm px-1.5 py-px font-semibold">
              −{discount}%
            </span>
          )}
        </div>
        {rarity && (
          <span
            aria-hidden
            className="absolute inset-x-0 bottom-0 h-0.5 opacity-80"
            style={{ backgroundColor: rarity }}
          />
        )}
      </div>
      <div className="border-border flex flex-1 flex-col border-t px-3 pb-3 pt-2.5">
        {item.weapon && <div className="text-fg-dim text-label truncate">{item.weapon}</div>}
        <div className="text-small truncate font-medium">
          {isVanilla(item) ? t("vanilla") : (item.skin ?? item.name)}
          {item.phase && <span className="text-fg-dim"> · {item.phase}</span>}
        </div>
        <div className="mt-auto flex items-baseline gap-2 pt-2">
          {price ? (
            <span className="text-fg text-body font-semibold">{price}</span>
          ) : (
            <span className="text-fg-dim text-label">{t("soldOut")}</span>
          )}
          {item.count > 1 && (
            <span className="text-fg-dim num text-meta ml-auto">
              {t("pieces", { count: item.count })}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
