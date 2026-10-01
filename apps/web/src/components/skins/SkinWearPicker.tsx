import { wearChoices } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";

import type { SkinFamilyMember } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";
import { displayPrice } from "@/lib/skins";

type Current = Pick<SkinFamilyMember, "slug" | "exterior" | "stattrak" | "souvenir">;

/**
 * Wear as tiles in plain words with each wear's price, and StatTrak™/Souvenir as toggles —
 * the old grid of «ST · FT» tiles made people decode two things at once. A wear
 * with no copies on sale is shown greyed, not hidden, so the range is visible.
 */
export function SkinWearPicker({
  family,
  current,
  locale,
}: {
  family: SkinFamilyMember[];
  current: Current;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  const c = wearChoices(family, current);
  const toggles = [
    { label: "StatTrak™", toggle: c.stattrak, tone: "text-orange-400 border-orange-400/60" },
    { label: "Souvenir", toggle: c.souvenir, tone: "text-yellow-400 border-yellow-400/60" },
  ].filter(({ toggle }) => toggle.slug !== null || toggle.on);

  return (
    <div className="space-y-3">
      {c.wears.length > 1 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {c.wears.map((w) => {
            const active = w.slug === current.slug;
            const cls = `block rounded-xl border px-3 py-2 text-left transition ${
              active
                ? "border-accent bg-accent/10"
                : w.available
                  ? "border-border bg-surface hover:border-border-strong"
                  : "border-border bg-surface opacity-50"
            }`;
            const price = w.available ? displayPrice(locale, w.price_uzs, w.price_usd) : null;
            const label = (
              <>
                <span className="text-fg-muted block text-[12px] font-semibold leading-tight">
                  {t(`exterior.${w.exterior}`)}
                </span>
                <span className="block whitespace-nowrap text-[13px] font-bold tabular-nums">
                  {price ?? "—"}
                </span>
              </>
            );
            return w.slug === null ? (
              <span key={w.exterior} className={`${cls} cursor-not-allowed`}>
                {label}
              </span>
            ) : (
              <Link
                key={w.exterior}
                href={itemPath(w.slug)}
                className={cls}
                aria-current={active ? "page" : undefined}
                aria-disabled={w.available ? undefined : true}
              >
                {label}
              </Link>
            );
          })}
        </div>
      )}
      {toggles.length > 0 && (
        <div className="flex gap-2">
          {toggles.map(({ label, toggle, tone }) => (
            <Link
              key={label}
              href={itemPath(toggle.slug ?? current.slug)}
              aria-current={toggle.on ? "page" : undefined}
              className={`rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition ${
                toggle.on ? tone : "border-border text-fg-muted hover:border-border-strong"
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
