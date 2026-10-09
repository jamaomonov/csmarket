/** The first screen: the geo H1, the lead, two calls to action, payments and the wall of skins. */
import { getTranslations } from "next-intl/server";

import { HeroWall } from "./HeroWall";
import { ArrowIcon } from "./Icons";
import { PayMarks } from "./Wordmarks";

import type { SkinItem } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { MARKET, SELL } from "@/lib/paths";

export async function Hero({ items, locale }: { items: SkinItem[]; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing" });
  const tSkins = await getTranslations({ locale, namespace: "web.skins" });
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
            <PayMarks />
          </div>
        </div>
        {items.length > 0 && (
          <HeroWall
            items={items}
            locale={locale}
            label={t("showcase")}
            vanilla={tSkins("vanilla")}
            buy={t("buy")}
          />
        )}
      </div>
    </section>
  );
}
