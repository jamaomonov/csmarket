import { cn } from "@csmarket/ui";
import { rarityGlow, steamImageSize } from "@csmarket/utils/skins";

interface ItemThumbProps {
  imageUrl: string | null;
  rarityColor: string | null;
  /** How many more items stand behind this one («+3»); 0 shows nothing. */
  more?: number;
  className?: string;
}

/** A skin's picture over its rarity glow, as the market's cards show it. */
export function ItemThumb({ imageUrl, rarityColor, more = 0, className }: ItemThumbProps) {
  const glow = rarityGlow(rarityColor);
  return (
    <span className={cn("bg-surface-2 relative flex h-14 w-[76px] shrink-0 rounded-md", className)}>
      {glow ? (
        <span aria-hidden className="absolute inset-0 rounded-md" style={{ background: glow }} />
      ) : null}
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- a Steam CDN image already cut to size
        <img
          src={steamImageSize(imageUrl, "128fx96f")}
          alt=""
          className="relative m-auto max-h-[85%] max-w-[90%] object-contain"
        />
      ) : null}
      {more > 0 ? (
        <span className="bg-surface-2 border-surface text-fg num absolute -bottom-1.5 -right-1.5 rounded-full border-2 px-1.5 text-[12px] font-bold">
          +{more}
        </span>
      ) : null}
    </span>
  );
}
