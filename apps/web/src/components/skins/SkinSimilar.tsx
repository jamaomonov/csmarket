import type { SkinItem } from "@csmarket/utils/skins";

import { SkinCard } from "@/components/skins/SkinCard";
import { Link } from "@/i18n/navigation";

interface Props {
  title: string;
  items: SkinItem[];
  locale: string;
  /** The landing these skins belong to (`/weapon/ak-47`, `/category/cases`). */
  allHref: string;
  allLabel: string;
}

/**
 * «Другие скины AK-47»: the item's neighbours as cards, and a link to their landing — the
 * internal links every leading market puts under an item. Nothing when there are none.
 */
export function SkinSimilar({ title, items, locale, allHref, allLabel }: Props) {
  if (items.length === 0) return null;
  return (
    <section className="mt-10" aria-labelledby="skin-similar">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="skin-similar" className="text-[17px] font-bold">
          {title}
        </h2>
        <Link href={allHref} className="text-accent text-[14px] font-semibold hover:underline">
          {allLabel}
        </Link>
      </div>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {items.map((it) => (
          <li key={it.slug}>
            <SkinCard item={it} locale={locale} />
          </li>
        ))}
      </ul>
    </section>
  );
}
