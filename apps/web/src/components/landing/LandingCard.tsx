/** A skin card in the landing's style: rarity glow, picture, model, name, price. */
import { formatUzs, isVanilla, type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";

import { rarityVar } from "./format";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";

interface Props {
  item: SkinItem;
  locale: string;
  pieces: string;
  vanilla: string;
}

export function LandingCard({ item, locale, pieces, vanilla }: Props) {
  const name = isVanilla(item) ? vanilla : (item.skin ?? item.name);
  return (
    <Link className="card" href={itemPath(item.slug)} style={rarityVar(item.rarity_color)}>
      <div className="card-top">
        {item.stattrak && <span className="st">ST™</span>}
        {item.exterior !== null && <span>{item.exterior}</span>}
        <span className="qty">{pieces}</span>
      </div>
      <div className="card-img">
        {item.image_url !== null && (
          <Image
            src={steamImageSize(item.image_url, "256fx256f")}
            alt={item.name}
            width={180}
            height={135}
            unoptimized
            loading="lazy"
          />
        )}
      </div>
      <div className="card-w">{item.weapon ?? item.name}</div>
      <div className="card-n">
        {name}
        {item.phase !== null && <> · {item.phase}</>}
      </div>
      {item.price_uzs !== null && (
        <div className="card-p num">{formatUzs(locale, item.price_uzs)}</div>
      )}
    </Link>
  );
}
