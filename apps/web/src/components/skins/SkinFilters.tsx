import { Accordion, buttonVariants, CheckMark } from "@csmarket/ui";
import { activeFilterCount, filterSections, skinQueryString } from "@csmarket/utils/skins";
import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import { SkinPriceFilter } from "./SkinPriceFilter";

import type { SkinQueryPatch, Exterior, SkinFacets, SkinQuery } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { MARKET } from "@/lib/paths";

const EXTERIORS: Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

function option(active: boolean): string {
  return `flex items-center gap-2.5 rounded-md px-1 py-1.5 text-[14px] transition-colors ${
    active ? "text-fg" : "text-fg-muted hover:text-fg"
  }`;
}

/**
 * The filter panel. Price applies itself as it is typed (`SkinPriceFilter`); wear,
 * rarity and StatTrak are links that toggle one value each, drawn as checkboxes. The page
 * places it twice: a sticky column on desktop, a bottom drawer on a phone.
 * Counts are scoped to the chosen category (the facets are), and so are the sections:
 * `filterSections` drops what the category does not have.
 */
export function SkinFilters({ query, facets }: { query: SkinQuery; facets: SkinFacets }) {
  const t = useTranslations("web.skins");
  const active = activeFilterCount(query);
  const href = (patch: SkinQueryPatch) => MARKET + skinQueryString(query, patch);
  // Only the filters this category has: no wear on agents or cases, StatTrak only where
  // it exists, the category's own rarities (the weapon scale when none is picked).
  const show = filterSections(query.category, facets, query.rarity);

  return (
    <div>
      <Accordion title={t("price")} defaultOpen>
        <SkinPriceFilter query={query} />
      </Accordion>

      {show.team && (
        <Accordion title={t("team.title")} defaultOpen>
          <ul role="radiogroup" aria-label={t("team.title")}>
            {([undefined, "ct", "t"] as const).map((side) => {
              const on = query.team === side;
              return (
                <li key={side ?? "all"}>
                  <Link
                    href={href({ team: side })}
                    role="radio"
                    aria-checked={on}
                    className={option(on)}
                  >
                    <span
                      aria-hidden
                      className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${
                        on ? "border-accent" : "border-border-strong"
                      }`}
                    >
                      {on && <span className="bg-accent size-2 rounded-full" />}
                    </span>
                    <span className="flex-1">{t(`team.${side ?? "all"}`)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </Accordion>
      )}

      {show.wear && (
        <Accordion title={t("wear")} defaultOpen>
          <ul>
            {EXTERIORS.map((e) => (
              <li key={e}>
                <Link
                  href={href({ exterior: query.exterior === e ? undefined : e })}
                  className={option(query.exterior === e)}
                  aria-current={query.exterior === e ? "true" : undefined}
                >
                  <CheckMark checked={query.exterior === e} />
                  <span className="flex-1">{t(`exterior.${e}`)}</span>
                  <span className="text-fg-dim text-[12px]">{e}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Accordion>
      )}

      {show.rarities.length > 0 && (
        // Agents have no wear: their rarity is the first thing to filter by.
        <Accordion title={t("rarity")} defaultOpen={query.rarity !== undefined || !show.wear}>
          <ul>
            {show.rarities.map((r) => (
              <li key={r.value}>
                <Link
                  href={href({ rarity: query.rarity === r.value ? undefined : r.value })}
                  className={option(query.rarity === r.value)}
                  aria-current={query.rarity === r.value ? "true" : undefined}
                >
                  <CheckMark checked={query.rarity === r.value} />
                  <span className="flex flex-1 items-center gap-2">
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: r.color ?? "currentColor" }}
                      aria-hidden
                    />
                    {r.value}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Accordion>
      )}

      {(show.stattrak || query.stattrak === true) && (
        <Accordion title={t("stattrakTitle")} defaultOpen={query.stattrak === true}>
          <Link
            href={href({ stattrak: query.stattrak ? undefined : true })}
            className={option(query.stattrak === true)}
            aria-current={query.stattrak ? "true" : undefined}
          >
            <CheckMark checked={query.stattrak === true} />
            {t("stattrak")}
          </Link>
        </Accordion>
      )}

      {active > 0 && (
        <Link
          href={href({
            exterior: undefined,
            rarity: undefined,
            team: undefined,
            stattrak: undefined,
            minUzs: undefined,
            maxUzs: undefined,
          })}
          className={`${buttonVariants({ variant: "secondary", size: "sm" })} mt-4 w-full`}
        >
          <RotateCcw className="h-4 w-4" aria-hidden />
          {t("reset")}
          <span className="bg-accent text-accent-fg rounded-full px-1.5 text-[11px] font-bold leading-[18px]">
            {active}
          </span>
        </Link>
      )}
    </div>
  );
}
