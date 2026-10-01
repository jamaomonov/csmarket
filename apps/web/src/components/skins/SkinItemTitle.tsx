interface SkinItemTitleProps {
  /** The skin (or «Ванильный», or the item's full name when it has no skin). */
  name: string;
  phase: string | null;
  weapon: string | null;
  stattrak: boolean;
  souvenir: boolean;
  /** The localised category, shown above the name in place of a weapon. */
  category: string;
}

/**
 * The item page's heading. The weapon (with StatTrak™ / Souvenir) sits on its own line
 * above the skin name, as before, but inside the `<h1>`: «Redline» alone would be the same
 * H1 on every weapon and variant that shares the skin. An item with no weapon and no
 * variant (a case, a sticker) already carries its full name, so its category line stays
 * outside; a StatTrak™ music kit keeps the marker (and so the category) inside.
 */
export function SkinItemTitle({
  name,
  phase,
  weapon,
  stattrak,
  souvenir,
  category,
}: SkinItemTitleProps) {
  const eyebrow = "text-fg-dim block text-[14px] font-semibold";
  const title = (
    <span className="block font-sans text-2xl font-bold md:text-3xl">
      {name}
      {phase && <span className="text-fg-muted"> · {phase}</span>}
    </span>
  );
  if (!weapon && !stattrak && !souvenir) {
    return (
      <div>
        <p className={eyebrow}>{category}</p>
        <h1>{title}</h1>
      </div>
    );
  }
  return (
    <h1>
      <span className={eyebrow}>
        {stattrak && <span className="text-orange-400">StatTrak™ </span>}
        {souvenir && <span className="text-yellow-400">Souvenir </span>}
        {weapon ?? category}
      </span>{" "}
      {title}
    </h1>
  );
}
