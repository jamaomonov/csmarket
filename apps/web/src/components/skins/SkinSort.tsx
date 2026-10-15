"use client";

import { skinQueryString } from "@csmarket/utils/skins";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, BadgePercent, Flame } from "lucide-react";
import { useTranslations } from "next-intl";

import type { SkinQuery, SkinSort as Sort } from "@csmarket/utils/skins";

import { SortMenu, type SortOption } from "@/components/SortMenu";
import { MARKET } from "@/lib/paths";

const ICONS = {
  "-price": ArrowDownWideNarrow,
  price: ArrowUpNarrowWide,
  popular: Flame,
  discount: BadgePercent,
} as const;
const SORTS = ["-price", "price", "popular", "discount"] as const satisfies readonly Sort[];

/** The market's order, as links: each option is the same filters with another `sort`. */
export function SkinSort({ query }: { query: SkinQuery }) {
  const t = useTranslations("web.skins");
  const options: SortOption<(typeof SORTS)[number]>[] = SORTS.map((s) => ({
    value: s,
    label: t(`sort.${s}`),
    icon: ICONS[s],
  }));
  const value = SORTS.find((s) => s === query.sort) ?? SORTS[0];
  return (
    <SortMenu
      label={t("sortLabel")}
      options={options}
      value={value}
      hrefFor={(sort) => MARKET + skinQueryString(query, { sort })}
      className="min-w-0 flex-1 sm:w-[210px] sm:flex-none"
    />
  );
}
