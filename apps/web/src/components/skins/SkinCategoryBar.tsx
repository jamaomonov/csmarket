import { chipVariants, cn } from "@csmarket/ui";
import { SKIN_CATEGORIES, weaponsOf } from "@csmarket/utils/skins";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { OtherCategoriesMenu } from "./OtherCategoriesMenu";
import { ScrollActiveIntoView } from "./ScrollActiveIntoView";
import { SkinCategoryIcon } from "./SkinCategoryIcon";
import { WeaponMenu } from "./WeaponMenu";

import type { SkinCategory, SkinFacets, SkinQuery } from "@csmarket/utils/skins";

const ORDER: SkinCategory[] = [
  "knives",
  "gloves",
  "rifles",
  "pistols",
  "smgs",
  "heavy",
  "agents",
  "cases",
  "keys",
  "charms",
  "music-kits",
];
/** Weapon categories: a chip each, with a ▾ menu of models. The rest go under «Другое». */
const WITH_MODELS: ReadonlySet<SkinCategory> = new Set([
  "knives",
  "gloves",
  "rifles",
  "pistols",
  "smgs",
  "heavy",
]);
/** Chips with a shorter label than the category's name (it must fit one row). */
const SHORT: ReadonlySet<SkinCategory> = new Set(["smgs", "heavy"]);

/** On a wide screen the chips share the panel's width; on a phone the row scrolls. */
const FILL = "lg:flex-1 lg:justify-center";

/** A chip inside the category panel: flat until hovered, green when chosen. */
const chip = (active: boolean) => cn(chipVariants({ active }), !active && "bg-transparent");

/**
 * One row of category chips with their silhouette (plain links — crawlable, no JS). A
 * chosen chip clears its category (there is no «Все» chip). Weapon categories add a ▾
 * menu of models with boxes (`WeaponMenu`); models of several categories may be ticked at
 * once, and each chip then names its own («Винтовки · AK-47», «Винтовки · 2»). The other
 * categories share one «Другое» menu; `SkinLandingLinks` keeps them crawlable from `/`.
 */
export function SkinCategoryBar({ query, facets }: { query: SkinQuery; facets: SkinFacets }) {
  const t = useTranslations("web.skins");
  const present = new Set(facets.categories.map((f) => f.value));
  const inStock = ORDER.filter(
    (c) => present.has(c) && (SKIN_CATEGORIES as readonly string[]).includes(c),
  );
  const weapons = inStock.filter((c) => WITH_MODELS.has(c));
  const others = inStock.filter((c) => !WITH_MODELS.has(c));
  const activeOther = others.find((c) => c === query.category);
  const picked = weaponsOf(query);
  /** The page's facets know a category's models when they are unscoped or scoped to it. */
  const models = (c: SkinCategory) => {
    if (query.category && query.category !== c) return undefined;
    const own = facets.weapons.filter((w) => w.category === c);
    return own.length > 0 ? own : undefined;
  };
  const categoryOf = new Map(facets.weapons.map((w) => [w.value, w.category]));
  /** The ticked models of category `c` (with `c` chosen, models it does not list count too). */
  const pickedIn = (c: SkinCategory) =>
    picked.filter((w) => categoryOf.get(w) === c || (query.category === c && !categoryOf.has(w)));

  return (
    <ScrollActiveIntoView
      activeKey={query.category ?? ""}
      className="flex gap-0.5 overflow-x-auto [scrollbar-width:none]"
    >
      {weapons.map((c) => {
        const mine = pickedIn(c);
        const active = query.category === c || mine.length > 0;
        const label = t(`category.${c}`);
        const shown = SHORT.has(c) ? t(`chipLabel.${c}`) : label;
        const known = models(c);
        const named = mine.length === 1 ? mine[0] : mine.length > 1 ? String(mine.length) : null;
        return (
          <span
            key={c}
            className={cn(chip(active), "gap-0 p-0", FILL)}
            {...(active ? { "data-active": "" } : {})}
            {...(shown !== label ? { title: label } : {})}
          >
            <WeaponMenu
              category={c}
              query={query}
              {...(known ? { initial: known } : {})}
              trigger={
                <>
                  <SkinCategoryIcon category={c} size="sm" />
                  {named ? `${shown} · ${named}` : shown}
                  <ChevronDown className="size-3.5 opacity-70" aria-hidden />
                </>
              }
            />
          </span>
        );
      })}
      {others.length > 0 && (
        // A plain wrapper marks the chosen «Другое» for ScrollActiveIntoView.
        <span className={cn("shrink-0", FILL)} {...(activeOther ? { "data-active": "" } : {})}>
          <OtherCategoriesMenu
            categories={others}
            query={query}
            {...(activeOther ? { active: activeOther } : {})}
          />
        </span>
      )}
    </ScrollActiveIntoView>
  );
}
