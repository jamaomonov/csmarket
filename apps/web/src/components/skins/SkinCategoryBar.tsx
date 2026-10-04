import { chipVariants } from "@csmarket/ui";
import { SKIN_CATEGORIES, skinQueryString } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";

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
const WITH_MODELS: ReadonlySet<SkinCategory> = new Set([
  "knives",
  "gloves",
  "rifles",
  "pistols",
  "smgs",
  "heavy",
]);

/**
 * Categories as chips with their silhouette (plain links — crawlable, no JS); weapon
 * categories add a ▾ menu of models (`WeaponMenu`, loaded on first open). With a model
 * chosen the active chip names it and links back to the whole category.
 */
export function SkinCategoryBar({ query, facets }: { query: SkinQuery; facets: SkinFacets }) {
  const t = useTranslations("web.skins");
  const present = new Set(facets.categories.map((f) => f.value));
  const categories = ORDER.filter(
    (c) => present.has(c) && (SKIN_CATEGORIES as readonly string[]).includes(c),
  );
  const href = (patch: SkinQueryPatch) => HOME + skinQueryString(query, patch);

  return (
    <ScrollActiveIntoView
      activeKey={query.category ?? ""}
      className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:flex-wrap lg:overflow-visible"
    >
      <Link
        href={href({ category: undefined, weapon: undefined })}
        className={chipVariants({ active: !query.category })}
        aria-current={!query.category ? "page" : undefined}
      >
        <SkinCategoryIcon category="all" size="sm" />
        {t("all")}
      </Link>
      {categories.map((c) => {
        const active = query.category === c;
        const label = t(`category.${c}`);
        const menu = WITH_MODELS.has(c);
        return (
          <span key={c} className={`${chipVariants({ active })} gap-0 p-0 ${menu ? "" : ""}`}>
            <Link
              href={href({ category: c, weapon: undefined })}
              className={`flex items-center gap-2 py-2 pl-3.5 ${menu ? "pr-1" : "pr-3.5"} focus-visible:ring-accent rounded-md focus-visible:outline-none focus-visible:ring-2`}
              aria-current={active ? "page" : undefined}
            >
              <SkinCategoryIcon category={c} size="sm" />
              {active && query.weapon ? `${label} · ${query.weapon}` : label}
            </Link>
            {menu && (
              <WeaponMenu
                category={c}
                label={label}
                query={query}
                {...(active ? { initial: facets.weapons } : {})}
              />
            )}
          </span>
        );
      })}
    </ScrollActiveIntoView>
  );
}
