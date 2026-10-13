import { colorParam, colorsOf, MAX_COLORS } from "@csmarket/utils/skins";
import { useTranslations } from "next-intl";

import type { Facet, SkinQuery, SkinQueryPatch } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { isSkinColor, swatchBackground } from "@/lib/skin-colors";

interface Props {
  query: SkinQuery;
  /** The colours with items here, in swatch order. */
  colors: Facet[];
  href: (patch: SkinQueryPatch) => string;
}

/**
 * «Цвет»: one round swatch per colour, several at once (up to three, the API's limit). Each
 * toggles its colour in the URL; the chosen ones wear a ring. The name and the count are the
 * link's label and tooltip.
 */
export function SkinColorFilter({ query, colors, href }: Props) {
  const t = useTranslations("web.skins.color");
  const chosen = colorsOf(query);
  return (
    <ul className="grid grid-cols-6 gap-2 pt-1" aria-label={t("title")}>
      {colors.flatMap((f) => {
        if (!isSkinColor(f.value)) return [];
        const c = f.value;
        const on = chosen.includes(c);
        const next = on ? chosen.filter((x) => x !== c) : [...chosen, c].slice(-MAX_COLORS);
        const label = `${t(`names.${c}`)} · ${String(f.count)}`;
        return [
          <li key={c} className="flex justify-center">
            <Link
              href={href({ color: colorParam(next) })}
              aria-label={label}
              aria-current={on ? "true" : undefined}
              title={label}
              className={`flex size-9 items-center justify-center rounded-full ring-offset-2 transition-shadow ${
                on ? "ring-accent ring-2" : "hover:ring-border-strong hover:ring-2"
              } ring-offset-[var(--color-surface)]`}
            >
              <span
                aria-hidden
                className="size-7 rounded-full shadow-[inset_0_0_0_1px_rgba(127,127,127,0.45)]"
                style={{ background: swatchBackground(c) }}
              />
            </Link>
          </li>,
        ];
      })}
    </ul>
  );
}
