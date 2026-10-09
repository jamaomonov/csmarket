/** Four figures the catalogue backs: items in stock, payment methods, the cheapest price, languages. */
import { getTranslations } from "next-intl/server";

import { groupDigits } from "./format";

import type { LandingStats } from "@/lib/landing";

/** Rounded down to the thousand and marked «+» — the count moves every few minutes. */
function roundedDown(n: number): number {
  return n >= 1000 ? Math.floor(n / 1000) * 1000 : n;
}

export async function Stats({ stats, locale }: { stats: LandingStats; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.stats" });
  const from = groupDigits(locale, stats.fromUzs);
  return (
    <section style={{ paddingTop: 64 }} aria-label={t("label")}>
      <div className="wrap">
        <div className="stats rv">
          {stats.inStock > 0 && (
            <div className="stat">
              <b className="num">
                {groupDigits(locale, roundedDown(stats.inStock))}
                <em>+</em>
              </b>
              <span>{t("skins")}</span>
            </div>
          )}
          <div className="stat">
            <b className="num">3</b>
            <span>{t("payments")}</span>
          </div>
          {from !== null && (
            <div className="stat">
              <b className="num">{t("from", { price: from })}</b>
              <span>{t("perSkin")}</span>
            </div>
          )}
          <div className="stat">
            <b>RU · UZ</b>
            <span>{t("support")}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
