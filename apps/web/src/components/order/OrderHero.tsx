import { formatUzs } from "@csmarket/utils";
import { rarityGlow, steamImageSize } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";

import type { OrderOut } from "@/lib/orders";

import { SkinFloatBar } from "@/components/skins/SkinFloatBar";
import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";

/** `"MAC-10 | Bronzer (Battle-Scarred)"` → the weapon above, the skin's own name below. */
export function splitName(name: string): { weapon: string | null; skin: string } {
  const bare = name.replace(
    /\s\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)$/,
    "",
  );
  const cut = bare.indexOf(" | ");
  return cut < 0
    ? { weapon: null, skin: bare }
    : { weapon: bare.slice(0, cut), skin: bare.slice(cut + 3) };
}

interface OrderHeroProps {
  order: OrderOut;
  locale: string;
}

/** The bought skin, large: art over its rarity glow, the float under it, wear and pattern. */
export function OrderHero({ order, locale }: OrderHeroProps) {
  const t = useTranslations("web");
  const glow = rarityGlow(order.rarity_color);
  const { weapon, skin } = splitName(order.name);
  const float = order.float_value === null ? null : Number(order.float_value);
  const chip = "bg-surface-2 text-fg-muted rounded-md px-2.5 py-1 text-[13px]";
  return (
    <div className="bg-surface grid w-full gap-5 rounded-xl p-5 sm:grid-cols-[200px_1fr_auto] sm:items-center">
      <div className="flex flex-col items-center gap-2.5">
        <div className="relative flex h-32 w-full items-center justify-center rounded-lg">
          {glow ? (
            <span aria-hidden className="absolute inset-0" style={{ background: glow }} />
          ) : null}
          {order.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- a Steam CDN image already cut to size
            <img
              src={steamImageSize(order.image_url, "360fx270f")}
              alt=""
              className="relative max-h-full max-w-full object-contain"
            />
          ) : null}
        </div>
        {float !== null && Number.isFinite(float) ? (
          <div data-testid="order-float" className="w-full max-w-[180px]">
            <SkinFloatBar value={float} />
            <p className="text-fg-dim mt-1.5 flex justify-between text-[12px]">
              <span>{t("skins.float")}</span>
              <span className="text-fg num font-semibold">{order.float_value}</span>
            </p>
          </div>
        ) : null}
      </div>
      <div className="min-w-0">
        {weapon ? <p className="text-fg-dim text-sm">{weapon}</p> : null}
        <h2 className="text-xl font-bold">
          <Link href={itemPath(order.slug)} className="hover:underline">
            {skin}
          </Link>
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {order.exterior ? (
            <span className={chip}>{t(`skins.exterior.${order.exterior}`)}</span>
          ) : null}
          {order.phase ? <span className={chip}>{order.phase}</span> : null}
          {order.paint_seed !== null ? (
            <span className={chip}>
              {t("trades.pattern")} <b className="text-fg num font-semibold">{order.paint_seed}</b>
            </span>
          ) : null}
        </div>
      </div>
      <p className="num text-2xl font-bold sm:text-right">{formatUzs(locale, order.price_uzs)}</p>
    </div>
  );
}
