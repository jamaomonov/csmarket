/**
 * The hero wall: three columns of real, clickable skin cards drifting in opposite directions on
 * a slightly tilted plane. Pure CSS motion — it pauses under the pointer or keyboard focus and
 * stands still for reduced motion. Each column repeats once (hidden from assistive tech) so
 * the loop is seamless.
 */
import { formatUzs, isVanilla, type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";

import { cx, rarityVar } from "./format";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";

const STAR = new Set(["knives", "gloves"]);
const COLUMNS = 3;

interface CardProps {
  item: SkinItem;
  locale: string;
  vanilla: string;
  buy: string;
  /** The repeat that closes the loop: out of the tab order and the accessibility tree. */
  copy: boolean;
  eager: boolean;
}

function WallCard({ item, locale, vanilla, buy, copy, eager }: CardProps) {
  const name = isVanilla(item) ? vanilla : (item.skin ?? item.name);
  return (
    <Link
      className="wc"
      href={itemPath(item.slug)}
      style={rarityVar(item.rarity_color)}
      {...(copy && { tabIndex: -1 })}
    >
      <span className="wc-top">
        {item.exterior !== null && <span>{item.exterior}</span>}
        {item.stattrak && <span className="st">ST™</span>}
      </span>
      {item.image_url !== null && (
        <Image
          className="wc-img"
          src={steamImageSize(item.image_url, "256fx192f")}
          alt={copy ? "" : item.name}
          width={256}
          height={192}
          unoptimized
          loading={eager ? "eager" : "lazy"}
        />
      )}
      <span className="wc-m">
        {STAR.has(item.category) && "★ "}
        {item.weapon ?? item.name}
      </span>
      <span className="wc-n">
        {name}
        {item.phase !== null && <> · {item.phase}</>}
      </span>
      <span className="wc-f">
        {item.price_uzs !== null && (
          <span className="wc-p num">{formatUzs(locale, item.price_uzs)}</span>
        )}
        <span className="wc-buy" aria-hidden>
          {buy}
        </span>
      </span>
    </Link>
  );
}

interface Props {
  items: SkinItem[];
  locale: string;
  label: string;
  vanilla: string;
  buy: string;
}

export function HeroWall({ items, locale, label, vanilla, buy }: Props) {
  const cols = Array.from({ length: COLUMNS }, (_, c) => items.filter((_, i) => i % COLUMNS === c));
  const card = (it: SkinItem, copy: boolean, eager: boolean) => (
    <WallCard
      key={it.slug}
      item={it}
      locale={locale}
      vanilla={vanilla}
      buy={buy}
      copy={copy}
      eager={eager}
    />
  );
  return (
    <div className="wall" role="region" aria-label={label}>
      <div className="wall-plane">
        {cols.map((col, c) => (
          <div key={c} className={cx("wall-col", `wall-col-${String(c)}`)}>
            <div className="wall-track">
              <div className="wall-set">{col.map((it, i) => card(it, false, i < 2))}</div>
              <div className="wall-set" aria-hidden>
                {col.map((it) => card(it, true, false))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
