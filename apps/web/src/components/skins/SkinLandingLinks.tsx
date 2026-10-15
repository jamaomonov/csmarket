import { getTranslations } from "next-intl/server";

import type { SkinFacets } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { categoryPath, colorPath, weaponPath } from "@/lib/paths";
import { isSkinColor } from "@/lib/skin-colors";
import { isSkinCategory, weaponSlug } from "@/lib/skin-landing";

/** How many weapons the hub links to — the most stocked ones. */
const TOP_WEAPONS = 16;

/**
 * The hub's links to its landing pages: every section («Ножи CS2») and the most stocked
 * weapons («Скины AK-47») — how a crawler, and a browsing buyer, reaches them from `/`.
 */
export async function SkinLandingLinks({ facets }: { facets: SkinFacets }) {
  const t = await getTranslations("web.skins");
  const groups = [
    {
      title: t("landing.categories"),
      links: facets.categories.flatMap((c) =>
        isSkinCategory(c.value)
          ? [
              {
                label: t("landing.categoryH1", { name: t(`category.${c.value}`) }),
                path: categoryPath(c.value),
              },
            ]
          : [],
      ),
    },
    {
      title: t("landing.popular"),
      links: [...facets.weapons]
        .sort((a, b) => b.count - a.count)
        .slice(0, TOP_WEAPONS)
        .map((w) => ({
          label: t("landing.weaponH1", { weapon: w.value }),
          path: weaponPath(weaponSlug(w.value)),
        })),
    },
    {
      title: t("color.title"),
      links: (facets.colors ?? []).flatMap((c) =>
        isSkinColor(c.value)
          ? [
              {
                label: t("color.h1", { plural: t(`color.plural.${c.value}`) }),
                path: colorPath(c.value),
              },
            ]
          : [],
      ),
    },
  ].filter((g) => g.links.length > 0);
  return (
    <nav
      className="border-border mt-10 space-y-5 border-t pt-6"
      aria-label={t("landing.categories")}
    >
      {groups.map((g) => (
        <div key={g.title}>
          <h2 className="text-lead mb-2 font-bold">{g.title}</h2>
          <ul className="flex flex-wrap gap-2">
            {g.links.map((l) => (
              <li key={l.path}>
                <Link
                  href={l.path}
                  className="border-border hover:border-border-strong text-fg-muted hover:text-fg text-small inline-block rounded-full border px-3 py-1.5"
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
