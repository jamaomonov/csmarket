import { chipVariants, cn } from "@csmarket/ui";
import { SKIN_CATEGORIES, skinQueryString } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";

import { OtherCategoriesMenu } from "./OtherCategoriesMenu";
import { ScrollActiveIntoView } from "./ScrollActiveIntoView";
import { SkinCategoryIcon } from "./SkinCategoryIcon";
import { WeaponMenu } from "./WeaponMenu";

import type { SkinCategory, SkinFacets, SkinQuery, SkinQueryPatch } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { HOME } from "@/lib/paths";

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

/** A chip inside the category panel: flat until hovered, green when chosen. */
const chip = (active: boolean) => cn(chipVariants({ active }), !active && "bg-transparent");

/**
 * One row of category chips with their silhouette (plain links — crawlable, no JS);
 * weapon categories add a ▾ menu of models (`WeaponMenu`, loaded on first open). With a
 * model chosen the active chip names it and links back to the whole category. The other
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
  const href = (patch: SkinQueryPatch) => HOME + skinQueryString(query, patch);

  return (
    <ScrollActiveIntoView
      activeKey={query.category ?? ""}
      className="flex gap-0.5 overflow-x-auto [scrollbar-width:none]"
    >
      <Link
        href={href({ category: undefined, weapon: undefined })}
        className={chip(!query.category)}
        aria-current={!query.category ? "page" : undefined}
      >
        <SkinCategoryIcon category="all" size="sm" />
        {t("all")}
      </Link>
      {weapons.map((c) => {
        const active = query.category === c;
        const label = t(`category.${c}`);
        const shown = SHORT.has(c) ? t(`chipLabel.${c}`) : label;
        return (
          <span key={c} className={cn(chip(active), "gap-0 p-0")}>
            <Link
              href={href({ category: c, weapon: undefined })}
              className="focus-visible:ring-accent focus-visible:ring-offset-bg flex items-center gap-2 rounded-md py-2 pl-2.5 pr-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
              aria-current={active ? "page" : undefined}
              {...(shown !== label ? { title: label } : {})}
            >
              <SkinCategoryIcon category={c} size="sm" />
              {active && query.weapon ? `${shown} · ${query.weapon}` : shown}
            </Link>
            <WeaponMenu
              category={c}
              label={label}
              query={query}
              {...(active ? { initial: facets.weapons } : {})}
            />
          </span>
        );
      })}
      {others.length > 0 && (
        // A plain wrapper marks the chosen «Другое» for ScrollActiveIntoView.
        <span className="shrink-0" {...(activeOther ? { "data-active": "" } : {})}>
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
