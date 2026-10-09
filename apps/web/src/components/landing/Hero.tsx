/** The first screen: the geo H1, the lead, two calls to action, payments and the showcase. */
import { formatUzs, type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import { getTranslations } from "next-intl/server";

import { HeroStage, type StageItem } from "./HeroStage";
import { ArrowIcon } from "./Icons";
import { PayMarks } from "./Wordmarks";

import { Link } from "@/i18n/navigation";
import { itemPath, MARKET, SELL } from "@/lib/paths";

const STAR_CATEGORIES = new Set(["knives", "gloves"]);

function toStage(item: SkinItem, locale: string): StageItem | null {
  if (item.image_url === null) return null;
  const title = [item.skin ?? item.name, item.phase].filter(Boolean).join(" · ");
  return {
    slug: item.slug,
    href: itemPath(item.slug),
    model: item.weapon ?? item.name,
    title,
    wear: item.exterior,
    rarity: item.rarity,
    color: item.rarity_color ?? "#eb4b4b",
    star: STAR_CATEGORIES.has(item.category),
    price: item.price_uzs === null ? null : formatUzs(locale, item.price_uzs),
    image: steamImageSize(item.image_url, "512fx384f"),
    thumb: steamImageSize(item.image_url, "128fx96f"),
    alt: item.name,
  };
}

export async function Hero({ items, locale }: { items: SkinItem[]; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing" });
  const stage = items.map((i) => toStage(i, locale)).filter((i): i is StageItem => i !== null);
  return (
    <section className="hero" aria-labelledby="lp-h1">
      <div className="wrap">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="flag" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            {t("eyebrow")}
          </span>
          <h1 id="lp-h1">
            {t("h1.pre") !== "" && <>{t("h1.pre")} </>}
            <span className="hl">{t("h1.hl")}</span> {t("h1.post")}
            <span className="sub">{t("h1.sub")}</span>
          </h1>
          <p className="lead">{t("lead")}</p>
          <div className="cta">
            <Link className="btn btn-primary" href={MARKET}>
              {t("openMarket")}
              <ArrowIcon />
            </Link>
            <Link className="btn btn-secondary" href={SELL}>
              {t("sellSkins")}
            </Link>
          </div>
          <div className="paywith">
            <span className="pw-l">{t("payWith")}</span>
            <PayMarks balance={t("balance")} />
          </div>
        </div>
        {stage.length > 0 && (
          <HeroStage
            items={stage}
            buy={t("buy")}
            showcase={t("showcase")}
            toastTitle={t("toastTitle")}
            toastText={t("toastText")}
          />
        )}
      </div>
    </section>
  );
}
