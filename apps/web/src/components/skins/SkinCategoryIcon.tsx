import { CATEGORY_ICONS } from "@csmarket/utils/skins";
import { LayoutGrid, Music } from "lucide-react";

import type { SkinCategory } from "@csmarket/utils/skins";

/**
 * A category's silhouette: a self-hosted Steam item image used as a CSS mask
 * over `currentColor`, so it takes the tile's grey or its active colour.
 */
interface SkinCategoryIconProps {
  category: SkinCategory | "all";
  /** `sm` sits beside a chip's label; `md` (default) tops a tile. */
  size?: "sm" | "md";
}

export function SkinCategoryIcon({ category, size = "md" }: SkinCategoryIconProps) {
  const icon = category === "all" ? null : CATEGORY_ICONS[category];
  const glyph = size === "sm" ? "h-3.5 w-3.5" : "h-5 w-5";
  if (category === "all") return <LayoutGrid className={glyph} aria-hidden />;
  if (icon === null) return <Music className={glyph} aria-hidden />;
  const url = `url(/skins/categories/${icon.file})`;
  return (
    <span
      data-skin-icon
      aria-hidden
      className={
        size === "sm"
          ? `block h-[14px] shrink-0 bg-current ${icon.wide ? "w-[26px]" : "w-[16px]"}`
          : `block h-[26px] bg-current ${icon.wide ? "w-[48px]" : "w-[30px]"}`
      }
      style={{
        maskImage: url,
        WebkitMaskImage: url,
        maskSize: icon.wide ? "100% auto" : "118% auto",
        WebkitMaskSize: icon.wide ? "100% auto" : "118% auto",
        maskPosition: "center",
        WebkitMaskPosition: "center",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
      }}
    />
  );
}
