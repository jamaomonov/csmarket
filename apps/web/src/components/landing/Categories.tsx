/**
 * «Что купить»: two large tiles (knives, gloves) and small ones, each with a real skin and price;
 * a «whole catalogue» tile closes a short last row.
 */
import { formatUzs, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { cx } from "./format";
import { ArrowIcon } from "./Icons";

import type { CSSProperties } from "react";

import { Link } from "@/i18n/navigation";
import { BIG_TILES, type CategoryTile } from "@/lib/landing";
import { categoryPath, MARKET } from "@/lib/paths";

const BIG = new Set<string>(BIG_TILES);

export async function Categories({ tiles, locale }: { tiles: CategoryTile[]; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.cats" });
  const tSkins = await getTranslations({ locale, namespace: "web.skins.category" });
  const shown = tiles.filter((tile) => tile.item !== null || tile.count > 0);
  const small = shown.filter((tile) => !BIG.has(tile.category)).length;
  const total = tiles.reduce((sum, tile) => sum + tile.count, 0);
  return (
    <section aria-labelledby="lp-cats">
      <div className="wrap">
        <div className="sec-h">
          <div>
            <div className="kicker">{t("kicker")}</div>
            <h2 id="lp-cats">{t("title")}</h2>
          </div>
          <Link className="more" href={MARKET}>
            {t("all")}
            <ArrowIcon />
          </Link>
        </div>
        <div className="cats">
          {shown.map((tile) => {
            const price = tile.fromUzs === null ? null : formatUzs(locale, tile.fromUzs);
            const style = {
              // The site's green behind every picture: the tiles show green skins (owner,
              // 2026-10-10), and one glow keeps the grid a single palette.
              "--r": "#4bf364",
              "--m": `url(/skins/categories/${tile.category}.png)`,
            } as CSSProperties; // CSS custom properties
            return (
              <Link
                key={tile.category}
                href={categoryPath(tile.category)}
                className={cx("cat rv", BIG.has(tile.category) && "cat--big")}
                style={style}
              >
                <span className="cat-go" aria-hidden>
                  <ArrowIcon />
                </span>
                {tile.item?.image_url && (
                  <Image
                    className="cat-img"
                    src={steamImageSize(tile.item.image_url, "256fx192f")}
                    alt=""
                    width={256}
                    height={192}
                    unoptimized
                    loading="lazy"
                  />
                )}
                <span className="cat-t">
                  <span className="cat-ic" aria-hidden />
                  {tSkins(tile.category)}
                </span>
                {price !== null && <span className="cat-p">{t("from", { price })}</span>}
              </Link>
            );
          })}
          {small % 4 !== 0 && (
            <Link href={MARKET} className="cat cat--all rv">
              <span className="cat-go" aria-hidden>
                <ArrowIcon />
              </span>
              <span className="cat-t">{t("all")}</span>
              {total > 0 && <span className="cat-p">{t("count", { count: total })}</span>}
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
