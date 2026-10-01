import { getTranslations } from "next-intl/server";

import type { SkinFacets } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { categoryPath, weaponPath } from "@/lib/paths";
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
  ];
  return (
    <nav
      className="border-border mt-10 space-y-5 border-t pt-6"
      aria-label={t("landing.categories")}
    >
      {groups.map((g) => (
        <div key={g.title}>
          <h2 className="mb-2 text-[15px] font-bold">{g.title}</h2>
          <ul className="flex flex-wrap gap-2">
            {g.links.map((l) => (
              <li key={l.path}>
                <Link
                  href={l.path}
                  className="border-border hover:border-border-strong text-fg-muted hover:text-fg inline-block rounded-full border px-3 py-1.5 text-[13px]"
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
